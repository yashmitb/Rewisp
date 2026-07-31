"""The day map: layout, filtering, labels, and reinstatement.

The label tests carry most of the weight here. Window titles are the messiest
input in the whole feature — macOS elides them to whatever width the window
happened to be, browsers staple unread counters and profile names on, and the
site name gets appended — so nearly every bug in this module has been a label
bug, and each of these locks one of them down.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from rewisp import constellation


def _day():
    """A fixed local day, used as the reference for every timestamp below."""
    return datetime.now().astimezone().replace(
        hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)


def _utc(day, minutes_offset):
    """UTC string for `minutes_offset` minutes after local noon on `day` — stays
    comfortably inside the local day whatever timezone the suite runs in."""
    return (day + timedelta(minutes=minutes_offset)).astimezone(
        timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _vec(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(512).astype(np.float32)
    return (v / np.linalg.norm(v)).tobytes()


def _cap(conn, day, offset, app, title, page_key, url=None, seed=1, text="hello there"):
    conn.execute(
        "INSERT INTO captures (ts, app, window_title, url, ocr_text, page_key, embedding) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (_utc(day, offset), app, title, url, text, page_key, _vec(seed)))
    conn.commit()


class TestLabels:
    def test_prefers_the_complete_title_over_the_elided_one(self):
        # macOS returns the title at whatever width the window had, so the SAME
        # page yields both of these. Ranking by frequency picked the elided one,
        # which is how every movie on the map ended up called "Srimanthudu…".
        titles = ["Delta: (50) Srimanthudu…"] * 9 + [
            "(50) Srimanthudu Telugu Full Movie | Mahesh Babu - YouTube"]
        assert constellation._label_for("https://youtube.com/watch", titles, "Dia") \
            == "Srimanthudu Telugu Full Movie"

    def test_site_suffix_never_eats_content(self):
        # " - 7.2)" is a page number, not a site name. The first cut at this
        # regex turned this title into "Chapter 7 TEST (7.1".
        assert constellation._label_for("app::x", ["Chapter 7 TEST (7.1 - 7.2)"], "Dia") \
            == "Chapter 7 TEST (7.1 - 7.2)"

    def test_unread_counter_stripped_even_behind_a_prefix(self):
        assert constellation._label_for("app::x", ["Delta: (50) Your Orders"], "Dia") \
            == "Delta: Your Orders"

    def test_long_titles_keep_the_name_and_drop_the_credits(self):
        long = ("Some Very Long Film Title Indeed | Actor One | Actor Two "
                "| Actor Three | Latest Movies")
        assert constellation._label_for("https://y.com/watch", [long], "Dia") \
            == "Some Very Long Film Title Indeed"

    def test_falls_back_to_the_url_when_there_is_no_title(self):
        assert constellation._label_for("https://www.github.com/yashmitb/Rewisp", [], "Dia") \
            == "github.com/Rewisp"

    def test_ellipsize_cuts_on_a_word_boundary(self):
        out = constellation._ellipsize("alpha beta gamma delta epsilon zeta", 20)
        assert out.endswith("…") and "gamm" not in out.replace("gamma", "")

    def test_shared_profile_prefix_is_inferred_and_stripped(self):
        # "Personal:" on three unrelated places is a browser space, not content.
        nodes = [{"label": "Personal: Amazon"}, {"label": "Personal: YouTube"},
                 {"label": "Personal: GitHub"}, {"label": "Chapter 7 TEST"}]
        constellation._strip_shared_prefixes(nodes)
        assert [n["label"] for n in nodes] == ["Amazon", "YouTube", "GitHub", "Chapter 7 TEST"]

    def test_a_prefix_on_one_place_is_left_alone(self):
        # Could easily be real content ("Rewisp: build notes") — don't touch it.
        nodes = [{"label": "Rewisp: build notes"}, {"label": "YouTube"}]
        constellation._strip_shared_prefixes(nodes)
        assert nodes[0]["label"] == "Rewisp: build notes"


class TestDayMap:
    def test_only_places_that_held_you_become_nodes(self, conn):
        day = _day()
        # Two real places (10 min each), one drive-by that must not earn a dot.
        for i in range(3):
            _cap(conn, day, i * 5, "Dia", "Long Read", "p::read", seed=1)
        for i in range(3):
            _cap(conn, day, 20 + i * 5, "Dia", "Docs Page", "p::docs", seed=2)
        _cap(conn, day, 40, "Dia", "Redirect", "p::blip", seed=3)
        m = constellation.day_map(conn, day)
        keys = {n["page_key"] for n in m["nodes"]}
        assert "p::read" in keys and "p::docs" in keys
        assert "p::blip" not in keys          # under MIN_DWELL_SECONDS

    def test_new_tab_is_not_a_place(self, conn):
        day = _day()
        for i in range(4):
            _cap(conn, day, i * 5, "Dia", ", New Tab,", "p::newtab", seed=1)
        for i in range(4):
            _cap(conn, day, 30 + i * 5, "Dia", "Real Page", "p::real", seed=2)
        m = constellation.day_map(conn, day)
        assert {n["page_key"] for n in m["nodes"]} == {"p::real"}

    def test_edges_need_two_crossings_and_carry_weight(self, conn):
        day = _day()
        # Bounce A<->B repeatedly; touch C once so its edge stays below the bar.
        for i in range(6):
            _cap(conn, day, i * 6, "Dia", "Alpha", "p::a", seed=1)
            _cap(conn, day, i * 6 + 3, "Dia", "Beta", "p::b", seed=2)
        for i in range(3):
            _cap(conn, day, 60 + i * 5, "Dia", "Gamma", "p::c", seed=3)
        m = constellation.day_map(conn, day)
        by_key = {n["id"]: n["page_key"] for n in m["nodes"]}
        pairs = {frozenset((by_key[e["a"]], by_key[e["b"]])): e["weight"] for e in m["edges"]}
        assert pairs[frozenset(("p::a", "p::b"))] >= 10
        assert frozenset(("p::b", "p::c")) not in pairs      # crossed once only

    def test_trace_follows_time_and_skips_repeats(self, conn):
        day = _day()
        for i in range(3):
            _cap(conn, day, i * 5, "Dia", "Alpha", "p::a", seed=1)
        for i in range(3):
            _cap(conn, day, 20 + i * 5, "Dia", "Beta", "p::b", seed=2)
        m = constellation.day_map(conn, day)
        by_key = {n["id"]: n["page_key"] for n in m["nodes"]}
        walked = [by_key[s["node"]] for s in m["trace"]]
        assert walked == ["p::a", "p::b"]      # one step per ARRIVAL, not per capture

    def test_coordinates_are_normalised_and_deterministic(self, conn):
        day = _day()
        for k in range(4):
            for i in range(3):
                _cap(conn, day, k * 20 + i * 5, "Dia", f"Page {k}", f"p::{k}", seed=k + 1)
        first = constellation.day_map(conn, day)
        second = constellation.day_map(conn, day)
        for n in first["nodes"]:
            assert -1.001 <= n["x"] <= 1.001 and -1.001 <= n["y"] <= 1.001
        # The map is a place the user learns. A layout that reshuffles between
        # two refreshes of the same day is worse than no layout at all.
        assert [(n["x"], n["y"]) for n in first["nodes"]] == \
               [(n["x"], n["y"]) for n in second["nodes"]]

    def test_an_empty_day_is_an_empty_map_not_a_crash(self, conn):
        m = constellation.day_map(conn, _day())
        assert m["nodes"] == [] and m["edges"] == [] and m["totals"]["captures"] == 0

    def test_uses_the_local_day_not_the_utc_day(self, conn):
        # The digest learned this one: timestamps are stored UTC, so slicing on
        # date(ts) chops the evening off the user's day in a western timezone and
        # staples it onto the next one.
        day = _day()
        _cap(conn, day, 0, "Dia", "Midday", "p::mid", seed=1)
        for i in range(3):
            _cap(conn, day, 600 + i * 5, "Dia", "Late Night", "p::late", seed=2)  # 22:00 local
        m = constellation.day_map(conn, day)
        assert "p::late" in {n["page_key"] for n in m["nodes"]}


class TestReinstate:
    def test_rebuilds_the_moment_with_both_neighbours(self, conn):
        day = _day()
        _cap(conn, day, 0, "Mail", "Inbox", "p::mail", seed=1, text="from dana about friday")
        for i in range(3):
            _cap(conn, day, 5 + i * 5, "Dia", "The Docs", "p::docs", seed=2,
                 text="the rate limit is 4000 requests per hour for this endpoint")
        _cap(conn, day, 30, "Terminal", "zsh", "p::term", seed=3, text="running the tests now")
        card = constellation.reinstate(conn, "p::docs")
        assert card["label"] == "The Docs"
        assert card["before"]["label"] == "Inbox"
        assert card["after"]["label"] == "zsh"
        assert any("rate limit" in l for l in card["lines"])

    def test_a_distant_neighbour_is_not_context(self, conn):
        day = _day()
        _cap(conn, day, 0, "Mail", "Yesterday's Thing", "p::mail", seed=1)
        for i in range(3):
            _cap(conn, day, 200 + i * 5, "Dia", "The Docs", "p::docs", seed=2)
        card = constellation.reinstate(conn, "p::docs")
        assert card["before"] is None          # 200 minutes earlier is a different day-part

    def test_unknown_page_returns_nothing(self, conn):
        assert constellation.reinstate(conn, "p::never") is None
