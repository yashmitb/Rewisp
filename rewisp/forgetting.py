"""The Forgetting Model — Rewisp learns what YOU forget, and rescues it first.

Every failed search is a documented forgetting event: you typed "that pasta
place brooklyn", got nothing useful, rephrased — your brain just lost something
specific, timestamped. Re-asking a question days later is a decay event: the
answer didn't stick. From these, fit a per-category forgetting signature
(C-HLR+: P(recall) = 2^-((t/h)^C), half-life h and complexity C per kind of fact
— names, numbers, links…),
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

# Complexity exponent C in the C-HLR+ curve. C = 1 is plain exponential decay;
# C > 1 bends the curve steeper (a cliff rather than a slope), C < 1 flattens it.
_PRIOR_COMPLEXITY = 1.0
_MIN_C, _MAX_C = 0.6, 2.0
_MIN_OBS_FOR_C = 5           # below this, dispersion is noise, not signal

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
                    "complexity": round(_fit_complexity(obs), 2),
                    "events": counts.get(cat, 0),
                    "observed": len(obs)}
    return out


def _fit_complexity(gaps: list[float]) -> float:
    """Estimate the C-HLR+ complexity exponent from how TIGHTLY re-asks cluster.

    The adaptive-forgetting-curve work (PMC7334729, fitted on 4.28M Duolingo
    observations) found its best variant was p = 2^-((Δt/ĥ)^C): a per-item
    complexity term, because real forgetting is not uniformly exponential. Hard
    items fall off a cliff; easy ones fade gently. Plain HLR (C fixed at 1) was
    measurably worse.

    Fitting C properly needs far more observations than one person's re-asks
    provide, so this uses the shape of the evidence rather than pretending to
    fit: if a category's re-ask gaps cluster tightly around one value, that
    category has a sharp edge — you remember reliably, then suddenly do not, so
    the curve is steep (C > 1). Gaps scattered widely mean a gradual slide
    (C < 1). Below _MIN_OBS_FOR_C observations the dispersion is noise, so it
    stays at 1.0 and the curve reduces exactly to the previous behaviour.
    """
    if len(gaps) < _MIN_OBS_FOR_C:
        return _PRIOR_COMPLEXITY
    mean = sum(gaps) / len(gaps)
    if mean <= 0:
        return _PRIOR_COMPLEXITY
    var = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    cv = math.sqrt(var) / mean          # coefficient of variation
    # cv ~1.0 is what a memoryless exponential produces, so that maps to C = 1.
    # Tighter than that means a sharper edge; broader means a gentler slide.
    c = _PRIOR_COMPLEXITY / max(cv, 0.05)
    return max(_MIN_C, min(_MAX_C, c))


def recall_probability(days_old: float, half_life: float,
                       complexity: float = _PRIOR_COMPLEXITY) -> float:
    """C-HLR+ : p = 2^-((Δt / h)^C).

    `half_life` is days until recall reaches 50%, so p(h) == 0.5 exactly at
    C = 1 — the parameter now means what the UI has always called it.
    """
    t = max(days_old, 0.0)
    h = max(half_life, 0.1)
    c = max(complexity, 0.05)
    try:
        return 2.0 ** (-((t / h) ** c))
    except OverflowError:
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
        # Pass the fitted complexity through: a category with a sharp forgetting
        # edge should be rescued nearer that edge, which is the whole point of
        # fitting C rather than assuming plain exponential decay.
        p = recall_probability(days, s, entry.get("complexity", 1.0))
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


def maybe_pin(conn, question: str, answer: str) -> bool:
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
    conn.execute(
        "INSERT INTO pinned (question, answer, embedding, created_at) VALUES (?, ?, ?, ?)",
        (question.strip(), answer.strip()[:500], qv, db.utcnow()))
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
