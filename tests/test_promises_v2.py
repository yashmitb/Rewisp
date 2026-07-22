"""Promise catching v2 — functional zoning, weak-commissive rejection, vague
temporal resolution, and fulfilment detection.

Grounded in the email commitment-extraction literature (Smart To-Do ACL 2020;
Carvalho & Cohen): commitments live in the active body zone, hedged/modal forms
are low-commitment, and a kept promise should stop nagging (Zeigarnik).
"""

from datetime import date

from rewisp import db, promises
from rewisp.promises import (_extract_due, _resolve_vague, detect, scan_and_store,
                             scan_fulfilment, strip_noise)


def hits(text, source="authored", bar=0.70):
    return [p for p in detect(text, source=source) if p["confidence"] >= bar]


# ── functional zoning ─────────────────────────────────────────────────────────

class TestZoning:
    def test_quoted_reply_line_dropped(self):
        assert "wrote" not in strip_noise("On Fri, Dana wrote:")
        assert strip_noise("> I'll send the report by Friday") == ""

    def test_forwarded_headers_dropped(self):
        block = "From: dana@x.com\nSent: Monday\nSubject: report\nreal body here"
        assert strip_noise(block) == "real body here"

    def test_signature_and_disclaimer_dropped(self):
        block = "I'll send it tomorrow\nSent from my iPhone\nCONFIDENTIAL: do not forward"
        out = strip_noise(block)
        assert "I'll send it tomorrow" in out
        assert "iPhone" not in out and "CONFIDENTIAL" not in out

    def test_body_line_with_content_survives(self):
        # A sign-off word mid-sentence is not a signature line and must survive.
        assert "thanks for the update" in strip_noise("thanks for the update, will do")

    def test_quoted_commitment_not_detected(self):
        # Dana's old quoted line must not become YOUR promise.
        text = "Thanks!\n> I'll send you the report by Friday"
        assert hits(text) == []

    def test_active_body_commitment_still_caught_with_quote_present(self):
        text = "I'll email the invoice tomorrow\n> earlier message from them"
        got = hits(text)
        assert got and got[0]["who"] == "me"


# ── weak commissives / modality (low commitment) ──────────────────────────────

class TestWeakCommissives:
    def test_try_hope_aim_rejected(self):
        for t in ["I'll try to send it tomorrow", "I hope to email Dana by Friday",
                  "I aim to finish the deck this week",
                  "I'll probably send the report tomorrow",
                  "I'll get to it at some point"]:
            assert not hits(t), t

    def test_firm_commitment_still_caught(self):
        got = hits("I'll send it tomorrow")
        assert got and got[0]["who"] == "me"


# ── vague temporal resolution ─────────────────────────────────────────────────

class TestTemporalResolver:
    REF = date(2026, 7, 21)   # a Tuesday

    def test_eod_cob_today_resolve_to_ref(self):
        for t in ["by EOD", "by COB", "end of day", "tonight"]:
            assert _resolve_vague(t, self.REF) == "2026-07-21", t

    def test_tomorrow(self):
        assert _resolve_vague("by tomorrow", self.REF) == "2026-07-22"

    def test_end_of_week_is_upcoming_friday(self):
        assert _resolve_vague("by EOW", self.REF) == "2026-07-24"        # Fri
        assert _resolve_vague("end of the week", self.REF) == "2026-07-24"

    def test_next_week_is_next_monday(self):
        assert _resolve_vague("next week", self.REF) == "2026-07-27"

    def test_next_month_first(self):
        assert _resolve_vague("next month", self.REF) == "2026-08-01"
        assert _resolve_vague("next month", date(2026, 12, 5)) == "2027-01-01"

    def test_no_anchor_returns_none(self):
        assert _resolve_vague("send the report", self.REF) is None

    def test_extract_due_falls_back_to_vague(self):
        # NSDataDetector doesn't resolve "EOW"; the resolver must fill it.
        assert _extract_due("send it by EOW", self.REF) == "2026-07-24"


# ── fulfilment detection ──────────────────────────────────────────────────────

class TestFulfilment:
    def _open_promise(self, conn, what, status="confirmed"):
        rid = db.insert_capture(conn, "Mail", None, None, "x")
        pid = db.add_promise(conn, rid, "me", what, "2026-07-24", 0.9)
        db.set_promise_status(conn, pid, status)
        return pid

    def test_completion_closes_matching_promise(self, conn):
        self._open_promise(conn, "send Dana the quarterly report")
        n = scan_fulfilment(conn, "just emailed Dana the quarterly report", app="Mail")
        assert n == 1
        assert db.promises_by_status(conn, ("confirmed",)) == []
        assert len(db.promises_by_status(conn, ("done",))) == 1

    def test_pending_promise_also_closes(self, conn):
        self._open_promise(conn, "book the flight to Boston", status="pending")
        assert scan_fulfilment(conn, "booked the flight to Boston", app="Notes") == 1

    def test_no_completion_cue_does_nothing(self, conn):
        self._open_promise(conn, "send Dana the report")
        # Mentions the action but nothing was completed.
        assert scan_fulfilment(conn, "still need to send Dana the report", app="Mail") == 0

    def test_unrelated_completion_leaves_promise_open(self, conn):
        self._open_promise(conn, "send Dana the quarterly report")
        assert scan_fulfilment(conn, "emailed Bob about lunch plans", app="Mail") == 0
        assert len(db.promises_by_status(conn, ("confirmed",))) == 1

    def test_blocked_surface_never_closes(self, conn):
        self._open_promise(conn, "send Dana the report")
        # An AI surface echoing "sent the report" must not close a real promise.
        assert scan_fulfilment(conn, "I sent Dana the report", app="Claude") == 0
        assert len(db.promises_by_status(conn, ("confirmed",))) == 1

    def test_needs_two_distinctive_words(self, conn):
        self._open_promise(conn, "send Dana the quarterly report")
        # Only one distinctive word ("report") overlaps — too weak to close.
        assert scan_fulfilment(conn, "finished the report", app="Mail") == 0

    def test_completion_matches_inside_a_long_real_capture(self, conn):
        # Regression: the body word-set must not be truncated (a real capture is
        # long, and the completion sentence can appear anywhere in it).
        self._open_promise(conn, "send Dana the quarterly report")
        body = ("Inbox  Sent  Drafts\n" + "filler subject line here\n" * 20 +
                "great, just emailed Dana the quarterly report a minute ago\n" +
                "footer nav home settings help\n" * 5)
        assert scan_fulfilment(conn, body, app="Mail") == 1
