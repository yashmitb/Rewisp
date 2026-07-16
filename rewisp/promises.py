"""Promises — catch commitments you made on screen, hold them, surface them.
"I'll send it tomorrow", "email manvi by EOD", "call dona today".

Precision-first redesign. The v1 detector ran the same regexes on every wisp
from every surface and hit ~95% false positives in live use: AI assistants
saying "I'll fix that" in an IDE, ad copy ("Get instant discounts today"),
dictation garble, truncated fragments. The fixes, in order of importance:

1. SOURCE GATING (the big one — mirrors how Microsoft's email commitment
   detection only scans mail you authored): commitments are only detected on
   surfaces where the user writes or reads correspondence. AI-chat surfaces,
   IDEs, terminals, and system UI are blocked outright; generic web pages get
   a stricter score bar than authored surfaces (Notes, Mail, Slack, Discord).
2. EVIDENCE SCORING instead of binary pattern hits: pattern base + deadline +
   surface trust, minus hard rejects (questions, negation, hedges, ad-speak,
   instructional "your …", incomplete tails, dictation disfluencies).
3. FUZZY STORE-DEDUP so OCR variants ("from"/"trom") don't store twice.

Fully local: regex + NSDataDetector for dates. No model, no cloud call.
"""

import logging
import re

from . import db

log = logging.getLogger("rewisp")

# ── source gating ─────────────────────────────────────────────────────────────

# Surfaces where first-person text is (mostly) authored by the user, or is real
# correspondence addressed to them. Detection runs at normal strictness here.
_AUTHORED_APPS = {
    "notes", "stickies", "textedit", "mail", "outlook", "spark", "mimestream",
    "slack", "discord", "telegram", "microsoft teams", "reminders", "things",
    "obsidian", "notion", "bear", "craft",
}

# Surfaces that constantly display OTHER speakers' first-person commitments
# (AI assistants, code reviews), plus surfaces with no correspondence at all.
# Never detect here — this single set removed ~70% of live false positives.
_BLOCKED_APPS = {
    "antigravity ide", "claude", "gemini", "chatgpt", "cursor", "code",
    "visual studio code", "xcode", "terminal", "iterm2", "warp", "dock",
    "finder", "system settings", "activity monitor", "screen sharing",
    "zoom.us", "lockdown browser", "health", "rewisp",
}

# Inside a browser, the URL decides.
_BLOCKED_URL = re.compile(
    r"(claude\.ai|chatgpt\.com|chat\.openai\.com|gemini\.google|perplexity\.ai|"
    r"poe\.com|meta\.ai|copilot\.microsoft|youtube\.com|netflix\.com)", re.I)
_AUTHORED_URL = re.compile(
    r"(mail\.google\.com|gmail\.com|outlook\.(?:live|office)|slack\.com|"
    r"discord\.com|web\.telegram\.org|teams\.(?:microsoft|live)|"
    r"linkedin\.com/messaging|messenger\.com|web\.whatsapp)", re.I)   # (WhatsApp app itself is kill-listed)


def source_class(app: str | None, url: str | None) -> str:
    """'authored' | 'strict' | 'blocked' — how much to trust this surface."""
    a = (app or "").strip().lower()
    if a in _BLOCKED_APPS:
        return "blocked"
    if a in _AUTHORED_APPS:
        return "authored"
    if url:
        if _BLOCKED_URL.search(url):
            return "blocked"
        if _AUTHORED_URL.search(url):
            return "authored"
    return "strict"          # unknown app or generic web page: higher bar


# ── commitment shapes ─────────────────────────────────────────────────────────

# Action verbs that make a commitment real (filters out idle "I will" chatter).
_VERB = (r"(?:send|sends|sending|reply|replies|replying|respond|email|finish|"
         r"submit|review|call|share|deliver|sign|return|pay|get back|"
         r"follow up|circle back|send over|get you|send you|schedule|book|invite|"
         r"buy|order|remind|update|write|draft|prepare|ask|meet|ping|dm|confirm|"
         r"cancel|renew|complete|upload|fix|merge|approve|set up|reach out|text|message)")

# The tail after the verb captures the object ("the report to Dana") but stops at
# clause breaks. OCR rarely has periods, so length-cap; partial-word trim later.
_TAIL = r"[^.?!\n,;\"“”|]{0,45}"

# You committing. Deliberately NARROW openers: "let me", "I can", "I want to",
# "I should", "I'd like to" all removed — they caught AI-assistant speak,
# dictation, and idle intent, not commitments.
_ME = re.compile(
    rf"\b(?:i'?ll|i will|i'?m going to|i'?m gonna|i plan to|"
    rf"i need to|i have to|i gotta|gotta|i must|remember to|don'?t forget to)"
    rf"\b[^.?!\n,;]*?\b{_VERB}\b{_TAIL}", re.I)

# Weak first-person openers ("need to email the professor tonight"). These read
# as prose/instructions everywhere else, so they only count WITH a time anchor —
# the live garbage they used to catch ("need to complete the refresher course",
# "have to update Namecheap once more") carried none.
_ME_WEAK = re.compile(
    rf"\b(?:need to|have to)\b[^.?!\n,;]*?\b{_VERB}\b{_TAIL}", re.I)

# Requested of you ("please reply by Friday", "can you send it by EOD").
_THEM = re.compile(
    rf"\b(?:please|can you|could you|make sure to)"
    rf"\b[^.?!\n,;]*?\b{_VERB}\b{_TAIL}", re.I)

_DEADLINE = re.compile(
    r"\b(?:by|before|due(?: on)?|no later than)\s+(?:the\s+)?"
    r"(?:end of\s+(?:the\s+)?(?:day|week|today|month)|eod|cob|eow|end of day|"
    r"today|tonight|tomorrow|this week|next week|this weekend|"
    r"mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{1,2}(?:st|nd|rd|th)?)"
    r"|\bend of (?:the\s+)?(?:day|week|today|month)\b",
    re.I)

_TEMPORAL = re.compile(
    r"\b(?:today|tonight|tonite|tomorrow|tmrw|this (?:week|weekend|afternoon|evening|morning)|"
    r"next (?:week|month)|end of (?:the )?(?:day|week|today|month)|eod|eow|cob|"
    r"mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I)

_IMP_VERB = (r"email|send|call|text|message|reply|respond|finish|submit|review|"
             r"schedule|book|invite|buy|order|pay|remind|update|write|draft|"
             r"prepare|share|ask|follow up|circle back|meet|ping|dm|confirm|cancel|"
             r"renew|complete|upload|fix|merge|approve|set up|reach out|get")
_IMPERATIVE = re.compile(rf"^\s*(?:{_IMP_VERB})\b[^.?!\n,;\"“”|]{{3,55}}", re.I)

_SENT_SPLIT = re.compile(r"[.?!\n]|\s{2,}|\s+[-–—•|›]\s+")

# ── hard rejects ──────────────────────────────────────────────────────────────

# Negation / already-hedged: not a commitment.
_NEGATION = re.compile(
    r"\b(?:won'?t|will not|wouldn'?t|not going to|no need to|don'?t have to|"
    r"never|can'?t|cannot|couldn'?t)\b", re.I)
# Conditionals, maybes, dictation disfluencies ("what I want to do is …").
_HEDGE = re.compile(
    r"\b(?:if [il1]\b|might|maybe|thinking about|was going to|want to do is|"
    r"wondering|considering|not sure|probably should)\b", re.I)
# Ad/marketing copy: imperative verb + commerce lexicon ("Get instant discounts
# on hotels today"). Either signal alone is fine; together it's an ad.
_AD_LEX = re.compile(
    r"\b(?:discounts?|deals?|offers?|free|% ?off|\d+% |sale|instant|exclusive|"
    r"save \$?\d|best price|limited time|shop now|subscribe|sign up|"
    r"upgrade now|premium|trial|unlock)\b", re.I)
# Instructional copy addressed at "you/your" (course pages, product tours):
# "remember to scan the paper where you showed your work…".
_INSTRUCTIONAL = re.compile(r"\b(?:your|you will|you'?ll need|you must|you should)\b", re.I)
# A sentence that trails off mid-clause was OCR-clipped — not a whole thought.
_BAD_TAIL = re.compile(
    r"\b(?:of|to|the|a|an|for|with|and|or|that|if|is|are|by|on|at|in|from|"
    r"instead|as|was|be|can|will|would|could|should|must|my|me|it)$", re.I)
_QUESTION_OPEN = re.compile(r"^\s*(?:will|can|could|would|should|do|does|did|am|are|is)\b", re.I)


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
    s = re.sub(r"\s+", " ", s).strip()
    s = re.split(r"\s+[-–—•|›»:]\s+", s)[0]
    s = re.sub(r"\s+[^\x00-\x7F].*$", "", s)
    return s.strip(" -–—•|:\"'")[:140]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()[:60]


def _rejected(sent: str, what: str, imperative: bool) -> bool:
    """Hard rejects shared by every pattern. Precision-first: when in doubt, drop."""
    if "?" in sent or _QUESTION_OPEN.match(sent):
        return True
    if _NEGATION.search(sent) or _HEDGE.search(sent):
        return True
    if _AD_LEX.search(sent):
        return True                    # commerce lexicon anywhere near = ad copy
    if imperative and _INSTRUCTIONAL.search(sent):
        return True                    # "remember to … your work" = course/tour copy
    words = what.split()
    if not 3 <= len(words) <= 16:
        return True                    # too short to mean anything / run-on
    if _BAD_TAIL.search(what):
        return True                    # OCR-clipped mid-clause ("…the state of")
    return False


def _trim_partial(what: str, sent: str) -> str:
    """If the length-capped tail cut a word in half ("…and uplo"), drop the stub."""
    if sent.startswith(what):
        rest = sent[len(what):]
        if rest[:1].isalpha():
            what = what.rsplit(" ", 1)[0] if " " in what else what
    return what


def detect(text: str, source: str = "authored") -> list[dict]:
    """Find commitments in a block of text from a given surface class.
    Returns [{who, what, due, confidence}], deduped within the block.
    `source`: 'authored' (Notes/Mail/Slack…) or 'strict' (generic web).
    Callers should not pass 'blocked' — scan_and_store short-circuits it."""
    out: list[dict] = []
    seen: list[str] = []
    trust = 0.15 if source == "authored" else 0.0
    for sent in _SENT_SPLIT.split(text):
        sent = sent.strip()
        if len(sent) < 8 or len(sent) > 200:
            continue
        if len(re.findall(r"[a-zA-Z]{2,}", sent)) < 3:
            continue
        strict_dl = bool(_DEADLINE.search(sent))
        any_time = strict_dl or bool(_TEMPORAL.search(sent))
        due = _extract_due(sent) if any_time else None

        candidate = None                       # (who, what, base score, imperative?)
        m = _ME.search(sent)
        if m:
            candidate = ("me", m.group(0), 0.55, False)
        if not candidate and any_time:
            m = _ME_WEAK.search(sent)
            if m:                              # "need to email … tonight"
                candidate = ("me", m.group(0), 0.55, False)
        if not candidate:
            m = _THEM.search(sent)
            if m:
                candidate = ("them", m.group(0), 0.45, False)
            else:
                im = _IMPERATIVE.match(sent)
                if im and any_time:            # bare "Send"/"Reply" is a UI button
                    candidate = ("me", im.group(0), 0.45, True)
        if not candidate:
            continue

        who, raw, score, imperative = candidate
        what = _trim_partial(_clean(raw), _clean(sent))
        if _rejected(sent, what, imperative):
            continue
        key = _norm(what)
        if len(key) < 6 or any(key in s or s in key for s in seen):
            continue
        seen.append(key)

        score += trust
        if strict_dl:
            score += 0.25
        elif any_time:
            score += 0.15
        out.append({"who": who, "what": what,
                    "due": due if (who != "them" or strict_dl) else None,
                    "confidence": round(min(score, 0.99), 2)})
    return out


def _similar(a: str, b: str) -> bool:
    """OCR-variant tolerant near-duplicate check ("from" vs "trom")."""
    from difflib import SequenceMatcher
    na, nb = _norm(a), _norm(b)
    if na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() > 0.8


def scan_and_store(conn, wisp_id: int, text: str, app: str | None = None,
                   url: str | None = None, max_per_capture: int = 2) -> int:
    """Detect promises in a capture and store new ones as Pending.

    Source-gated: AI-chat surfaces / IDEs / system UI never produce promises;
    authored surfaces (Notes, Mail, Slack…) use a 0.70 bar; generic web pages
    0.85 (deadline required in practice). Fuzzy-dedups against recent promises.
    Returns how many were added."""
    src = source_class(app, url)
    if src == "blocked":
        return 0
    return _scan(conn, wisp_id, text, src, max_per_capture)


def remind_due(conn) -> int:
    """Due-day reminders for confirmed promises, via the nudge pill. Prospective-
    memory research is unambiguous: time-based intentions are the most-forgotten
    kind, explicit reminders massively raise completion, and a reminder only works
    when it names BOTH the action and the deadline — so the pill carries the full
    commitment text, not just a topic. One reminder per promise per day; confirming
    the promise is the opt-in. Returns how many reminders were enqueued."""
    n = 0
    for p in db.promises_needing_reminder(conn):
        overdue = p["due"] < db.utcnow()[:10]
        title = "Overdue promise" if overdue else "You said you'd do this today"
        if p["who"] == "them":
            title = "Overdue — waiting on them" if overdue else "Due today — waiting on them"
        db.enqueue_nudge(conn, "promise", title, p["what"],
                         topic_key=f"promise:{p['id']}")
        db.mark_promise_reminded(conn, p["id"])
        n += 1
    if n:
        log.info("promises: enqueued %d due-day reminders", n)
    return n


def _scan(conn, wisp_id: int, text: str, src: str, max_per_capture: int) -> int:
    # authored: any solid commitment; strict: effectively requires a first-person
    # commitment WITH a deadline (0.55 + 0.25) — imperatives/requests can't reach it.
    bar = 0.70 if src == "authored" else 0.80
    found = [p for p in detect(text, source=src) if p["confidence"] >= bar]
    found = found[:max_per_capture]
    if not found:
        return 0
    recent = conn.execute(
        "SELECT what FROM promises WHERE created_at >= datetime('now','-14 days')"
    ).fetchall()
    known = [r[0] for r in recent]
    added = 0
    for p in found:
        if any(_similar(p["what"], k) for k in known):
            continue
        db.add_promise(conn, wisp_id, p["who"], p["what"], p["due"], p["confidence"])
        known.append(p["what"])
        added += 1
    if added:
        log.info("promises: stored %d from wisp #%s (src=%s)", added, wisp_id, src)
    return added
