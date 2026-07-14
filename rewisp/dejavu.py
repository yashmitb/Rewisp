"""Déjà Vu — proactive recall. When the screen you're on relates to something
you saw before, quietly surface it.

Detection is fully local: reuse the embedding already computed for the capture,
vector-search history, and fire only when a strict set of gates all hold. The
one-line body is templated (no model, no cloud call — nudges must be free).
"""

import logging
from datetime import datetime, timedelta, timezone

from . import config, db

log = logging.getLogger("rewisp")


def _humanize(ts: str) -> str:
    """'2026-07-03 18:20:00' -> 'on Jul 3' / 'yesterday' / 'earlier today'."""
    try:
        then = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return "earlier"
    days = (datetime.now(timezone.utc).date() - then.date()).days
    if days <= 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return then.strftime("on %A")           # "on Thursday"
    return then.strftime("on %b %-d")            # "on Jul 3"


def find_recall(conn, wisp_id: int, qvec, app: str, page_key: str,
                threshold: float | None = None) -> dict | None:
    """Return a nudge dict for the best past match, or None. Gates:
       - cosine > threshold
       - matched wisp older than 24 h
       - a different context (not the same app AND same page)
    Vector search already restricts to older wisps via `until`."""
    if qvec is None:
        return None
    thr = threshold if threshold is not None else config.load_settings().get(
        "nudge_similarity", 0.82)
    day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    hits = db.vector_search(conn, qvec, k=10, until=day_ago)
    for hid, score in hits:
        if score < thr:
            break                                # sorted desc — nothing better ahead
        row = conn.execute(
            "SELECT app, page_key, ts, substr(ocr_text,1,160) FROM captures WHERE id=?",
            (hid,)).fetchone()
        if not row:
            continue
        m_app, m_key, m_ts, snippet = row
        if m_app == app and m_key == page_key:
            continue                             # same context, not a recall
        snippet = " ".join((snippet or "").split())[:120]
        try:
            db.bump_recall(conn, [hid])   # a surfaced memory counts as recalled
        except Exception:  # noqa: BLE001
            pass
        return {
            "type": "dejavu",
            "title": "You've seen something like this",
            "body": f"You saw this {_humanize(m_ts)} in {m_app}: “{snippet}”",
            "source_wisp_id": hid,
            "topic_key": m_key or f"wisp:{hid}",
            "score": round(float(score), 3),
        }
    return None


def maybe_nudge(conn, wisp_id: int, qvec, app: str, page_key: str) -> int | None:
    """Called from the daemon after a capture. Applies the enabled flag + rate
    limits, then enqueues a Déjà Vu nudge. Returns the nudge id or None."""
    s = config.load_settings()
    if not s.get("nudges_enabled", False):
        return None
    if db.nudge_count_today(conn) >= s.get("nudge_max_per_day", 3):
        return None
    match = find_recall(conn, wisp_id, qvec, app, page_key)
    if not match:
        return None
    if db.nudge_topic_recent(conn, match["topic_key"]):
        return None                              # cooled down on this topic
    nid = db.enqueue_nudge(conn, match["type"], match["title"], match["body"],
                           source_wisp_id=match["source_wisp_id"], topic_key=match["topic_key"])
    log.info("dejavu nudge #%d (score=%.3f) -> wisp #%s", nid, match["score"],
             match["source_wisp_id"])
    return nid
