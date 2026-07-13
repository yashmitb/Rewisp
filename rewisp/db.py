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
    cur = conn.execute(
        "INSERT INTO captures (ts, app, window_title, url, ocr_text, embedding) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (utcnow(), app, window_title, url, ocr_text, embedding),
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


def search_captures_hybrid(conn: sqlite3.Connection, query: str, qvec,
                           limit: int = 20, since: str | None = None,
                           until: str | None = None) -> list[dict]:
    """FTS keyword search fused with semantic vector search via Reciprocal Rank
    Fusion. Falls back to FTS-only when no query vector is available (embedder
    offline). Row shape matches search_captures() so build_context is unchanged."""
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


def delete_captures(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Single choke point for removing captures — 'forget', kill-list purge, and
    retention all route here. The AFTER DELETE trigger cleans captures_fts and the
    embedding lives on the row, so both go with it. As derived tables land
    (deltas, promises, series, episodes) their cascade deletes attach HERE, so no
    forgotten wisp ever leaks into a downstream table."""
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    n = conn.execute(f"DELETE FROM captures WHERE id IN ({marks})", ids).rowcount
    # (future: delete from promises/series/episodes WHERE wisp_id IN (...))
    conn.commit()
    return n


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
    old = [r[0] for r in conn.execute(f"SELECT id FROM captures WHERE ts < {cutoff}")]
    c1 = delete_captures(conn, old)   # cascade choke point (fts + embedding + future tables)
    c2 = conn.execute(f"DELETE FROM chats WHERE ts < {cutoff}").rowcount
    conn.commit()
    return c1, c2
