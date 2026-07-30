"""Time-phrase parsing. Every real query in the logs is time-based ("what did I
do today/yesterday/this week"), so a phrase that parses to nothing silently
answers the wrong window. These lock the newly-added relative windows and guard
the originals from regressing. A fixed UTC `now` keeps them deterministic."""

from datetime import datetime, timezone

from rewisp import timeparse

# Thursday 2026-07-30 20:00 UTC — mid-week so weekend points at the past weekend.
NOW = datetime(2026, 7, 30, 20, 0, 0, tzinfo=timezone.utc)


def p(phrase):
    return timeparse.parse(phrase, now=NOW)


def test_rolling_days_window_ends_now():
    s, u, _ = p("past 3 days")
    assert s == "2026-07-27 20:00:00" and u == "2026-07-30 20:00:00"


def test_rolling_hours_and_minutes():
    assert p("last 2 hours")[0] == "2026-07-30 18:00:00"
    assert p("last 30 minutes")[0] == "2026-07-30 19:30:00"
    assert p("past hour")[0] == "2026-07-30 19:00:00"


def test_qty_words():
    assert p("last couple weeks")[0] == "2026-07-16 20:00:00"   # 14 days back
    assert p("past few days")[0] == "2026-07-27 20:00:00"       # 3 days back


def test_this_month_to_date():
    s, u, _ = p("this month")
    assert s == "2026-07-01 00:00:00" and u is None


def test_last_month_bounds():
    s, u, _ = p("last month")
    assert s.startswith("2026-06-01") and u.startswith("2026-06-30")


def test_weekend_windows():
    s, u, _ = p("this weekend")           # the weekend before Thu 07-30 = Sat 25/Sun 26
    assert s.startswith("2026-07-25") and u.startswith("2026-07-26")
    s2, _, _ = p("last weekend")
    assert s2.startswith("2026-07-18")


def test_tonight_and_last_night_parse():
    assert p("tonight")[0] is not None
    ln_s, ln_u, _ = p("last night")
    assert ln_s.startswith("2026-07-29") and ln_u.startswith("2026-07-30")


def test_originals_still_work():
    assert p("today")[0].startswith("2026-07-30")
    assert p("yesterday")[0].startswith("2026-07-29")
    assert p("this week")[0].startswith("2026-07-27")          # Monday of NOW's week
    assert p("last week")[0].startswith("2026-07-20")
    assert p("this morning")[0] is not None


def test_weekend_not_swallowed_by_week():
    # "this weekend" must NOT match the "this week" rule (would give the wrong span).
    s, u, _ = p("what did I do this weekend")
    assert s.startswith("2026-07-25")                          # weekend, not week-start


def test_unparseable_returns_none():
    assert p("what is my wifi password") == (None, None, "what is my wifi password")
