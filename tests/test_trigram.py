"""Trigram fuzzy retrieval — the OCR-noise resilience signal.

The exact word index misses a query word when OCR mangled its stored copy
('client' -> 'cl1ent'). The trigram index expands a clean query word into its
3-char shingles, which still overlap the mangled copy, so it surfaces as a fused
candidate. These lock: the index populates and cascades, fuzzy matching works,
and it only ever ADDS recall to hybrid search (never drops an exact hit).
"""

from rewisp import db


def _add(conn, text, app="A"):
    return db.insert_capture(conn, app, None, None, text)


def test_trigram_match_string_expands_words_to_shingles():
    m = db._trigram_match("client dashboard")
    assert '"cli"' in m and '"ent"' in m and '"das"' in m
    assert " OR " in m


def test_trigram_match_ignores_short_words():
    assert db._trigram_match("a to be") == ""       # nothing >= 3 chars


def test_trigram_finds_ocr_mangled_word(conn):
    clean = _add(conn, "the modern client dashboard shows latency")
    noisy = _add(conn, "the m0dern cl1ent dashboard shows latency")
    unrel = _add(conn, "quarterly budget review meeting notes")
    hits = db.search_captures_trigram(conn, "client", limit=10)
    assert clean in hits and noisy in hits      # both, despite the OCR slip
    assert unrel not in hits


def test_trigram_insert_trigger_keeps_index_live(conn):
    rid = _add(conn, "auth-gateway compiled successfully")
    # substring/partial recall the word tokenizer can't do: 'gateway' inside 'auth-gateway'
    assert rid in db.search_captures_trigram(conn, "gateway", limit=10)


def test_trigram_delete_trigger_cascades(conn):
    rid = _add(conn, "ephemeral secret token value here")
    assert rid in db.search_captures_trigram(conn, "ephemeral", limit=10)
    db.delete_captures(conn, [rid])
    assert rid not in db.search_captures_trigram(conn, "ephemeral", limit=10)


def test_backfill_rebuild_populates_existing_rows():
    # Real upgrade path: captures + old FTS exist BEFORE the trigram table, so its
    # index starts empty and the triggers never saw those rows. _migrate's flagged
    # rebuild must catch them up.
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.executescript(
        "CREATE TABLE captures(id INTEGER PRIMARY KEY, ts TEXT, app TEXT,"
        " window_title TEXT, url TEXT, ocr_text TEXT NOT NULL);")
    c.execute("INSERT INTO captures(ts,app,ocr_text) VALUES('t','A','retroactive indexing target')")
    # Now the current schema arrives (adds the trigram table + triggers + meta).
    c.executescript(db.SCHEMA)
    assert db.search_captures_trigram(c, "retroactive") == []   # not yet built
    db._migrate(c)
    assert len(db.search_captures_trigram(c, "retroactive")) == 1
    # Idempotent: a second migrate doesn't error or double-work.
    db._migrate(c)
    assert len(db.search_captures_trigram(c, "retroactive")) == 1
    c.close()


def test_backfill_flag_is_set_on_fresh_db(conn):
    # Fresh DB (no rows): flag still gets set so the rebuild never runs later on a
    # now-populated index (triggers already keep it live).
    assert conn.execute("SELECT value FROM meta WHERE key='trigram_built'").fetchone()[0] == "1"


def test_hybrid_surfaces_trigram_only_hit(conn):
    # A row only reachable via fuzzy trigram overlap still appears in hybrid
    # results (with a snippet pulled), even without a query vector.
    rid = _add(conn, "the cl1ent portal went down at noon")
    rows = db.search_captures_hybrid(conn, "client", None, limit=5)
    assert any(r["id"] == rid for r in rows)


def test_hybrid_still_returns_exact_fts_hit(conn):
    # Adding the fuzzy signal must never lose a clean exact match.
    rid = _add(conn, "unmistakable exact keyword zebra")
    rows = db.search_captures_hybrid(conn, "zebra", None, limit=5)
    assert any(r["id"] == rid for r in rows)
