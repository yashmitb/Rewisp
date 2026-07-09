"""SQLite store: captures + FTS5, summaries, chats, entities. WAL mode, UTC timestamps."""

import sqlite3
from datetime import datetime, timezone

from . import config

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


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def insert_capture(conn: sqlite3.Connection, app: str, window_title: str | None,
                   url: str | None, ocr_text: str) -> int:
    ocr_text = ocr_text[: config.MAX_OCR_CHARS]
    cur = conn.execute(
        "INSERT INTO captures (ts, app, window_title, url, ocr_text) VALUES (?, ?, ?, ?, ?)",
        (utcnow(), app, window_title, url, ocr_text),
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
    c1 = conn.execute(f"DELETE FROM captures WHERE ts < {cutoff}").rowcount
    c2 = conn.execute(f"DELETE FROM chats WHERE ts < {cutoff}").rowcount
    conn.commit()
    return c1, c2
