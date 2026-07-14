"""Dream Mode consolidation + Reinforcement weighting."""

import numpy as np

from rewisp import db, dream, embed


def _add_at(conn, ts_offset_min, app, key, text):
    cur = conn.execute(
        "INSERT INTO captures (ts, app, window_title, url, ocr_text, page_key) "
        "VALUES (datetime('now', ?), ?, NULL, NULL, ?, ?)",
        (f"{ts_offset_min} minutes", app, text, key))
    conn.commit()
    return cur.lastrowid


class TestReinforcement:
    def test_bump_and_weight_order(self, conn):
        a = db.insert_capture(conn, "A", None, None, "alpha")
        b = db.insert_capture(conn, "B", None, None, "beta")
        db.bump_recall(conn, [a]); db.bump_recall(conn, [a])   # a recalled twice
        ranked = db.reinforcement_rank(conn, [a, b])
        assert ranked == [a]                    # only a has weight > 0, ranks first

    def test_retention_exempts_recalled(self, conn):
        # both old; one recalled -> survives
        old = conn.execute(
            "INSERT INTO captures (ts, app, ocr_text) VALUES (datetime('now','-200 days'),'A','x')")
        keep_id = old.lastrowid
        conn.execute(
            "INSERT INTO captures (ts, app, ocr_text) VALUES (datetime('now','-200 days'),'B','y')")
        conn.commit()
        db.bump_recall(conn, [keep_id])
        db.run_retention(conn)
        rows = [r[0] for r in conn.execute("SELECT id FROM captures")]
        assert keep_id in rows and len(rows) == 1

    def test_retention_hard_cap(self, conn):
        # recalled but WAY past the hard cap (2x window) -> still deleted
        c = conn.execute(
            "INSERT INTO captures (ts, app, ocr_text) VALUES (datetime('now','-400 days'),'A','x')")
        db.bump_recall(conn, [c.lastrowid])
        db.run_retention(conn)
        assert conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 0


class TestConsolidation:
    def test_clusters_by_gap_and_page(self, conn):
        # session 1: two wisps same page close in time
        _add_at(conn, -120, "Docs", "docs::a", "Writing the quarterly plan for the team offsite")
        _add_at(conn, -119, "Docs", "docs::a", "Writing the quarterly plan and budget numbers 4500")
        # session 2: different page, later
        _add_at(conn, -30, "Mail", "mail::b", "Email from Dana about the vendor contract renewal")
        _add_at(conn, -29, "Mail", "mail::b", "Email thread about the vendor contract and pricing")
        d = conn.execute("SELECT date(ts) FROM captures LIMIT 1").fetchone()[0]
        n = dream.consolidate_day(conn, d)
        assert n == 2                           # two sessions -> two episodes
        eps = conn.execute("SELECT title, summary FROM episodes ORDER BY span_start").fetchall()
        assert "Docs" in eps[0][0] or "Mail" in eps[0][0]

    def test_episode_is_searchable(self, conn):
        _add_at(conn, -60, "Docs", "docs::a", "Notes on photosynthesis and chloroplast structure")
        _add_at(conn, -59, "Docs", "docs::a", "More on photosynthesis, light reactions and ATP")
        d = conn.execute("SELECT date(ts) FROM captures LIMIT 1").fetchone()[0]
        dream.consolidate_day(conn, d)
        hits = dream.search_episodes(conn, "photosynthesis", None, limit=3)
        assert hits and "photosynthesis" in (hits[0]["summary"] + hits[0]["title"]).lower()

    def test_idempotent(self, conn):
        for i in range(3):
            _add_at(conn, -60 - i, "Docs", "docs::a", f"line {i} about the same working session topic")
        d = conn.execute("SELECT date(ts) FROM captures LIMIT 1").fetchone()[0]
        dream.consolidate_day(conn, d)
        dream.consolidate_day(conn, d)          # re-run
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] >= 1
        # no duplication of the day
        dates = conn.execute("SELECT COUNT(DISTINCT date) FROM episodes").fetchone()[0]
        assert dates == 1

    def test_cascade_delete_drops_episode(self, conn):
        a = _add_at(conn, -60, "Docs", "docs::a", "session line one about the report draft")
        b = _add_at(conn, -59, "Docs", "docs::a", "session line two about the report draft numbers")
        d = conn.execute("SELECT date(ts) FROM captures LIMIT 1").fetchone()[0]
        dream.consolidate_day(conn, d)
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 1
        db.delete_captures(conn, [a, b])        # forget the wisps
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0
