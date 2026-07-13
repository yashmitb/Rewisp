"""Promises — catch commitments you (or others) made on screen, hold them,
surface them. "I'll send it tomorrow", "please reply by Friday."

Detection is fully local and cheap: regex for commitment shapes + Apple's
NSDataDetector for the deadline. No model, no cloud call. New promises land as
Pending in the existing review flow, so precision is the human's call — the
detector can be a little liberal without polluting anything.
"""

import logging
import re

from . import db

log = logging.getLogger("rewisp")

# Action verbs that make a commitment real (filters out idle "I will" chatter).
_VERB = (r"(?:send|sends|sending|reply|replies|replying|respond|email|finish|"
         r"submit|review|call|share|deliver|sign|return|pay|get back|"
         r"follow up|circle back|send over|get you|send you)")

# You committing: "I'll send…", "I will review…", "let me get back to you".
_ME = re.compile(rf"\b(?:i'?ll|i will|i can|i'?m going to|i plan to|let me|i'?ll go ahead and)\b[^.?!\n]*?\b{_VERB}\b[^.?!\n]{{0,60}}", re.I)
# Owed to you: "please reply by…", "can you send…", "get back to me by…".
_THEM = re.compile(rf"\b(?:please|can you|could you|would you|will you|make sure to|don'?t forget to)\b[^.?!\n]*?\b{_VERB}\b[^.?!\n]{{0,60}}", re.I)
# A deadline anywhere in the clause strengthens confidence.
_DEADLINE = re.compile(
    r"\b(?:by|before|due|no later than)\s+(?:eod|cob|end of day|today|tonight|tomorrow|"
    r"this week|next week|mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{1,2}(?:st|nd|rd|th)?)",
    re.I)

_SENT_SPLIT = re.compile(r"[.?!\n]")


def _extract_due(text: str) -> str | None:
    """Resolve a natural-language deadline to an ISO date via NSDataDetector."""
    try:
        import Foundation
        det, _ = Foundation.NSDataDetector.dataDetectorWithTypes_error_(
            Foundation.NSTextCheckingTypeDate, None)
        if det is None:
            return None
        rng = Foundation.NSMakeRange(0, len(text))
        for m in det.matchesInString_options_range_(text, 0, rng):
            d = m.date()
            if d is not None:
                return d.descriptionWithCalendarFormat_timeZone_locale_(
                    "%Y-%m-%d", None, None) if hasattr(d, "descriptionWithCalendarFormat_timeZone_locale_") \
                    else str(d)[:10]
    except Exception:  # noqa: BLE001 — date detection is best-effort
        pass
    return None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()[:140]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()[:60]


def detect(text: str) -> list[dict]:
    """Find commitments in a block of text. Returns
    [{who:'me'|'them', what, due, confidence}], deduped within the block."""
    out: list[dict] = []
    seen: list[str] = []
    for sent in _SENT_SPLIT.split(text):
        sent = sent.strip()
        if len(sent) < 8 or len(sent) > 200:
            continue
        if len(re.findall(r"[a-zA-Z]{2,}", sent)) < 4:
            continue                              # OCR garbage / not a real sentence
        for who, pat in (("me", _ME), ("them", _THEM)):
            m = pat.search(sent)
            if not m:
                continue
            what = _clean(m.group(0))
            key = _norm(what)
            if len(key) < 6 or any(key in s or s in key for s in seen):
                continue                          # substring dup (one promise, reworded)
            seen.append(key)
            has_deadline = bool(_DEADLINE.search(sent))
            due = _extract_due(sent) if has_deadline else None
            out.append({
                "who": who,
                "what": what,
                "due": due,
                "confidence": 0.85 if has_deadline else 0.6,
            })
            break  # one promise per sentence
    return out


def scan_and_store(conn, wisp_id: int, text: str, min_conf: float = 0.85,
                   max_per_capture: int = 3) -> int:
    """Detect promises in a capture and store new ones as Pending. Only commitments
    with a real deadline are auto-stored (min_conf 0.85) — deadline-less matches
    and web boilerplate ('please email me at…') are too noisy on ambient screen
    text. Dedups against recent promises. Returns how many were added."""
    found = [p for p in detect(text) if p["confidence"] >= min_conf][:max_per_capture]
    if not found:
        return 0
    # Dedup against recent promises by normalized substring (handles apostrophes
    # and rewordings that a raw SQL LIKE would miss).
    recent = conn.execute(
        "SELECT what FROM promises WHERE status IN ('pending','confirmed') "
        "AND created_at >= datetime('now','-7 days')").fetchall()
    known = [_norm(r[0]) for r in recent]
    added = 0
    for p in found:
        norm = _norm(p["what"])
        if any(norm in k or k in norm for k in known):
            continue
        db.add_promise(conn, wisp_id, p["who"], p["what"], p["due"], p["confidence"])
        known.append(norm)
        added += 1
    if added:
        log.info("promises: stored %d from wisp #%s", added, wisp_id)
    return added
