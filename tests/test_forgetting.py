"""The Forgetting Model: event mining, signature fitting, rescue, auto-pin."""

import numpy as np
import pytest

from rewisp import db, embed, forgetting


def _q(conn, text, vec, ago):
    conn.execute("INSERT INTO queries (text, ts, embedding) VALUES (?, datetime('now', ?), ?)",
                 (text, ago, vec.tobytes()))
    conn.commit()


def _vec(seed):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(embed.DIM).astype(np.float32)
    return v / np.linalg.norm(v)


class TestCategorize:
    def test_bins(self):
        assert forgetting.categorize("who was that recruiter from google") == "name"
        assert forgetting.categorize("when is the fafsa deadline") == "date"
        assert forgetting.categorize("where was that pasta restaurant") == "place"
        assert forgetting.categorize("link to the github repo") == "link"
        assert forgetting.categorize("how much was the contractor quote") == "number"
        assert forgetting.categorize("summarize my day") == "other"


class TestEvents:
    def test_rephrase_within_minutes(self, conn):
        v = _vec(1)
        _q(conn, "that pasta place brooklyn", v, "-3 minutes")
        _q(conn, "pasta restaurant in brooklyn", v, "-2 minutes")   # same vec = similar
        ev = forgetting.forgetting_events(conn)
        assert any(e["kind"] == "rephrase" for e in ev)

    def test_reask_days_later(self, conn):
        v = _vec(2)
        _q(conn, "wifi password for the office", v, "-6 days")
        _q(conn, "office wifi password", v, "-1 hours")
        ev = forgetting.forgetting_events(conn)
        reasks = [e for e in ev if e["kind"] == "re-ask"]
        assert reasks and 5.5 <= reasks[0]["gap_days"] <= 6.5

    def test_unrelated_queries_no_event(self, conn):
        _q(conn, "what did i do today", _vec(3), "-3 days")
        _q(conn, "how has my weight moved", _vec(4), "-1 hours")
        assert forgetting.forgetting_events(conn) == []


class TestSignature:
    def test_priors_without_data(self, conn):
        sig = forgetting.signature(conn)
        assert sig["name"]["stability_days"] == forgetting.PRIORS["name"]
        assert sig["number"]["stability_days"] == forgetting.PRIORS["number"]

    def test_observed_gaps_pull_stability(self, conn):
        v = _vec(5)
        # name-question re-asked after 2 days, twice -> stability drops below prior
        _q(conn, "who was the recruiter", v, "-9 days")
        _q(conn, "who was that recruiter", v, "-7 days")
        sig = forgetting.signature(conn)
        assert sig["name"]["stability_days"] < forgetting.PRIORS["name"]
        assert sig["name"]["observed"] >= 1


class TestRescue:
    def _wisp(self, conn, text, ago, pkey="site::once"):
        rid = conn.execute(
            "INSERT INTO captures (ts, app, window_title, url, ocr_text, page_key) "
            "VALUES (datetime('now', ?), 'Dia', NULL, NULL, ?, ?)",
            (ago, text, pkey)).lastrowid
        conn.commit()
        return rid

    def test_fading_wisp_selected_once(self, conn):
        rid = self._wisp(conn, "Contractor quote total $2,400 call Mike 415-555-0100 "
                               "for the bathroom remodel project estimate", "-5 days")
        fading = forgetting.about_to_fade(conn, limit=3)
        assert any(f["wisp_id"] == rid for f in fading)
        forgetting.mark_rescued(conn, [rid])
        assert not any(f["wisp_id"] == rid for f in forgetting.about_to_fade(conn))

    def test_fresh_and_ancient_not_selected(self, conn):
        a = self._wisp(conn, "Quote number 999 dollars from the plumber visit", "-1 days")
        b = self._wisp(conn, "Quote number 888 dollars from the electrician", "-40 days")
        ids = {f["wisp_id"] for f in forgetting.about_to_fade(conn, limit=5)}
        assert a not in ids and b not in ids

    def test_recalled_wisps_not_rescued(self, conn):
        rid = self._wisp(conn, "Invoice total $500 due to Dana Smith accounting", "-5 days")
        conn.execute("UPDATE captures SET recall_count=2 WHERE id=?", (rid,))
        conn.commit()
        assert not any(f["wisp_id"] == rid for f in forgetting.about_to_fade(conn))


class TestAutoPin:
    def test_third_ask_pins(self, conn, monkeypatch):
        v = _vec(7)
        monkeypatch.setattr(forgetting, "_real_embed", None, raising=False)
        import unittest.mock as mock
        with mock.patch("rewisp.embed.embed", return_value=v.tobytes()):
            _q(conn, "office wifi password", v, "-10 days")
            _q(conn, "wifi password office", v, "-5 days")
            _q(conn, "what is the office wifi", v, "-1 minutes")
            assert forgetting.maybe_pin(conn, "what is the office wifi", "hunter2net") is True
            hit = forgetting.pinned_answer(conn, "office wifi?")
            assert hit and hit["answer"] == "hunter2net" and hit["model"] == "Pinned"
            # second pin of the same fact refused
            assert forgetting.maybe_pin(conn, "office wifi password", "hunter2net") is False

    def test_not_found_answers_never_pin(self, conn):
        assert forgetting.maybe_pin(conn, "anything", "Not found in your memory.") is False

    def test_two_asks_not_enough(self, conn):
        v = _vec(8)
        import unittest.mock as mock
        with mock.patch("rewisp.embed.embed", return_value=v.tobytes()):
            _q(conn, "gym door code", v, "-3 days")
            _q(conn, "door code for the gym", v, "-1 minutes")
            assert forgetting.maybe_pin(conn, "door code for the gym", "4821") is False


class TestUnpinnable:
    def test_time_dependent_questions_never_pin(self, conn):
        for q in ["what did i do yesterday?", "summarize my day",
                  "what changed on this page", "what was i working on today"]:
            assert forgetting.maybe_pin(conn, q, "some answer") is False, q

    def test_time_dependent_lookup_bypasses_pins(self, conn):
        conn.execute("INSERT INTO pinned (question, answer, embedding, created_at) "
                     "VALUES ('what did i do yesterday?', 'stale', x'00', datetime('now'))")
        conn.commit()
        assert forgetting.pinned_answer(conn, "what did i do yesterday?") is None


class TestFSRSCurve:
    """FSRS-6 power-law recall curve: R(t) = (1 + F·t/h)^decay, F set so
    R(h) == 0.5. The power tail is the point — heavier than exponential, matching
    the FSRS finding that real memory retains more at long delays than exp
    predicts."""

    def test_half_life_means_half_life(self):
        from rewisp import forgetting
        # The half-life keeps its meaning at ANY decay: R(h) == 0.5 by
        # construction, so every prior/label/threshold in half-life terms holds.
        for d in (-0.2, -0.5, -0.8):
            assert abs(forgetting.recall_probability(5.0, 5.0, d) - 0.5) < 1e-9

    def test_curve_is_monotonic_and_bounded(self):
        from rewisp import forgetting
        assert forgetting.recall_probability(0.0, 5.0) == 1.0
        seq = [forgetting.recall_probability(t, 5.0) for t in range(0, 40, 2)]
        assert all(a >= b for a, b in zip(seq, seq[1:]))     # never increases
        assert all(0.0 <= p <= 1.0 for p in seq)

    def test_power_tail_beats_exponential_at_long_delay(self):
        from rewisp import forgetting
        # At 4 half-lives the power law must retain MORE than a pure exponential
        # (2^-4 = 0.0625) — that heavier tail is the FSRS improvement.
        p = forgetting.recall_probability(20.0, 5.0)
        assert p > 0.0625

    def test_steeper_decay_is_sharper_past_the_half_life(self):
        from rewisp import forgetting
        gentle = forgetting.recall_probability(10.0, 5.0, -0.2)
        steep = forgetting.recall_probability(10.0, 5.0, -0.8)
        assert steep < gentle, "more-negative decay must fall faster past h"
        # ...and be MORE confident before it — the sharp-edge shape.
        assert (forgetting.recall_probability(2.0, 5.0, -0.8)
                > forgetting.recall_probability(2.0, 5.0, -0.2))

    def test_decay_needs_evidence_before_it_moves(self):
        from rewisp import forgetting
        assert forgetting._fit_decay([]) == forgetting.DEFAULT_DECAY
        assert forgetting._fit_decay([4.0, 5.0]) == forgetting.DEFAULT_DECAY

    def test_tight_gaps_imply_a_sharper_edge(self):
        from rewisp import forgetting
        tight = forgetting._fit_decay([5.0, 5.1, 4.9, 5.0, 5.05])
        spread = forgetting._fit_decay([1.0, 9.0, 3.0, 14.0, 6.0])
        assert tight < spread, "tight cluster -> steeper (more-negative) decay"

    def test_decay_is_clamped(self):
        from rewisp import forgetting
        d = forgetting._fit_decay([5.0] * 6)     # identical gaps -> cv ~0
        assert forgetting._MIN_DECAY <= d <= forgetting._MAX_DECAY

    def test_extreme_inputs_do_not_raise(self):
        from rewisp import forgetting
        assert forgetting.recall_probability(0.0, 5.0) == 1.0
        assert 0.0 <= forgetting.recall_probability(1e6, 0.1, 2.0) <= 1.0
        assert 0.0 <= forgetting.recall_probability(-5.0, -1.0, -1.0) <= 1.0
