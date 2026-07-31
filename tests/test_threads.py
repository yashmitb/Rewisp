"""Loose-thread ageing: the same unfinished thing, recognised across rewordings.

The digest re-derives its threads from scratch every night, so a thread that is
still open comes back described differently. Matching on characters fails at
exactly that point, which is why everything here is about content words.
"""

import pytest

from rewisp import threads


def _summary(conn, date, md):
    conn.execute("INSERT INTO summaries (date, summary_md, threads_md) VALUES (?, '', ?)",
                 (date, md))
    conn.commit()


class TestParse:
    def test_strips_bullets_markdown_and_carry_markers(self):
        md = ("- **Projector research has no decision.** A dozen models surveyed\n"
              "- *(carried from 7/26)* Rewisp capture-design question unresolved\n"
              "\n"
              "- None.\n")
        out = threads.parse(md)
        assert len(out) == 2
        assert out[0].startswith("**Projector research")
        assert "carried from" not in out[1]
        assert out[1].startswith("Rewisp capture-design")

    def test_empty_and_none_are_no_threads(self):
        assert threads.parse(None) == []
        assert threads.parse("") == []
        assert threads.parse("None.") == []


class TestMatching:
    def test_a_reworded_thread_is_the_same_thread(self):
        # Both of these are real phrasings of one unfinished thing from two
        # consecutive nights. Character similarity does not see it.
        a = threads._words("Gmail inbox untouched all day — opened but never answered")
        b = threads._words("Gmail opened and scanned but nothing answered; still-open items")
        assert threads._same(a, b)

    def test_different_threads_do_not_merge(self):
        a = threads._words("Projector research has no decision, a dozen models surveyed")
        b = threads._words("Chapter 7 TEST left in progress, still on question one")
        assert not threads._same(a, b)

    def test_one_shared_word_is_a_coincidence(self):
        a = threads._words("Amazon order still in transit")
        b = threads._words("Amazon customer service chat never completed")
        # "amazon" alone must not fuse two unrelated loose ends.
        assert not threads._same(a, b) or len(a & b) >= threads.MIN_SHARED_WORDS


class TestAgeing:
    def test_counts_consecutive_nights(self, conn):
        _summary(conn, "2026-07-26", "- Gmail inbox untouched, nothing answered all day")
        _summary(conn, "2026-07-27", "- Gmail opened but nothing was answered again")
        _summary(conn, "2026-07-28", "- Gmail inbox still unanswered, nothing sent")
        items = threads.open_threads(conn)
        assert len(items) == 1
        assert items[0]["nights"] == 3
        assert items[0]["first_seen"] == "2026-07-26"
        assert items[0]["days_open"] == 3

    def test_a_brand_new_thread_is_one_night(self, conn):
        _summary(conn, "2026-07-27", "- Something entirely unrelated about projectors")
        _summary(conn, "2026-07-28", "- Chapter 7 TEST left in progress on question one")
        items = threads.open_threads(conn)
        assert items[0]["nights"] == 1

    def test_a_gap_starts_the_count_over(self, conn):
        # Resolved, then came back: that is a new thread, not a longer-running one.
        _summary(conn, "2026-07-26", "- Gmail inbox untouched, nothing answered")
        _summary(conn, "2026-07-27", "- Projector research has no decision yet")
        _summary(conn, "2026-07-28", "- Gmail inbox untouched, nothing answered")
        items = threads.open_threads(conn)
        assert items[0]["nights"] == 1

    def test_longest_running_sorts_first(self, conn):
        _summary(conn, "2026-07-26", "- Gmail inbox untouched, nothing answered")
        _summary(conn, "2026-07-27", "- Gmail inbox untouched, nothing answered")
        _summary(conn, "2026-07-28", "- Gmail inbox untouched, nothing answered\n"
                                     "- Brand new projector decision still pending")
        items = threads.open_threads(conn)
        assert items[0]["nights"] == 3          # the old one leads, not the new one
        assert items[1]["nights"] == 1

    def test_no_digests_is_no_threads(self, conn):
        assert threads.open_threads(conn) == []


class TestDismissal:
    def test_dismissing_hides_the_thread(self, conn):
        _summary(conn, "2026-07-28", "- Gmail inbox untouched, nothing answered")
        assert len(threads.open_threads(conn)) == 1
        threads.dismiss(conn, "Gmail inbox untouched, nothing answered")
        assert threads.open_threads(conn) == []

    def test_dismissal_survives_a_rewording(self, conn):
        # The whole reason the key is content words: tomorrow's digest will
        # describe this differently, and it must stay dismissed.
        threads.dismiss(conn, "Gmail inbox untouched all day, nothing answered")
        _summary(conn, "2026-07-29",
                 "- Gmail opened and scanned but nothing answered, still unanswered")
        assert threads.open_threads(conn) == []

    def test_dismissing_one_leaves_the_others(self, conn):
        _summary(conn, "2026-07-28", "- Gmail inbox untouched, nothing answered\n"
                                     "- Projector research has no decision yet")
        threads.dismiss(conn, "Gmail inbox untouched, nothing answered")
        rest = threads.open_threads(conn)
        assert len(rest) == 1 and "Projector" in rest[0]["text"]
