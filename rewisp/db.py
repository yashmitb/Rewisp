"""SQLite store: captures + FTS5, summaries, chats, entities. WAL mode, UTC timestamps."""

import logging
import pathlib
import re
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

-- Small key/value store for one-time migration state (e.g. whether the trigram
-- index has been backfilled). External-content FTS5 can't be probed for
-- "is it built" — its EXISTS reads through to the content table — so a flag here
-- is the reliable signal.
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

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

-- Trigram index over the same text. The word tokenizer above is exact: an OCR
-- slip ('cl1ent' for 'client') makes a query word miss entirely. The trigram
-- tokenizer indexes every 3-char shingle, so a query word expanded to its own
-- trigrams still overlaps a mangled copy and surfaces it. Used only as one more
-- fused (rank-based) signal in search_captures_hybrid, so the extra fuzzy hits
-- it brings can lift recall without hurting precision. Separate triggers (new
-- names) because CREATE TRIGGER IF NOT EXISTS won't rewrite the bodies above on
-- an existing database.
CREATE VIRTUAL TABLE IF NOT EXISTS captures_trigram USING fts5(
  ocr_text, content=captures, content_rowid=id, tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS captures_ai_tri AFTER INSERT ON captures BEGIN
  INSERT INTO captures_trigram(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;
CREATE TRIGGER IF NOT EXISTS captures_ad_tri AFTER DELETE ON captures BEGIN
  INSERT INTO captures_trigram(captures_trigram, rowid, ocr_text)
  VALUES ('delete', old.id, old.ocr_text);
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

CREATE TABLE IF NOT EXISTS pinned (          -- facts you kept re-asking, kept forever
  id INTEGER PRIMARY KEY,
  question TEXT,
  answer TEXT,
  embedding BLOB,
  created_at TEXT,
  source_wisp_ids TEXT       -- JSON list, so forgetting a source removes the pin
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
    pincols = {r[1] for r in conn.execute("PRAGMA table_info(pinned)")}
    if pincols and "source_wisp_ids" not in pincols:
        # Provenance for pinned facts. Existing pins have none, so they cannot be
        # cascaded — they predate the tracking. Deliberately not deleted here:
        # silently removing facts someone relies on, to fix a leak they may not
        # have, is the worse trade. New pins are covered from now on.
        conn.execute("ALTER TABLE pinned ADD COLUMN source_wisp_ids TEXT")
        conn.commit()
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(promises)")}
    if pcols and "reminded_at" not in pcols:
        # Due-day reminders: one pill per promise per day, never spam.
        conn.execute("ALTER TABLE promises ADD COLUMN reminded_at TEXT")
        conn.commit()
    if "recall_count" not in cols:
        # Reinforcement: every time a wisp is recalled it strengthens — ranks
        # higher and survives consolidation/retention longer.
        conn.execute("ALTER TABLE captures ADD COLUMN recall_count INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE captures ADD COLUMN last_recalled TEXT")
        conn.commit()
    if "rescued" not in cols:
        # Forgetting model: a wisp gets ONE "about to fade" rescue mention, ever.
        conn.execute("ALTER TABLE captures ADD COLUMN rescued INTEGER DEFAULT 0")
        conn.commit()

    # One-time backfill of the trigram index. The triggers only cover rows
    # inserted after the table exists, so on an existing database it starts empty
    # while captures is full. FTS5's external-content 'rebuild' repopulates it from
    # the content table in one pass. Gated by a meta flag rather than a row count:
    # an external-content FTS5 reports EXISTS=1 even when its index is empty
    # (it reads through to the content table), so a count check would wrongly skip
    # the rebuild and leave every pre-upgrade row unindexed.
    try:
        done = conn.execute("SELECT 1 FROM meta WHERE key='trigram_built'").fetchone()
        if not done:
            if conn.execute("SELECT EXISTS(SELECT 1 FROM captures)").fetchone()[0]:
                log.info("building trigram index (one-time)…")
                conn.execute("INSERT INTO captures_trigram(captures_trigram) VALUES('rebuild')")
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('trigram_built','1')")
            conn.commit()
    except Exception:  # noqa: BLE001 — a fuzzy-recall index is optional; never block open
        log.exception("trigram backfill skipped")


def _driver():
    """SQLCipher when it is available, plain sqlite3 otherwise.

    The API is identical, so everything above this line is unaffected either way.
    """
    try:
        from sqlcipher3 import dbapi2 as driver
        return driver
    except ImportError:
        return sqlite3


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    from . import crypto

    driver = _driver()
    key = None
    if driver is not sqlite3:
        # Encrypt automatically, with no step for the user. If anything about the
        # key is unavailable we stay on the plaintext database rather than
        # failing: encryption must never be the reason someone cannot open their
        # own memory.
        try:
            key = crypto.get_key(create=True)
            if key:
                _encrypt_in_place_if_needed(driver, key)
        except Exception:  # noqa: BLE001
            log.exception("encryption setup failed — continuing unencrypted")
            key = None

    # An encrypted database opened by a build WITHOUT SQLCipher fails deep in
    # sqlite3 with "file is not a database" — indistinguishable from corruption,
    # and an invitation for something upstream to recreate it. Say what is
    # actually wrong instead.
    if driver is sqlite3 and crypto.is_encrypted(config.DB_PATH):
        raise RuntimeError(
            "This Rewisp database is encrypted, but this build has no SQLCipher "
            "support, so it cannot be opened. Your data is intact — use a "
            "current build of Rewisp. Nothing has been changed.")

    # A database already encrypted on disk MUST be opened with the key, even if
    # something above went wrong; opening it without one would look like
    # corruption and could tempt a caller into recreating it.
    if key is None and crypto.is_encrypted(config.DB_PATH):
        key = crypto.get_key(create=False)
        if key is None:
            raise RuntimeError(
                "The Rewisp database is encrypted but its key could not be read "
                "from the Keychain. Nothing has been changed.")

    conn = driver.connect(config.DB_PATH)
    if key:
        conn.execute(f"PRAGMA key = \"x'{key}'\"")
        conn.execute("SELECT count(*) FROM sqlite_master")   # fails fast on a bad key
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _encrypt_in_place_if_needed(driver, key: str) -> None:
    """Convert an existing plaintext database, once, safely.

    Deliberately paranoid about ordering, because the input is months of the
    user's memory and there is no second copy:

      1. export into a NEW file, leaving the original untouched
      2. verify the copy independently — row counts per table AND a real FTS
         query, since a file that opens is not the same as a file that works
      3. only then move the original aside and swap the new one in
      4. keep the original until the next clean start

    Any failure leaves the plaintext database exactly where it was.
    """
    from . import crypto
    path = pathlib.Path(config.DB_PATH)
    if not path.exists() or path.stat().st_size == 0:
        return                       # fresh install: created encrypted below
    if crypto.is_encrypted(path):
        return                       # already done

    tmp = path.with_suffix(".encrypting")
    tmp.unlink(missing_ok=True)
    log.info("encryption: converting the database (%.0f MB)", path.stat().st_size / 1e6)

    tables = [r[0] for r in sqlite3.connect(path).execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    before = {}
    src = sqlite3.connect(path)
    for t in tables:
        try:
            before[t] = src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.DatabaseError:
            pass                     # virtual/shadow tables aren't all countable
    src.close()

    conn = driver.connect(str(path))          # plaintext source takes no key
    conn.execute(f"ATTACH DATABASE '{tmp}' AS enc KEY \"x'{key}'\"")
    conn.execute("SELECT sqlcipher_export('enc')")
    conn.execute("DETACH DATABASE enc")
    conn.close()

    check = driver.connect(str(tmp))
    check.execute(f"PRAGMA key = \"x'{key}'\"")
    after = {}
    for t in before:
        after[t] = check.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    # Opening is not the same as working: prove the search index came across.
    try:
        check.execute("SELECT COUNT(*) FROM captures_fts "
                      "WHERE captures_fts MATCH 'the'").fetchone()
    except Exception as e:  # noqa: BLE001
        check.close(); tmp.unlink(missing_ok=True)
        raise RuntimeError(f"encrypted copy failed its search check: {e}") from e
    check.close()

    if after != before:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"row counts differ after conversion: {before} vs {after}")

    backup = path.with_suffix(".plaintext-backup")
    backup.unlink(missing_ok=True)
    path.replace(backup)              # original preserved, not deleted
    tmp.replace(path)
    # WAL/SHM belong to the old file; leaving them would confuse the new one.
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    log.info("encryption: done — previous database kept at %s", backup.name)


def insert_capture(conn: sqlite3.Connection, app: str, window_title: str | None,
                   url: str | None, ocr_text: str, embedding: bytes | None = None) -> int:
    # Redact validated card/SSN numbers here too, not only in the daemon: this is
    # the single choke point every ingestion path passes through, so the database
    # cannot hold one even if a future caller forgets. Idempotent with the daemon's
    # earlier pass (which also protects the embedding).
    if config.REDACT_PII:
        from . import redact
        ocr_text = redact.scrub_pii(ocr_text)
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


def _trigram_match(query: str) -> str:
    """Turn a query into a trigram-tokenizer MATCH string: each content word (≥3
    chars) becomes an OR of its own 3-char shingles. A word and an OCR-mangled
    copy of it share most shingles, so a clean query still overlaps a noisy stored
    word ('client' finds 'cl1ent'). Returns '' when nothing is long enough."""
    words = re.findall(r"[a-z0-9]{3,}", query.lower())
    grams: list[str] = []
    seen: set[str] = set()
    for w in words[:12]:                     # cap: keep the MATCH string bounded
        for i in range(len(w) - 2):
            g = w[i:i + 3]
            if g not in seen:
                seen.add(g)
                grams.append(f'"{g}"')
    return " OR ".join(grams)


def search_captures_trigram(conn: sqlite3.Connection, query: str, limit: int = 40,
                            since: str | None = None, until: str | None = None) -> list[int]:
    """Fuzzy candidate ids from the trigram index, best first. Robust to OCR
    character errors that the exact word index misses. Returns ids only — this is
    a recall signal fused by rank in search_captures_hybrid, not a result set."""
    match = _trigram_match(query)
    if not match:
        return []
    sql = ("SELECT captures_trigram.rowid FROM captures_trigram "
           "JOIN captures c ON c.id = captures_trigram.rowid "
           "WHERE captures_trigram MATCH ?")
    params: list = [match]
    if since:
        sql += " AND c.ts >= ?"; params.append(since)
    if until:
        sql += " AND c.ts <= ?"; params.append(until)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    try:
        return [row[0] for row in conn.execute(sql, params)]
    except Exception:  # noqa: BLE001 — a missing/immature trigram index must not break search
        return []


# Cached embedding matrix for semantic search.
#
# vector_search used to pull every embedding out of SQLite and rebuild the numpy
# matrix on EVERY query: 12k rows measured at 24 ms warm, growing linearly, and
# paid again for each of the several searches a single question can trigger. The
# matmul was never the cost — the loading was.
#
# The daemon is long-lived, so the matrix is held in memory and extended
# incrementally as wisps arrive. Deletions (forget, kill-list purge, retention)
# are caught by a row-count check, which is cheap and cannot silently keep a
# forgotten wisp searchable — the one failure mode that would actually matter
# here.
_VEC = {"db": None, "max_id": 0, "count": 0, "ids": None, "mat": None, "ts": None}


def _db_identity(conn: sqlite3.Connection) -> str:
    """Which file this connection is actually attached to.

    The cache is module-level, so it must know when the database underneath it
    changes. That is not hypothetical: restoring from a backup swaps the file
    while the process keeps running, and a cache keyed to nothing would go on
    answering from embeddings that no longer exist.
    """
    try:
        for _seq, name, path in conn.execute("PRAGMA database_list"):
            if name == "main":
                return path or ":memory:"
    except sqlite3.Error:
        pass
    return ":memory:"


def _epoch(ts: str) -> float:
    """DB timestamps are UTC 'YYYY-MM-DD HH:MM:SS'. Compared as floats so the
    time window is a numpy mask rather than per-row string parsing."""
    from datetime import datetime, timezone
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _refresh_vec_cache(conn: sqlite3.Connection) -> None:
    import numpy as np
    total, = conn.execute(
        "SELECT COUNT(*) FROM captures WHERE embedding IS NOT NULL").fetchone()
    identity = _db_identity(conn)
    # Fewer rows than we hold means something was deleted; the cached copy could
    # otherwise keep serving a wisp the user asked to forget. A different file
    # means the database was swapped underneath us entirely.
    if _VEC["ids"] is None or total < _VEC["count"] or _VEC["db"] != identity:
        _VEC.update(max_id=0, count=0, ids=None, mat=None, ts=None)

    rows = conn.execute(
        "SELECT id, ts, embedding FROM captures "
        "WHERE embedding IS NOT NULL AND id > ? ORDER BY id",
        (_VEC["max_id"],)).fetchall()
    if not rows and _VEC["ids"] is not None:
        return

    # Skip blobs that are not the expected width. One malformed embedding would
    # otherwise break EVERY semantic search, because vstack demands uniform rows —
    # a single bad byte-count taking out the whole retrieval path. Cheap to
    # tolerate: that wisp simply falls back to keyword matching.
    from . import embed as _embed
    want = _embed.DIM * 4                      # float32
    keep = [r for r in rows if r[2] is not None and len(r[2]) == want]
    skipped = len(rows) - len(keep)
    if skipped:
        log.warning("vector cache: skipped %d capture(s) with malformed embeddings",
                    skipped)
    if not keep:
        # Still advance past these rows, or every call retries them forever.
        if rows:
            _VEC["max_id"] = max(_VEC["max_id"], max(r[0] for r in rows))
        _VEC["count"] = total
        _VEC["db"] = identity
        return

    new_ids = np.fromiter((r[0] for r in keep), dtype=np.int64, count=len(keep))
    new_ts = np.fromiter((_epoch(r[1]) for r in keep), dtype=np.float64, count=len(keep))
    new_mat = np.vstack([np.frombuffer(r[2], dtype=np.float32) for r in keep])

    if _VEC["ids"] is None:
        _VEC.update(ids=new_ids, ts=new_ts, mat=new_mat)
    elif rows:
        _VEC["ids"] = np.concatenate([_VEC["ids"], new_ids])
        _VEC["ts"] = np.concatenate([_VEC["ts"], new_ts])
        _VEC["mat"] = np.vstack([_VEC["mat"], new_mat])

    if rows:
        _VEC["max_id"] = max(_VEC["max_id"], max(r[0] for r in rows))
    elif _VEC["ids"] is not None and len(_VEC["ids"]):
        _VEC["max_id"] = max(_VEC["max_id"], int(_VEC["ids"][-1]))
    _VEC["count"] = total
    _VEC["db"] = identity


def vector_search(conn: sqlite3.Connection, qvec, k: int = 40,
                  since: str | None = None, until: str | None = None) -> list[tuple[int, float]]:
    """Cosine over stored embeddings, against an in-memory matrix.

    Brute force is still the right call at this scale — a single matmul over
    ~20k x 512 float32 is a few ms, and no ANN index earns its complexity until
    the corpus is far larger. What did not scale was rebuilding the matrix from
    SQLite on every call. Returns [(id, score)] descending.
    """
    import numpy as np
    _refresh_vec_cache(conn)
    if _VEC["ids"] is None or not len(_VEC["ids"]):
        return []

    mat, ids, ts = _VEC["mat"], _VEC["ids"], _VEC["ts"]
    if since or until:
        mask = np.ones(len(ids), dtype=bool)
        if since:
            mask &= ts >= _epoch(since)
        if until:
            mask &= ts <= _epoch(until)
        if not mask.any():
            return []
        mat, ids = mat[mask], ids[mask]

    q = np.asarray(qvec, dtype=np.float32)
    q = q / (np.linalg.norm(q) + 1e-9)
    sims = mat @ q                             # cosine: both sides unit-norm
    k = min(k, len(ids))
    top = np.argpartition(-sims, k - 1)[:k]
    top = top[np.argsort(-sims[top])]
    return [(int(ids[i]), float(sims[i])) for i in top]


def invalidate_vector_cache() -> None:
    """Drop the cached matrix. Called after deletes so a forgotten wisp cannot
    be served from memory even for the moment before the count check notices."""
    _VEC.update(db=None, max_id=0, count=0, ids=None, mat=None, ts=None)


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
    tri_hits = search_captures_trigram(conn, query, limit=config.RRF_POOL, since=since, until=until)
    if qvec is None and not tri_hits:
        return fts_rows[:limit]
    vec_hits = vector_search(conn, qvec, k=config.RRF_POOL, since=since, until=until) if qvec is not None else []

    kk = config.RRF_K
    fused: dict[int, float] = {}
    for rank, r in enumerate(fts_rows):
        fused[r["id"]] = fused.get(r["id"], 0.0) + 1.0 / (kk + rank)
    for rank, (rid, _score) in enumerate(vec_hits):
        fused[rid] = fused.get(rid, 0.0) + 1.0 / (kk + rank)
    # Fuzzy signal: trigram overlap, robust to OCR character errors the exact FTS
    # missed. Rank-based like the others, so noisy fuzzy hits sit below anything a
    # second signal corroborates.
    for rank, rid in enumerate(tri_hits):
        fused[rid] = fused.get(rid, 0.0) + 1.0 / (kk + rank)
    # Reinforcement weight, over the candidates we already have.
    for rank, rid in enumerate(reinforcement_rank(conn, list(fused))):
        fused[rid] = fused.get(rid, 0.0) + 1.0 / (kk + rank)

    order = sorted(fused, key=lambda i: -fused[i])[:limit]
    by_id = {r["id"]: r for r in fts_rows}
    missing = [i for i in order if i not in by_id]
    if missing:
        # Vector- or trigram-only hits have no FTS snippet — pull a plain head.
        q = f"SELECT id, ts, app, window_title, url, substr(ocr_text,1,300) FROM captures WHERE id IN ({','.join('?' * len(missing))})"
        cols = ["id", "ts", "app", "window_title", "url", "snippet"]
        for row in conn.execute(q, missing):
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
    # Nudges quote the wisp verbatim in their body ("You saw this on Sunday in
    # Dia: …"), so a surviving nudge repeats content the user asked to forget
    # straight back at them. This table was added after the docstring above was
    # written and never attached to the cascade — exactly the leak it promises
    # cannot happen.
    conn.execute(f"DELETE FROM nudges WHERE source_wisp_id IN ({marks})", ids)
    # Pinned facts are kept forever on purpose, which makes them the one place a
    # forgotten wisp could survive indefinitely — as a deterministic answer, no
    # less. If any source is forgotten, the pin goes too, exactly as episodes do.
    try:
        import json as _json
        gone_pins = [pid for pid, sj in conn.execute(
            "SELECT id, source_wisp_ids FROM pinned WHERE source_wisp_ids IS NOT NULL")
            if sj and idset & set(_json.loads(sj))]
        if gone_pins:
            conn.execute(
                f"DELETE FROM pinned WHERE id IN ({','.join('?' * len(gone_pins))})",
                gone_pins)
    except Exception:  # noqa: BLE001 — never let this block a delete
        log.debug("pinned cascade failed", exc_info=True)
    n = conn.execute(f"DELETE FROM captures WHERE id IN ({marks})", ids).rowcount
    conn.commit()
    invalidate_vector_cache()
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


def promises_needing_reminder(conn: sqlite3.Connection) -> list[dict]:
    """Due/overdue confirmed promises not yet reminded today. Confirming a
    promise is the opt-in for its reminder — pending ones stay silent."""
    cols = ["id", "who", "what", "due", "created_at"]
    rows = conn.execute(
        "SELECT id, who, what, due, created_at FROM promises WHERE status='confirmed' "
        "AND due IS NOT NULL AND due <= date('now') "
        "AND (reminded_at IS NULL OR date(reminded_at) < date('now'))").fetchall()
    return [dict(zip(cols, r)) for r in rows]


def mark_promise_reminded(conn: sqlite3.Connection, promise_id: int) -> None:
    conn.execute("UPDATE promises SET reminded_at=? WHERE id=?", (utcnow(), promise_id))
    conn.commit()


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
