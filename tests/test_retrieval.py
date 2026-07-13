"""Semantic memory: vector search, hybrid RRF fusion, cascade delete, page_key
lookups for delta. Uses the in-memory `conn` fixture."""

import numpy as np

from rewisp import db, embed


def _add(conn, app, title, url, text, emb=None):
    return db.insert_capture(conn, app, title, url, text, embedding=emb)


class TestVectorSearch:
    def test_ranks_by_cosine(self, conn):
        # three unit vectors; query equals v2 -> #2 ranks first
        base = np.eye(3, embed.DIM, dtype=np.float32)
        ids = [_add(conn, "A", None, None, f"t{i}", base[i].tobytes()) for i in range(3)]
        hits = db.vector_search(conn, base[1], k=3)
        assert hits[0][0] == ids[1]
        assert hits[0][1] > hits[1][1]  # cosine descending

    def test_skips_rows_without_embeddings(self, conn):
        v = np.eye(1, embed.DIM, dtype=np.float32)[0]
        _add(conn, "A", None, None, "no vec")           # embedding NULL
        hit_id = _add(conn, "B", None, None, "vec", v.tobytes())
        hits = db.vector_search(conn, v, k=5)
        assert [h[0] for h in hits] == [hit_id]

    def test_empty_when_no_embeddings(self, conn):
        _add(conn, "A", None, None, "no vec")
        assert db.vector_search(conn, np.ones(embed.DIM, np.float32), k=5) == []


class TestHybrid:
    def test_falls_back_to_fts_when_no_qvec(self, conn):
        _add(conn, "A", None, None, "alpha banana")
        _add(conn, "B", None, None, "gamma delta")
        rows = db.search_captures_hybrid(conn, "alpha", None, limit=5)
        assert len(rows) == 1 and rows[0]["app"] == "A"

    def test_vector_only_hit_is_included_and_tagged(self, conn):
        base = np.eye(3, embed.DIM, dtype=np.float32)
        a = _add(conn, "A", None, None, "alpha", base[0].tobytes())   # FTS match
        _add(conn, "B", None, None, "beta", base[1].tobytes())
        c = _add(conn, "C", None, None, "gamma", base[2].tobytes())   # vector match
        rows = db.search_captures_hybrid(conn, "alpha", base[2], limit=5)
        ids = [r["id"] for r in rows]
        assert a in ids and c in ids
        c_row = next(r for r in rows if r["id"] == c)
        assert c_row.get("vector_match") is True


class TestCascadeDelete:
    def test_delete_removes_row_and_fts(self, conn):
        rid = _add(conn, "A", None, None, "secret phrase to forget")
        assert db.search_captures(conn, "secret", limit=5)
        n = db.delete_captures(conn, [rid])
        assert n == 1
        assert db.search_captures(conn, "secret", limit=5) == []

    def test_delete_empty_is_noop(self, conn):
        assert db.delete_captures(conn, []) == 0


class TestVersionsForKey:
    def test_returns_latest_and_prior(self, conn):
        import time
        # same page_key via same app+title, different text over time
        for i, txt in enumerate(["v1 content", "v2 content", "v3 content"]):
            conn.execute(
                "INSERT INTO captures (ts, app, window_title, url, ocr_text, page_key) "
                "VALUES (datetime('now', ?), 'App', 'Page', NULL, ?, 'app::page')",
                (f"-{10-i*4} minutes", txt))
        conn.commit()
        old, new = db.versions_for_key(conn, "app::page")
        assert new["ocr_text"] == "v3 content"
        assert old["ocr_text"] in ("v1 content", "v2 content")

    def test_single_version_returns_none_old(self, conn):
        conn.execute("INSERT INTO captures (ts, app, window_title, url, ocr_text, page_key) "
                     "VALUES (datetime('now'), 'App', 'Page', NULL, 'only', 'app::page')")
        conn.commit()
        old, new = db.versions_for_key(conn, "app::page")
        assert new is not None and old is None
