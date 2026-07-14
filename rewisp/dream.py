"""Dream Mode — nightly consolidation. Raw wisps pile up (~113/day); a brain
doesn't keep every frame, it consolidates. Cluster a day's wisps into "episodes"
(one per session/topic), summarize each, and index them. Retrieval then reads
clean episodes instead of OCR noise, and old raw wisps can age out while the gist
survives.

Summaries are EXTRACTIVE (salient lines picked locally) — no model call, so this
respects the one-cloud-call-a-day rule and can't run up cost. The daemon can't
call Apple's on-device model anyway.
"""

import json
import logging
import re
from collections import Counter

from . import config, db, delta

log = logging.getLogger("rewisp")

_URL = re.compile(r"https?://[^\s)]+")
_NUM = re.compile(r"[$€£]?\d[\d,]*\.?\d*%?")
_ENTITY = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,2})\b")
_SESSION_GAP_MIN = 20          # a >20-min gap starts a new episode
_MIN_WISPS = 2                 # single-capture blips aren't episodes


def _cluster(rows: list[dict]) -> list[list[dict]]:
    """Group ts-ordered wisps into sessions: a new cluster starts on a big time
    gap or a page_key change."""
    clusters: list[list[dict]] = []
    cur: list[dict] = []
    last_ts = None
    last_key = None
    for r in rows:
        gap_min = 999.0
        if last_ts is not None:
            gap_min = (_ts(r["ts"]) - last_ts) / 60.0
        if cur and (gap_min > _SESSION_GAP_MIN or r["page_key"] != last_key):
            clusters.append(cur)
            cur = []
        cur.append(r)
        last_ts = _ts(r["ts"])
        last_key = r["page_key"]
    if cur:
        clusters.append(cur)
    return [c for c in clusters if len(c) >= _MIN_WISPS]


def _ts(s: str) -> float:
    from datetime import datetime
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


def _salient_lines(texts: list[str], limit: int = 6) -> list[str]:
    """Pick the most informative distinct lines across a cluster's OCR text.
    Score by length + word variety; drop near-duplicates and chrome-ish lines."""
    seen: list[str] = []
    scored: list[tuple[float, str]] = []
    for t in texts:
        for raw in t.splitlines():
            ln = re.sub(r"\s+", " ", raw).strip()
            if len(ln) < 15 or len(ln) > 160:
                continue
            low = ln.lower()
            if low.startswith(("dia file", "file edit", "http")) or "•" in ln[:3]:
                continue
            key = re.sub(r"[^a-z0-9 ]", "", low)[:50]
            if any(key in s or s in key for s in seen):
                continue
            seen.append(key)
            words = re.findall(r"[a-zA-Z]{3,}", ln)
            score = len(set(w.lower() for w in words)) + len(ln) / 60.0
            scored.append((score, ln))
    scored.sort(key=lambda x: -x[0])
    return [ln for _s, ln in scored[:limit]]


def _episode_from_cluster(cluster: list[dict]) -> dict:
    texts = [c["ocr_text"] for c in cluster]
    joined = "\n".join(texts)
    apps = Counter(c["app"] for c in cluster)
    top_app = apps.most_common(1)[0][0]
    lines = _salient_lines(texts)
    links = list(dict.fromkeys(_URL.findall(joined)))[:8]
    numbers = list(dict.fromkeys(_NUM.findall(joined)))[:12]
    entities = [e for e, _ in Counter(_ENTITY.findall(joined)).most_common(8)
                if len(e) > 2 and e.lower() not in ("the", "dia", "file", "edit")]
    title = f"{top_app}: {lines[0][:60]}" if lines else f"{top_app} session"
    return {
        "title": title,
        "summary": "\n".join(lines),
        "entities": entities,
        "links": links,
        "numbers": numbers,
        "wisp_ids": [c["id"] for c in cluster],
        "span_start": cluster[0]["ts"],
        "span_end": cluster[-1]["ts"],
    }


def consolidate_day(conn, date_str: str) -> int:
    """Build episodes for one day (YYYY-MM-DD). Idempotent — clears that day's
    episodes first. Returns how many episodes were written."""
    rows = conn.execute(
        "SELECT id, ts, app, page_key, ocr_text FROM captures "
        "WHERE date(ts) = ? ORDER BY ts ASC", (date_str,)).fetchall()
    if not rows:
        return 0
    wisps = [dict(zip(["id", "ts", "app", "page_key", "ocr_text"], r)) for r in rows]
    conn.execute("DELETE FROM episodes WHERE date = ?", (date_str,))
    n = 0
    from . import embed
    for cluster in _cluster(wisps):
        ep = _episode_from_cluster(cluster)
        emb = embed.embed(ep["title"] + "\n" + ep["summary"])
        conn.execute(
            "INSERT INTO episodes (date, title, summary, entities_json, links_json, "
            "numbers_json, wisp_ids_json, span_start, span_end, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date_str, ep["title"], ep["summary"], json.dumps(ep["entities"]),
             json.dumps(ep["links"]), json.dumps(ep["numbers"]),
             json.dumps(ep["wisp_ids"]), ep["span_start"], ep["span_end"], emb))
        n += 1
    conn.commit()
    if n:
        log.info("dream: consolidated %s into %d episodes", date_str, n)
    return n


def run_pending(conn, older_than_days: int = 14) -> int:
    """Consolidate days that have aged past the raw-retention window and don't
    have episodes yet. Returns total episodes written."""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=older_than_days)).strftime("%Y-%m-%d")
    days = [r[0] for r in conn.execute(
        "SELECT DISTINCT date(ts) d FROM captures WHERE date(ts) < ? "
        "AND d NOT IN (SELECT DISTINCT date FROM episodes) ORDER BY d", (cutoff,))]
    total = 0
    for d in days[:30]:                       # cap per run so a first pass can't stall
        total += consolidate_day(conn, d)
    return total


def search_episodes(conn, query: str, qvec, limit: int = 3) -> list[dict]:
    """Episodes matching a query (FTS + vector), for inclusion in answer context."""
    out: dict[int, dict] = {}
    try:
        for rid, title, summary, span in conn.execute(
            "SELECT e.id, e.title, e.summary, e.span_start FROM episodes_fts f "
            "JOIN episodes e ON e.id = f.rowid WHERE episodes_fts MATCH ? "
            "ORDER BY rank LIMIT ?", (query, limit)):
            out[rid] = {"id": rid, "title": title, "summary": summary, "span": span}
    except Exception:  # noqa: BLE001 — bad FTS query chars
        pass
    if qvec is not None:
        import numpy as np
        rows = conn.execute(
            "SELECT id, title, summary, span_start, embedding FROM episodes "
            "WHERE embedding IS NOT NULL").fetchall()
        if rows:
            mat = np.vstack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
            q = np.asarray(qvec, dtype=np.float32)
            q = q / (np.linalg.norm(q) + 1e-9)
            sims = mat @ q
            for i in np.argsort(-sims)[:limit]:
                r = rows[int(i)]
                out.setdefault(r[0], {"id": r[0], "title": r[1], "summary": r[2], "span": r[3]})
    return list(out.values())[:limit]
