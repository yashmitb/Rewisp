"""The embedding matrix is cached in memory. A cache that outlives a delete
would keep answering with wisps the user asked to forget, so these tests care
more about correctness than speed."""

import numpy as np
import pytest

from rewisp import config, db, embed


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.invalidate_vector_cache()
    c = db.connect()
    yield c
    c.close()
    db.invalidate_vector_cache()


def _vec(i):
    v = np.zeros(embed.DIM, dtype=np.float32)
    v[i % embed.DIM] = 1.0
    return v


def _add(c, i, text="x"):
    return db.insert_capture(c, "Dia", f"t{i}", None, text, embedding=_vec(i).tobytes())


def test_new_wisps_appear_without_a_restart(conn):
    _add(conn, 0)
    assert len(db.vector_search(conn, _vec(0), k=10)) == 1
    _add(conn, 1)
    # Incremental append: the second wisp must be searchable immediately.
    assert len(db.vector_search(conn, _vec(1), k=10)) == 2


def test_forgotten_wisps_leave_the_cache(conn):
    a = _add(conn, 0)
    _add(conn, 1)
    assert len(db.vector_search(conn, _vec(0), k=10)) == 2
    db.delete_captures(conn, [a])
    ids = [i for i, _ in db.vector_search(conn, _vec(0), k=10)]
    assert a not in ids, "a forgotten wisp was still served from cache"
    assert len(ids) == 1


def test_a_swapped_database_is_detected(conn, tmp_path, monkeypatch):
    """Restoring from a backup replaces the file under a running process."""
    _add(conn, 0)
    db.vector_search(conn, _vec(0), k=5)          # warm the cache
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "other.db")
    other = db.connect()
    try:
        # Different file, no rows: must not answer from the first database.
        assert db.vector_search(other, _vec(0), k=5) == []
    finally:
        other.close()


def test_malformed_embedding_does_not_break_search(conn):
    """One bad blob must not take out the whole retrieval path."""
    _add(conn, 0)
    conn.execute("INSERT INTO captures (ts, app, ocr_text, embedding, page_key) "
                 "VALUES (datetime('now'), 'Dia', 'junk', ?, 'k')", (b"\x00\x01",))
    conn.commit()
    db.invalidate_vector_cache()
    hits = db.vector_search(conn, _vec(0), k=10)
    assert len(hits) == 1, "the good wisp should still be findable"


def test_time_window_filters_correctly(conn):
    _add(conn, 0)
    conn.execute("UPDATE captures SET ts = datetime('now','-30 days')")
    conn.commit()
    _add(conn, 1)
    db.invalidate_vector_cache()
    recent = db.vector_search(conn, _vec(1), k=10,
                              since=conn.execute(
                                  "SELECT datetime('now','-1 day')").fetchone()[0])
    assert len(recent) == 1, "the 30-day-old wisp should be outside the window"


def test_empty_corpus_is_not_an_error(conn):
    assert db.vector_search(conn, _vec(0), k=5) == []
