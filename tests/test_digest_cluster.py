"""Nightly digest input: topic clustering, dedup, and significance ordering.

The digest is the one cloud call a day, and its input is truncated to a budget.
These lock the properties that make that budget count: a topic returned to all
day is one block, redundant lines collapse, and the substantive topics come
first so truncation never eats the evening's real work.
"""

from rewisp import digest


def _row(ts, app, title, url, text):
    return (ts, app, title, url, text)


def test_same_page_across_hours_is_one_block():
    rows = [
        _row("2026-07-21 09:00:00", "Dia", "Auth design", "https://docs.local/auth", "line about tokens"),
        _row("2026-07-21 14:00:00", "Dia", "Auth design", "https://docs.local/auth", "line about sessions"),
        _row("2026-07-21 18:00:00", "Dia", "Auth design", "https://docs.local/auth", "line about refresh"),
    ]
    out = digest.compress_captures(rows)
    # one topic header for the page, all three lines under it
    assert out.count("### ") == 1
    for frag in ("tokens", "sessions", "refresh"):
        assert frag in out


def test_redundant_lines_collapse():
    rows = [
        _row("2026-07-21 09:00:00", "Mail", "Inbox", None, "quarterly report is ready"),
        _row("2026-07-21 09:05:00", "Mail", "Inbox", None, "quarterly report is ready"),  # dup
    ]
    out = digest.compress_captures(rows)
    assert out.lower().count("quarterly report is ready") == 1


def test_richer_topic_ranks_before_a_refreshed_noise_page():
    # A music tab refreshed 5x but carrying one line vs a doc visited twice with
    # lots of unique content — the doc must come first.
    rows = []
    for i in range(5):
        rows.append(_row(f"2026-07-21 10:0{i}:00", "Music", "Now Playing", None, "now playing same song"))
    rows.append(_row("2026-07-21 11:00:00", "Dia", "Spec", "https://x.local/spec",
                     "requirement one\nrequirement two\nrequirement three\nrequirement four"))
    rows.append(_row("2026-07-21 12:00:00", "Dia", "Spec", "https://x.local/spec",
                     "requirement five\nrequirement six"))
    out = digest.compress_captures(rows)
    spec_pos = out.find("requirement one")
    music_pos = out.find("now playing")
    assert spec_pos != -1 and music_pos != -1
    assert spec_pos < music_pos, "the content-rich spec must rank above the noise tab"


def test_time_span_shown_per_topic():
    rows = [
        _row("2026-07-21 09:15:00", "Dia", "Doc", "https://x.local/d", "alpha content here"),
        _row("2026-07-21 16:45:00", "Dia", "Doc", "https://x.local/d", "beta content here"),
    ]
    out = digest.compress_captures(rows)
    assert "09:15–16:45 UTC" in out


def test_empty_rows_safe():
    assert digest.compress_captures([]) == ""
