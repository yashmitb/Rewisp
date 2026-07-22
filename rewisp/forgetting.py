"""The Forgetting Model — Rewisp learns what YOU forget, and rescues it first.

Every failed search is a documented forgetting event: you typed "that pasta
place brooklyn", got nothing useful, rephrased — your brain just lost something
specific, timestamped. Re-asking a question days later is a decay event: the
answer didn't stick. From these, fit a per-category forgetting signature
(FSRS-6 power-law curve: R(t) = (1 + F·t/h)^decay, with half-life h and a decay
exponent per kind of fact — names, numbers, links…),
then:

  • "About to fade" — wisps predicted to cross YOUR forgetting cliff get one
    rescue mention (digest line / Today card) at the optimal moment, the same
    review-right-before-you-forget trick that makes spaced repetition work —
    applied passively to life instead of flashcards.
  • Auto-pin — the 3rd time you look up the same fact, it's pinned: answered
    instantly and deterministically forever, like a Vault fact.

Spaced-repetition science (SuperMemo/Anki) fits personal forgetting curves for
flashcards; nothing has ever fit one over ambient life memory, because nothing
else holds both everything-you-saw AND evidence-of-what-you-failed-to-recall.
Fully local: numpy + SQL, no model, no cloud.
"""

import json
import logging
import math
import re
from datetime import datetime, timezone

from . import config, db

log = logging.getLogger("rewisp")

# Population priors for HALF-LIFE h (days until recall drops to 50%), per bin.
# Diary-study ordering: names go first, numbers fast, places stick longer.
#
# These were previously the time-constant S of an exponential e^(-t/S), whose
# half-life is S·ln2. Converting (x0.693) keeps every curve exactly where it was
# while making the number mean the thing the UI already labels it: "half-gone in
# N days". The parameter is now directly interpretable instead of needing a
# conversion at every read site.
PRIORS = {"name": 4.2, "number": 2.1, "link": 1.4, "date": 2.8,
          "place": 4.9, "other": 4.9}
_PRIOR_WEIGHT = 3.0          # pseudo-observations the prior counts for

# FSRS-6 decay exponent. FSRS models retention as a POWER law, not an exponential:
# a category's curve is R(t) = (1 + FACTOR·t/h)^decay. The canonical FSRS-6 value
# is -0.5. A category whose re-asks cluster tightly has a sharper forgetting edge
# (steeper, more-negative decay); scattered re-asks mean a gentler slide. Range
# kept modest so no category degenerates.
DEFAULT_DECAY = -0.5
_MIN_DECAY, _MAX_DECAY = -0.8, -0.2      # steepest .. gentlest
_MIN_OBS_FOR_DECAY = 5                    # below this, dispersion is noise, not signal

_NUMBERY = re.compile(r"\d|how (much|many)|price|cost|amount|balance|number|total|phone|percent", re.I)
_LINKY = re.compile(r"\b(link|url|site|website|repo|video|article|page|doc)\b", re.I)
_DATEY = re.compile(r"\b(when|date|deadline|due|schedule|meeting)\b", re.I)
_PLACEY = re.compile(r"\b(where|place|restaurant|cafe|address|location|room|building)\b", re.I)
_NAMEY = re.compile(r"\b(who|name|person|guy|girl|professor|recruiter|advisor|doctor|contact)\b", re.I)


def categorize(text: str) -> str:
    """Coarse bin for what kind of fact a question is chasing."""
    t = text.lower()
    if _NAMEY.search(t):
        return "name"
    if _DATEY.search(t):
        return "date"
    if _PLACEY.search(t):
        return "place"
    if _LINKY.search(t):
        return "link"
    if _NUMBERY.search(t):
        return "number"
    return "other"


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _sim(a, b) -> float:
    import numpy as np
    va = np.frombuffer(a, dtype=np.float32)
    vb = np.frombuffer(b, dtype=np.float32)
    return float(va @ vb)


def forgetting_events(conn) -> list[dict]:
    """Mine the query log for documented forgetting.

    rephrase  — a semantically-near query within 3 minutes of the last one:
                the first wording failed, you tried again.
    re-ask    — a semantically-near query ≥ 20 hours later: the answer didn't
                stick, your brain dropped it. Carries the decay gap in days.
    """
    rows = conn.execute(
        "SELECT id, text, ts, embedding FROM queries WHERE embedding IS NOT NULL "
        "ORDER BY id ASC").fetchall()
    events: list[dict] = []
    for i, (qid, text, ts, emb) in enumerate(rows):
        t_i = _parse_ts(ts)
        for pid, ptext, pts, pemb in rows[:i]:
            if _sim(emb, pemb) < 0.60:
                continue
            gap_min = (t_i - _parse_ts(pts)).total_seconds() / 60.0
            if gap_min < 0.25:
                continue                          # same moment / double-submit
            if gap_min <= 3.0:                    # tried again within 3 minutes
                events.append({"kind": "rephrase", "text": text, "ts": ts,
                               "category": categorize(text), "gap_days": 0.0})
                break
            if gap_min >= 20 * 60:                # 20+ hours later = decay re-ask
                events.append({"kind": "re-ask", "text": text, "ts": ts,
                               "category": categorize(text),
                               "gap_days": round(gap_min / (24 * 60), 2)})
                break
    return events


def signature(conn) -> dict:
    """Fit per-category stability S (days) from re-ask gaps, blended with the
    population prior. A re-ask after g days ≈ evidence that S ≲ g (memory failed
    by then), so we estimate S as a weighted mean of observed gaps and the prior."""
    events = forgetting_events(conn)
    gaps: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for e in events:
        counts[e["category"]] = counts.get(e["category"], 0) + 1
        if e["kind"] == "re-ask" and e["gap_days"] > 0:
            gaps.setdefault(e["category"], []).append(e["gap_days"])
    out = {}
    for cat, prior in PRIORS.items():
        obs = gaps.get(cat, [])
        s = (prior * _PRIOR_WEIGHT + sum(obs)) / (_PRIOR_WEIGHT + len(obs))
        out[cat] = {"stability_days": round(s, 1),
                    "decay": round(_fit_decay(obs), 2),
                    "events": counts.get(cat, 0),
                    "observed": len(obs)}
    return out


def _fit_decay(gaps: list[float]) -> float:
    """Estimate the FSRS-6 decay exponent from how TIGHTLY re-asks cluster.

    FSRS-6 (open-spaced-repetition, validated on ~1.7B reviews) makes the curve's
    decay a free parameter rather than fixing the exponential shape SM-2 assumed,
    because real forgetting is a heavy-tailed power law and its steepness differs
    by material. We can't fit it the FSRS way (that needs graded reviews we don't
    have), so we read the shape of the evidence: re-ask gaps that cluster tightly
    around one value mean a sharp edge — reliable recall, then a sudden drop —
    which is a steeper (more-negative) decay; gaps scattered widely mean a gentle
    slide. Below _MIN_OBS_FOR_DECAY observations the dispersion is noise, so it
    stays at the canonical -0.5.
    """
    if len(gaps) < _MIN_OBS_FOR_DECAY:
        return DEFAULT_DECAY
    mean = sum(gaps) / len(gaps)
    if mean <= 0:
        return DEFAULT_DECAY
    var = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    cv = math.sqrt(var) / mean          # coefficient of variation
    # cv ~1.0 is what a memoryless process produces -> canonical -0.5. Tighter
    # than that means a sharper edge (steeper); broader means a gentler slide.
    d = DEFAULT_DECAY / max(cv, 0.05)
    return max(_MIN_DECAY, min(_MAX_DECAY, d))


def recall_probability(days_old: float, half_life: float,
                       decay: float = DEFAULT_DECAY) -> float:
    """FSRS-6 power-law recall curve: R(t) = (1 + FACTOR · t/h) ^ decay.

    FACTOR is set so R(half_life) == 0.5 for ANY decay, so `half_life` keeps its
    meaning — days until recall reaches 50% — and every prior, label and rescue
    threshold expressed in half-life terms stays valid. The power tail is the
    point: at long delays it predicts more retained memory than an exponential,
    which is what the FSRS data shows and what makes the rescue window realistic.
    """
    t = max(days_old, 0.0)
    h = max(half_life, 0.1)
    d = min(max(decay, _MIN_DECAY), _MAX_DECAY)
    factor = 0.5 ** (1.0 / d) - 1.0     # => (1 + factor)^d == 0.5 at t == h
    try:
        return (1.0 + factor * (t / h)) ** d
    except (OverflowError, ValueError):
        return 0.0


def about_to_fade(conn, limit: int = 2) -> list[dict]:
    """Wisps predicted to be crossing YOUR forgetting cliff: 3–14 days old,
    never revisited or recalled, salient, and in a category you demonstrably
    lose. One rescue mention each — never repeated (rescued flag)."""
    sig = signature(conn)
    rows = conn.execute(
        "SELECT id, ts, app, page_key, substr(ocr_text,1,2500), recall_count "
        "FROM captures WHERE ts BETWEEN datetime('now','-14 days') AND datetime('now','-3 days') "
        "AND COALESCE(recall_count,0) = 0 AND COALESCE(rescued,0) = 0 "
        "ORDER BY id DESC LIMIT 400").fetchall()
    now = datetime.now(timezone.utc)
    from .promises import _BLOCKED_APPS
    scored = []
    for rid, ts, app, pkey, text, _rc in rows:
        # IDE/terminal/AI surfaces aren't personal facts you forget — their
        # status bars are full of number-shaped junk that gamed the ranking.
        if (app or "").strip().lower() in _BLOCKED_APPS:
            continue
        # The most content-rich LINE of the wisp, not the head — OCR reads the
        # menu bar first, so the head is toolbar chrome ("History … Help 29%").
        from . import dream
        lines = dream._salient_lines([text or ""], limit=1)
        snippet = lines[0][:160] if lines else ""
        if len(snippet) < 30:
            continue
        # Only rescue wisps that resemble the kinds of facts you lose: they
        # carry a number/name/link/date payload worth keeping.
        cat = categorize(snippet)
        if cat == "other":
            continue
        # single-visit pages only — things you saw once and moved on
        n_key = conn.execute("SELECT COUNT(*) FROM captures WHERE page_key=?",
                             (pkey,)).fetchone()[0] if pkey else 1
        if n_key > 3:
            continue
        days = (now - _parse_ts(ts)).total_seconds() / 86400.0
        entry = sig.get(cat, sig["other"])
        s = entry["stability_days"]
        # Pass the fitted decay through: a category with a sharp forgetting edge
        # should be rescued nearer that edge, which is the point of fitting the
        # FSRS decay per category rather than assuming one shape for all.
        p = recall_probability(days, s, entry.get("decay", DEFAULT_DECAY))
        # sweet spot: past the cliff's edge but not long gone
        if not 0.15 <= p <= 0.55:
            continue
        scored.append({"wisp_id": rid, "ts": ts, "app": app, "category": cat,
                       "snippet": snippet, "p_recall": round(p, 2)})
    scored.sort(key=lambda x: x["p_recall"])          # most-faded first
    return scored[:limit]


def mark_rescued(conn, wisp_ids: list[int]) -> None:
    if wisp_ids:
        marks = ",".join("?" * len(wisp_ids))
        conn.execute(f"UPDATE captures SET rescued=1 WHERE id IN ({marks})", wisp_ids)
        conn.commit()


# ── auto-pin: the 3rd lookup of the same fact makes it permanent ─────────────

# Questions whose answers are time-dependent can never be pinned — "what did I
# do yesterday" has a different correct answer every day. Only stable facts
# (wifi passwords, codes, links, names) qualify.
_UNPINNABLE = re.compile(
    r"\b(today|yesterday|tonight|this (week|morning|afternoon|evening)|last (week|night)|"
    r"now|currently|recently|what did i|what was i|what have i|summarize|recap|"
    r"what changed|how has|what happened)\b", re.I)


def maybe_pin(conn, question: str, answer: str,
              wisp_ids: list[int] | None = None) -> bool:
    """Called after every answered question. If this is the ~3rd time the same
    STABLE fact has been asked, pin the answer for instant deterministic recall."""
    if not answer or "not found" in answer.lower():
        return False
    if _UNPINNABLE.search(question):
        return False
    qv = None
    try:
        from . import embed
        qv = embed.embed(question)
    except Exception:  # noqa: BLE001
        return False
    if qv is None:
        return False
    rows = conn.execute(
        "SELECT embedding FROM queries WHERE embedding IS NOT NULL "
        "ORDER BY id DESC LIMIT 300").fetchall()
    similar = sum(1 for (e,) in rows if _sim(qv, e) >= 0.75)
    if similar < 3:                                   # includes today's ask
        return False
    if pinned_answer(conn, question):
        return False                                  # already pinned
    # Record which wisps produced this answer. A pinned fact is kept forever by
    # design, so without provenance "forget the last 10 minutes" would leave a
    # permanent, deterministic copy of whatever it said — the exact thing the
    # forget button exists to prevent.
    import json as _json
    sources = _json.dumps(sorted(set(wisp_ids))) if wisp_ids else None
    conn.execute(
        "INSERT INTO pinned (question, answer, embedding, created_at, source_wisp_ids) "
        "VALUES (?, ?, ?, ?, ?)",
        (question.strip(), answer.strip()[:500], qv, db.utcnow(), sources))
    conn.commit()
    log.info("forgetting: auto-pinned %r (asked %d times)", question[:50], similar)
    return True


def pinned_answer(conn, question: str) -> dict | None:
    """Deterministic hit for a previously-pinned fact."""
    if _UNPINNABLE.search(question):
        return None                     # time-dependent asks always re-answer live
    try:
        from . import embed
        qv = embed.embed(question)
    except Exception:  # noqa: BLE001
        return None
    if qv is None:
        return None
    best = None
    for pid, q, a, e in conn.execute("SELECT id, question, answer, embedding FROM pinned"):
        s = _sim(qv, e)
        if s >= 0.80 and (best is None or s > best[0]):
            best = (s, q, a)
    if not best:
        return None
    return {"answer": best[2], "source": f"Pinned · you kept asking “{best[1][:40]}”",
            "copy_text": best[2], "model": "Pinned"}
