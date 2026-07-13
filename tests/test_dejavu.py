"""Déjà Vu detection gates + the nudge queue helpers."""

import numpy as np

from rewisp import db, dejavu, embed


def _add_old(conn, app, page_key, text, vec, days_ago):
    cur = conn.execute(
        "INSERT INTO captures (ts, app, window_title, url, ocr_text, embedding, page_key) "
        "VALUES (datetime('now', ?), ?, NULL, NULL, ?, ?, ?)",
        (f"-{days_ago} days", app, text, vec.tobytes(), page_key))
    conn.commit()
    return cur.lastrowid


class TestFindRecall:
    def test_returns_older_match_in_different_context(self, conn):
        v = np.eye(1, embed.DIM, dtype=np.float32)[0]
        old = _add_old(conn, "Safari", "site::paper", "the kennedy paper on economics", v, days_ago=3)
        got = dejavu.find_recall(conn, wisp_id=999, qvec=v, app="Notes",
                                 page_key="notes::draft", threshold=0.5)
        assert got and got["source_wisp_id"] == old

    def test_below_threshold_returns_none(self, conn):
        v = np.eye(2, embed.DIM, dtype=np.float32)
        _add_old(conn, "Safari", "site::a", "x", v[0], days_ago=3)
        got = dejavu.find_recall(conn, 999, v[1], "Notes", "notes::d", threshold=0.5)
        assert got is None                       # orthogonal vectors, cosine ~0

    def test_recent_match_within_24h_excluded(self, conn):
        v = np.eye(1, embed.DIM, dtype=np.float32)[0]
        _add_old(conn, "Safari", "site::a", "x", v, days_ago=0)   # too recent
        got = dejavu.find_recall(conn, 999, v, "Notes", "notes::d", threshold=0.5)
        assert got is None

    def test_same_context_skipped(self, conn):
        v = np.eye(1, embed.DIM, dtype=np.float32)[0]
        _add_old(conn, "Notes", "notes::draft", "x", v, days_ago=3)
        got = dejavu.find_recall(conn, 999, v, "Notes", "notes::draft", threshold=0.5)
        assert got is None                       # same app AND same page = not a recall


class TestNudgeQueue:
    def test_enqueue_and_pending(self, conn):
        db.enqueue_nudge(conn, "dejavu", "t", "b", source_wisp_id=1, topic_key="k")
        p = db.pending_nudges(conn)
        assert len(p) == 1 and p[0]["title"] == "t"

    def test_count_today(self, conn):
        for _ in range(3):
            db.enqueue_nudge(conn, "dejavu", "t", "b", topic_key="k")
        assert db.nudge_count_today(conn) == 3

    def test_topic_cooldown(self, conn):
        db.enqueue_nudge(conn, "dejavu", "t", "b", topic_key="topicX")
        assert db.nudge_topic_recent(conn, "topicX") is True
        assert db.nudge_topic_recent(conn, "other") is False

    def test_delivered_leaves_queue(self, conn):
        nid = db.enqueue_nudge(conn, "dejavu", "t", "b", topic_key="k")
        db.mark_nudge_delivered(conn, nid)
        assert db.pending_nudges(conn) == []

    def test_feedback_recorded(self, conn):
        nid = db.enqueue_nudge(conn, "dejavu", "t", "b", topic_key="k")
        db.nudge_feedback(conn, nid, "up")
        row = conn.execute("SELECT feedback, status FROM nudges WHERE id=?", (nid,)).fetchone()
        assert row == ("up", "dismissed")


class TestMaybeNudgeGating:
    def test_disabled_by_default(self, conn, monkeypatch):
        monkeypatch.setattr(db.config, "load_settings", lambda: dict(db.config.DEFAULT_SETTINGS))
        v = np.eye(1, embed.DIM, dtype=np.float32)[0]
        _add_old(conn, "Safari", "site::a", "x", v, days_ago=3)
        assert dejavu.maybe_nudge(conn, 999, v, "Notes", "notes::d") is None

    def test_enabled_enqueues(self, conn, monkeypatch):
        s = dict(db.config.DEFAULT_SETTINGS); s["nudges_enabled"] = True; s["nudge_similarity"] = 0.5
        monkeypatch.setattr(dejavu.config, "load_settings", lambda: s)
        v = np.eye(1, embed.DIM, dtype=np.float32)[0]
        _add_old(conn, "Safari", "site::a", "the kennedy paper", v, days_ago=3)
        nid = dejavu.maybe_nudge(conn, 999, v, "Notes", "notes::d")
        assert nid and len(db.pending_nudges(conn)) == 1
