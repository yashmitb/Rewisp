"""SQLite store: captures + FTS5, summaries, chats, entities. WAL mode, UTC timestamps."""

import logging
import sqlite3
from datetime import datetime, timezone

from . import config

log = logging.getLogger("rewisp")

SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
  id INTEGER PRIMARY KEY,
  ts DATETIME NOT NULL,
  app TEXT NOT NULL,
  window_title TEXT,
  url TEXT,
  ocr_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_captures_ts ON captures(ts);

CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
  ocr_text, window_title, url, content=captures, content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS captures_ai AFTER INSERT ON captures BEGIN
  INSERT INTO captures_fts(rowid, ocr_text, window_title, url)
  VALUES (new.id, new.ocr_text, new.window_title, new.url);
END;
CREATE TRIGGER IF NOT EXISTS captures_ad AFTER DELETE ON captures BEGIN
  INSERT INTO captures_fts(captures_fts, rowid, ocr_text, window_title, url)
  VALUES ('delete', old.id, old.ocr_text, old.window_title, old.url);
END;

CREATE TABLE IF NOT EXISTS summaries (
  id INTEGER PRIMARY KEY,
  date DATE UNIQUE,
  summary_md TEXT,
  threads_md TEXT,
  time_report_json TEXT
);

CREATE TABLE IF NOT EXISTS chats (
  id INTEGER PRIMARY KEY,
  ts DATETIME,
  role TEXT,
  content TEXT
);

CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY,
  name TEXT, kind TEXT, first_seen DATETIME, last_seen DATETIME, notes TEXT
);

CREATE TABLE IF NOT EXISTS nudges (
  id INTEGER PRIMARY KEY,
  type TEXT,                 -- 'dejavu' | 'delta' | 'promise'
  title TEXT,
  body TEXT,
  source_wisp_id INTEGER,    -- the past wisp this points back to
  topic_key TEXT,            -- page_key/thread, for per-topic cooldown
  created_at TEXT,
  status TEXT DEFAULT 'pending',   -- 'pending' | 'delivered' | 'dismissed'
  feedback TEXT              -- 'up' | 'down' | NULL
);
CREATE INDEX IF NOT EXISTS idx_nudges_status ON nudges(status, created_at);

CREATE TABLE IF NOT EXISTS promises (
  id INTEGER PRIMARY KEY,
  wisp_id INTEGER,           -- source capture
  who TEXT,                  -- 'me' (you owe) | 'them' (waiting on them)
  what TEXT,
  due TEXT,                  -- ISO date, nullable
  status TEXT DEFAULT 'pending',   -- 'pending' | 'confirmed' | 'done' | 'dismissed'
  confidence REAL,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_promises_status ON promises(status, due);

CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY,
  date TEXT,                 -- day consolidated
  title TEXT,
  summary TEXT,
  entities_json TEXT,
  links_json TEXT,
  numbers_json TEXT,
  wisp_ids_json TEXT,
  span_start TEXT,
  span_end TEXT,
  embedding BLOB
);
CREATE INDEX IF NOT EXISTS idx_episodes_date ON episodes(date);
CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
  title, summary, content=episodes, content_rowid=id
);
CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
  INSERT INTO episodes_fts(rowid, title, summary) VALUES (new.id, new.title, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
  INSERT INTO episodes_fts(episodes_fts, rowid, title, summary)
  VALUES ('delete', old.id, old.title, old.summary);
END;

CREATE TABLE IF NOT EXISTS series (
  id INTEGER PRIMARY KEY,
  key TEXT,             -- page_key + normalized label
  label TEXT,
  value REAL,
  unit TEXT,            -- '$', '%', 'kg', ''
  ts TEXT,
  wisp_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_series_key ON series(key, ts);

CREATE TABLE IF NOT EXISTS queries (
  id INTEGER PRIMARY KEY,
  text TEXT,
  ts TEXT,
  app_context TEXT,
  was_tapped INTEGER DEFAULT 0,
  embedding BLOB
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent column adds. SQLite has no ADD COLUMN IF NOT EXISTS, so probe."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(captures)")}
    if "embedding" not in cols:
        # 512-dim float32 semantic vector for meaning-based retrieval (nullable;
        # backfilled for old rows). Lives on the row, so DELETE removes it too.
        conn.execute("ALTER TABLE captures ADD COLUMN embedding BLOB")
        conn.commit()
    if "page_key" not in cols:
        # Stable page identity for Delta ("what changed") and Numbers Over Time.
        conn.execute("ALTER TABLE captures ADD COLUMN page_key TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_pagekey ON captures(page_key, ts)")
        conn.commit()
    if "recall_count" not in cols:
        # Reinforcement: every time a wisp is recalled it strengthens — ranks
        # higher and survives consolidation/retention longer.
        conn.execute("ALTER TABLE captures ADD COLUMN recall_count INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE captures ADD COLUMN last_recalled TEXT")
        conn.commit()


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def insert_capture(conn: sqlite3.Connection, app: str, window_title: str | None,
                   url: str | None, ocr_text: str, embedding: bytes | None = None) -> int:
    ocr_text = ocr_text[: config.MAX_OCR_CHARS]
    from . import delta
    pkey = delta.page_key(app, window_title, url)
    cur = conn.execute(
        "INSERT INTO captures (ts, app, window_title, url, ocr_text, embedding, page_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (utcnow(), app, window_title, url, ocr_text, embedding, pkey),
    )
    conn.commit()
    return cur.lastrowid


def search_captures(conn: sqlite3.Connection, query: str, limit: int = 20,
                    since: str | None = None, until: str | None = None) -> list[dict]:
    sql = """
      SELECT c.id, c.ts, c.app, c.window_title, c.url,
             snippet(captures_fts, 0, '[', ']', ' … ', 48) AS snip
      FROM captures_fts JOIN captures c ON c.id = captures_fts.rowid
      WHERE captures_fts MATCH ?
    """
    params: list = [query]
    if since:
        sql += " AND c.ts >= ?"
        params.append(since)
    if until:
        sql += " AND c.ts <= ?"
        params.append(until)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    cols = ["id", "ts", "app", "window_title", "url", "snippet"]
    return [dict(zip(cols, row)) for row in conn.execute(sql, params)]


def vector_search(conn: sqlite3.Connection, qvec, k: int = 40,
                  since: str | None = None, until: str | None = None) -> list[tuple[int, float]]:
    """Brute-force cosine over stored embeddings. At 6-month retention the corpus
    is ~20k rows x 512 float32 (~40 MB) — a single numpy matmul, a few ms. No
    vector-index extension needed at this scale. Returns [(id, score)] desc."""
    import numpy as np
    sql = "SELECT id, embedding FROM captures WHERE embedding IS NOT NULL"
    params: list = []
    if since:
        sql += " AND ts >= ?"; params.append(since)
    if until:
        sql += " AND ts <= ?"; params.append(until)
    ids: list[int] = []
    vecs: list = []
    for rid, blob in conn.execute(sql, params):
        ids.append(rid)
        vecs.append(np.frombuffer(blob, dtype=np.float32))
    if not ids:
        return []
    mat = np.vstack(vecs)                      # (n, dim), already normalized
    q = np.asarray(qvec, dtype=np.float32)
    q = q / (np.linalg.norm(q) + 1e-9)
    sims = mat @ q                             # cosine, since both are unit-norm
    k = min(k, len(ids))
    top = np.argpartition(-sims, k - 1)[:k]
    top = top[np.argsort(-sims[top])]
    return [(ids[i], float(sims[i])) for i in top]


def reinforcement_rank(conn: sqlite3.Connection, ids: list[int]) -> list[int]:
    """Order the given wisp ids by reinforcement weight w = recall_count *
    exp(-days_since_last_recall / 90). Returns ids sorted strongest-first; used as
    a third RRF signal so frequently-recalled memories surface higher."""
    if not ids:
        return []
    import math
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, recall_count, "
        f"CAST(julianday('now') - julianday(COALESCE(last_recalled, created_at_fallback)) AS REAL) "
        f"FROM (SELECT id, COALESCE(recall_count,0) recall_count, last_recalled, ts AS created_at_fallback "
        f"      FROM captures WHERE id IN ({marks}))", ids).fetchall()
    weighted = []
    for rid, rc, days in rows:
        w = (rc or 0) * math.exp(-(days or 0) / 90.0)
        weighted.append((rid, w))
    weighted.sort(key=lambda x: -x[1])
    return [rid for rid, w in weighted if w > 0]


def bump_recall(conn: sqlite3.Connection, ids: list[int]) -> None:
    """Record that these wisps were recalled (search hit, Déjà Vu match, delta
    view). Strengthens them for ranking + retention."""
    if not ids:
        return
    marks = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE captures SET recall_count = COALESCE(recall_count,0) + 1, last_recalled = ? "
        f"WHERE id IN ({marks})", [utcnow()] + ids)
    conn.commit()


def search_captures_hybrid(conn: sqlite3.Connection, query: str, qvec,
                           limit: int = 20, since: str | None = None,
                           until: str | None = None) -> list[dict]:
    """FTS keyword search fused with semantic vector search (and reinforcement)
    via Reciprocal Rank Fusion. Falls back to FTS-only when no query vector is
    available (embedder offline). Row shape matches search_captures()."""
    fts_rows = search_captures(conn, query, limit=config.RRF_POOL, since=since, until=until)
    if qvec is None:
        return fts_rows[:limit]
    vec_hits = vector_search(conn, qvec, k=config.RRF_POOL, since=since, until=until)

    kk = config.RRF_K
    fused: dict[int, float] = {}
    for rank, r in enumerate(fts_rows):
        fused[r["id"]] = fused.get(r["id"], 0.0) + 1.0 / (kk + rank)
    for rank, (rid, _score) in enumerate(vec_hits):
        fused[rid] = fused.get(rid, 0.0) + 1.0 / (kk + rank)
    # Third signal: reinforcement weight, over the candidates we already have.
    for rank, rid in enumerate(reinforcement_rank(conn, list(fused))):
        fused[rid] = fused.get(rid, 0.0) + 1.0 / (kk + rank)

    order = sorted(fused, key=lambda i: -fused[i])[:limit]
    by_id = {r["id"]: r for r in fts_rows}
    vec_only = [i for i in order if i not in by_id]
    if vec_only:
        # Vector-only hits have no FTS snippet — pull a plain head of their text.
        q = f"SELECT id, ts, app, window_title, url, substr(ocr_text,1,300) FROM captures WHERE id IN ({','.join('?' * len(vec_only))})"
        cols = ["id", "ts", "app", "window_title", "url", "snippet"]
        for row in conn.execute(q, vec_only):
            d = dict(zip(cols, row))
            d["vector_match"] = True   # UI can badge "≈ meaning match"
            by_id[d["id"]] = d
    return [by_id[i] for i in order if i in by_id]


def embeddings_backfill(conn: sqlite3.Connection, batch: int = 500) -> int:
    """Embed captures that don't have a vector yet (old rows, or rows stored while
    the embedder was offline). Chunked; returns how many were embedded this call."""
    from . import embed
    if not embed.available():
        return 0
    rows = conn.execute(
        "SELECT id, ocr_text FROM captures WHERE embedding IS NULL "
        "ORDER BY id DESC LIMIT ?", (batch,)).fetchall()
    done = 0
    for rid, text in rows:
        b = embed.embed(text)
        if b is not None:
            conn.execute("UPDATE captures SET embedding=? WHERE id=?", (b, rid))
            done += 1
    if done:
        conn.commit()
    return done


def missing_embeddings(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM captures WHERE embedding IS NULL").fetchone()[0]


def pagekey_backfill(conn: sqlite3.Connection, batch: int = 2000) -> int:
    """Compute page_key for old rows that predate the column. Cheap (string ops),
    so a large batch per pass is fine."""
    from . import delta
    rows = conn.execute(
        "SELECT id, app, window_title, url FROM captures WHERE page_key IS NULL "
        "ORDER BY id DESC LIMIT ?", (batch,)).fetchall()
    for rid, app, title, url in rows:
        conn.execute("UPDATE captures SET page_key=? WHERE id=?",
                     (delta.page_key(app, title, url), rid))
    if rows:
        conn.commit()
    return len(rows)


def latest_page_key(conn: sqlite3.Connection) -> str | None:
    """page_key of the most recent capture — i.e. the page the user is on now
    (Rewisp never captures its own UI, so this is the app behind the panel)."""
    row = conn.execute(
        "SELECT page_key FROM captures WHERE page_key IS NOT NULL "
        "ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row else None


def versions_for_key(conn: sqlite3.Connection, key: str, before: str | None = None,
                     after: str | None = None) -> tuple[dict | None, dict | None]:
    """The two versions of a page to diff. Default: latest vs the one just before
    it. With `before` (a parsed 'since Tuesday'): latest vs the last capture at or
    before that time. Returns (old, new) dicts or (None, None)."""
    def _row(sql, params):
        r = conn.execute(sql, params).fetchone()
        if not r:
            return None
        return dict(zip(["id", "ts", "app", "window_title", "url", "ocr_text"], r))

    base = ("SELECT id, ts, app, window_title, url, ocr_text FROM captures "
            "WHERE page_key = ?")
    new = _row(base + (" AND ts <= ?" if after else "") + " ORDER BY ts DESC LIMIT 1",
               [key] + ([after] if after else []))
    if not new:
        return None, None
    if before:
        old = _row(base + " AND ts <= ? ORDER BY ts DESC LIMIT 1", [key, before])
    else:
        # "since I last looked" = a meaningfully earlier visit, not the frame from
        # 1s ago. Prefer the newest version at least 5 min older; fall back to the
        # immediately previous capture if that's all there is.
        old = _row(base + " AND ts <= datetime(?, '-5 minutes') ORDER BY ts DESC LIMIT 1",
                   [key, new["ts"]])
        if not old:
            old = _row(base + " AND id < ? ORDER BY ts DESC LIMIT 1", [key, new["id"]])
    return old, new


def delete_captures(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Single choke point for removing captures — 'forget', kill-list purge, and
    retention all route here. The AFTER DELETE trigger cleans captures_fts and the
    embedding lives on the row, so both go with it. As derived tables land
    (deltas, promises, series, episodes) their cascade deletes attach HERE, so no
    forgotten wisp ever leaks into a downstream table."""
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM promises WHERE wisp_id IN ({marks})", ids)
    # Episodes are summaries built from wisps — if a forgotten wisp fed one, drop
    # the whole episode so no trace of the forgotten content survives in a summary.
    idset = set(ids)
    try:
        import json as _json
        gone = [eid for eid, wj in conn.execute("SELECT id, wisp_ids_json FROM episodes")
                if wj and idset & set(_json.loads(wj))]
        if gone:
            conn.execute(f"DELETE FROM episodes WHERE id IN ({','.join('?' * len(gone))})", gone)
    except Exception:  # noqa: BLE001
        pass
    conn.execute(f"DELETE FROM series WHERE wisp_id IN ({marks})", ids)
    n = conn.execute(f"DELETE FROM captures WHERE id IN ({marks})", ids).rowcount
    conn.commit()
    return n


# -- nudges (proactive recall / delta / promise pills) -----------------------

def nudge_count_today(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM nudges WHERE created_at >= datetime('now','-1 day')"
    ).fetchone()[0]


def nudge_topic_recent(conn: sqlite3.Connection, topic_key: str, hours: int = 48) -> bool:
    """True if we already nudged about this topic within the cooldown — the main
    anti-annoyance guard (don't re-surface the same memory over and over)."""
    if not topic_key:
        return False
    row = conn.execute(
        f"SELECT 1 FROM nudges WHERE topic_key = ? AND created_at >= datetime('now','-{hours} hours') LIMIT 1",
        (topic_key,)).fetchone()
    return row is not None


def enqueue_nudge(conn: sqlite3.Connection, type: str, title: str, body: str,
                  source_wisp_id: int | None = None, topic_key: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO nudges (type, title, body, source_wisp_id, topic_key, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
        (type, title, body, source_wisp_id, topic_key, utcnow()))
    conn.commit()
    return cur.lastrowid


def pending_nudges(conn: sqlite3.Connection) -> list[dict]:
    cols = ["id", "type", "title", "body", "source_wisp_id", "created_at"]
    rows = conn.execute(
        "SELECT id, type, title, body, source_wisp_id, created_at FROM nudges "
        "WHERE status = 'pending' ORDER BY id ASC").fetchall()
    return [dict(zip(cols, r)) for r in rows]


def mark_nudge_delivered(conn: sqlite3.Connection, nudge_id: int) -> None:
    conn.execute("UPDATE nudges SET status='delivered' WHERE id=?", (nudge_id,))
    conn.commit()


def nudge_feedback(conn: sqlite3.Connection, nudge_id: int, vote: str) -> None:
    """Store 👍/👎 and dismiss. Feedback tunes the similarity threshold nightly."""
    status = "dismissed"
    conn.execute("UPDATE nudges SET feedback=?, status=? WHERE id=?",
                 (vote if vote in ("up", "down") else None, status, nudge_id))
    conn.commit()


# -- promises -----------------------------------------------------------------

def add_promise(conn: sqlite3.Connection, wisp_id: int, who: str, what: str,
                due: str | None, confidence: float) -> int:
    cur = conn.execute(
        "INSERT INTO promises (wisp_id, who, what, due, status, confidence, created_at) "
        "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
        (wisp_id, who, what, due, confidence, utcnow()))
    conn.commit()
    return cur.lastrowid


def promises_by_status(conn: sqlite3.Connection, statuses: tuple[str, ...]) -> list[dict]:
    marks = ",".join("?" * len(statuses))
    cols = ["id", "who", "what", "due", "status", "confidence", "created_at"]
    rows = conn.execute(
        f"SELECT id, who, what, due, status, confidence, created_at FROM promises "
        f"WHERE status IN ({marks}) ORDER BY (due IS NULL), due ASC, id DESC", statuses).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def set_promise_status(conn: sqlite3.Connection, promise_id: int, status: str) -> None:
    conn.execute("UPDATE promises SET status=? WHERE id=?", (status, promise_id))
    conn.commit()


def due_promises(conn: sqlite3.Connection) -> list[dict]:
    """Confirmed promises due today or overdue — drives the due-day nudge."""
    cols = ["id", "who", "what", "due"]
    rows = conn.execute(
        "SELECT id, who, what, due FROM promises WHERE status='confirmed' "
        "AND due IS NOT NULL AND due <= date('now')").fetchall()
    return [dict(zip(cols, r)) for r in rows]


def recent_captures(conn: sqlite3.Connection, limit: int = 3,
                    max_chars: int = 1500) -> list[dict]:
    """Most recent captures with (truncated) full OCR text — 'what's on my
    screen right now' questions don't match FTS keywords, so these are always
    fed to Ask verbatim."""
    rows = conn.execute(
        "SELECT id, ts, app, window_title, url, ocr_text FROM captures "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    cols = ["id", "ts", "app", "window_title", "url", "ocr_text"]
    out = []
    for row in rows:
        d = dict(zip(cols, row))
        d["ocr_text"] = d["ocr_text"][:max_chars]
        out.append(d)
    return out


def run_retention(conn: sqlite3.Connection) -> tuple[int, int]:
    """Delete captures and chats older than the retention window. Summaries kept forever."""
    cutoff = f"datetime('now', '-{config.RETENTION_DAYS} days')"
    hard = f"datetime('now', '-{config.RETENTION_DAYS * 2} days')"
    # Reinforcement: a wisp that's been recalled survives past the normal cutoff —
    # importance-based, not clock-based. A hard cap (2x the window) bounds growth
    # so the exemption can't let the DB grow forever.
    old = [r[0] for r in conn.execute(
        f"SELECT id FROM captures WHERE (ts < {cutoff} AND COALESCE(recall_count,0) = 0) "
        f"OR ts < {hard}")]
    c1 = delete_captures(conn, old)   # cascade choke point (fts + embedding + promises)
    c2 = conn.execute(f"DELETE FROM chats WHERE ts < {cutoff}").rowcount
    conn.commit()
    return c1, c2
