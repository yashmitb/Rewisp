"""build_context routing — activity questions must stay inside their time window
(the 'what did I do today gives past data' bug)."""

import re
import unittest.mock as mock

from rewisp import ask, db


# TODAY was flaky for one hour a night: run the suite at 00:30 and a wisp an
# hour old belongs to YESTERDAY in local time, so a "what did I do today" query
# correctly excluded it and the test failed on a product that was working. These
# tests are about the time WINDOW, not about clock arithmetic, so today-wisps are
# pinned to the current minute — always inside today, whenever the suite runs.
TODAY = "-1 minutes"


def _wisp(conn, text, ago, app="Dia"):
    conn.execute("INSERT INTO captures (ts, app, window_title, url, ocr_text, page_key) "
                 "VALUES (datetime('now', ?), ?, NULL, NULL, ?, 'k')", (ago, app, text))
    conn.commit()


class TestActivityQuestions:
    def test_activity_regex(self):
        for q in ["what did I do today?", "what did I work on today",
                  "summarize my day", "what was I working on yesterday",
                  "recap of this morning"]:
            assert ask._ACTIVITY_Q.search(q), q
        assert not ask._ACTIVITY_Q.search("what is my linkedin url")

    def test_today_context_excludes_old_captures(self, conn):
        _wisp(conn, "OLD project meeting notes alpha", "-6 days")
        _wisp(conn, "TODAY editing the rewisp landing page", TODAY)
        with mock.patch("rewisp.embed.embed_vec", return_value=None):
            ctx, meta = ask.build_context(conn, "what did I do today?", compact=True)
        assert "TODAY editing" in ctx and "OLD project" not in ctx

    def test_summarize_my_day_gets_today_window(self, conn):
        _wisp(conn, "OLD thing beta", "-6 days")
        _wisp(conn, "TODAY thing gamma", TODAY)
        with mock.patch("rewisp.embed.embed_vec", return_value=None):
            ctx, meta = ask.build_context(conn, "summarize my day", compact=True)
        assert meta["since"] is not None          # defaulted to today
        assert "OLD thing" not in ctx

    def test_activity_question_skips_vault(self, conn):
        conn.execute("INSERT INTO vault_files (path, content, mtime) VALUES "
                     "('portfolio.pdf', 'my work on GradeHQ project', 0)")
        _wisp(conn, "TODAY writing tests", TODAY)
        conn.commit()
        with mock.patch("rewisp.embed.embed_vec", return_value=None):
            ctx, _ = ask.build_context(conn, "what did I work on today", compact=True)
        assert "[vault:" not in ctx

    def test_past_window_hides_current_screen_block(self, conn):
        _wisp(conn, "yesterday content delta", "-1 days")
        _wisp(conn, "right now content epsilon", "-1 minutes")
        with mock.patch("rewisp.embed.embed_vec", return_value=None):
            ctx, _ = ask.build_context(conn, "what was I working on yesterday", compact=True)
        assert "Current / most recent" not in ctx

    def test_specific_question_keeps_vault_and_history(self, conn):
        conn.execute("INSERT INTO vault_files (path, content, mtime) VALUES "
                     "('links.md', 'linkedin: linkedin.com/in/yashmit', 0)")
        conn.commit()
        with mock.patch("rewisp.embed.embed_vec", return_value=None):
            ctx, _ = ask.build_context(conn, "what is my linkedin url", compact=True)
        assert "[vault:" in ctx
