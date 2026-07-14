"""Precognition — query logging + suggestion ranking."""

from rewisp import db, precog


class TestLogging:
    def test_log_and_embed(self, conn):
        precog.log_query(conn, "what did I do today?", "Safari")
        row = conn.execute("SELECT text, app_context, embedding FROM queries").fetchone()
        assert row[0] == "what did I do today?" and row[1] == "Safari"
        assert row[2] is not None                 # embedded

    def test_mark_tapped(self, conn):
        precog.log_query(conn, "where's my zoom link?")
        precog.mark_tapped(conn, "where's my zoom link?")
        assert conn.execute("SELECT was_tapped FROM queries").fetchone()[0] == 1


class TestSuggest:
    def test_stacktrace_template(self, conn):
        db.insert_capture(conn, "Terminal", None, None,
                          "Traceback (most recent call last):\n  File x\nValueError: boom")
        s = precog.suggest(conn)
        assert any("error" in q.lower() for q in s)

    def test_meeting_template(self, conn):
        db.insert_capture(conn, "Calendar", None, None, "Standup — Join now via Zoom meeting")
        s = precog.suggest(conn)
        assert any("link" in q.lower() for q in s)

    def test_changed_page_template(self, conn):
        # same page captured twice -> "what changed" is offered
        for _ in range(2):
            db.insert_capture(conn, "Chrome", "Dashboard", "https://ex.com/d", "metrics content")
        s = precog.suggest(conn)
        assert any("changed" in q.lower() for q in s)

    def test_history_ranked_by_screen(self, conn):
        # log a past query about photosynthesis; current screen is about it
        precog.log_query(conn, "explain photosynthesis light reactions")
        precog.log_query(conn, "best pizza in town")
        db.insert_capture(conn, "Notes", None, None,
                          "chloroplast photosynthesis ATP light reaction notes")
        s = precog.suggest(conn, limit=3)
        assert any("photosynthesis" in q.lower() for q in s)

    def test_empty_when_nothing(self, conn):
        assert precog.suggest(conn) == []
