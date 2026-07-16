"""Promise detection — precision-first regression suite.

The LIVE_GARBAGE cases are real false positives captured in daily use (v0.8.1
stored 19 promises; 18 were dismissed as junk). Every one must stay dead.
"""

from rewisp import db, promises
from rewisp.promises import detect, scan_and_store, source_class


def hits(text, source="authored", bar=0.70):
    return [p for p in detect(text, source=source) if p["confidence"] >= bar]


# ── source gating ─────────────────────────────────────────────────────────────

class TestSourceGating:
    def test_ai_and_ide_surfaces_blocked(self):
        for app in ["Claude", "Gemini", "Antigravity IDE", "Terminal", "Cursor",
                    "Visual Studio Code", "Dock", "Finder", "Rewisp"]:
            assert source_class(app, None) == "blocked", app

    def test_authored_surfaces(self):
        for app in ["Notes", "Mail", "Slack", "Discord", "Obsidian"]:
            assert source_class(app, None) == "authored", app

    def test_browser_url_decides(self):
        assert source_class("Dia", "https://claude.ai/chat/abc") == "blocked"
        assert source_class("Dia", "https://chatgpt.com/c/1") == "blocked"
        assert source_class("Dia", "https://mail.google.com/mail/u/0") == "authored"
        assert source_class("Dia", "https://discord.com/channels/1/2") == "authored"
        assert source_class("Dia", "https://example.com/article") == "strict"

    def test_blocked_surface_stores_nothing(self, conn):
        rid = db.insert_capture(conn, "Claude", None, None, "x")
        n = scan_and_store(conn, rid, "I'll send the report by Friday", app="Claude")
        assert n == 0


# ── real false positives from the live DB — every one must stay rejected ────

LIVE_GARBAGE = [
    "I'll write the guide",                                        # Claude output
    "let me confirm the current state of",                         # Claude output, clipped
    "Let me verify assets + the auto-update link",                 # Claude output
    "I'll fix real friction instead of",                           # Claude output, clipped
    "I can run /design-review on the live app for a",              # Claude output
    "I want to do is I want to wait to make it so that if I message something from",  # dictation
    "I want to do is type an email to the person asking if I can",  # dictation
    "I want to do is type an email to the person asking if l can",  # dictation, OCR l/I
    "Get instant discounts on hotels today",                       # ad copy
    "Draft my weekly update from this week's calls",               # AI-product marketing
    "Draft my weekly update trom this week's calls",               # same, OCR variant
    "Update my Linear tickets with this week's progress",          # AI-product marketing
    "have to update Namecheap once more",                          # idle prose fragment
    "need to complete the refresher course and pass the test",     # course copy
    "remember to scan the paper where you showed your work for each question and uplo",  # instructions, clipped
    "I'll definitely reach out to him",                            # article/podcast quote
]


class TestLiveGarbageStaysDead:
    def test_all_live_false_positives_rejected_on_strict(self):
        # These appeared on web pages / AI surfaces. AI surfaces are blocked
        # outright; anything similar on a generic page must miss the strict bar.
        survivors = [(t, hits(t, source="strict", bar=0.80)) for t in LIVE_GARBAGE
                     if hits(t, source="strict", bar=0.80)]
        assert not survivors, survivors

    def test_worst_offenders_rejected_even_on_authored(self):
        for t in ["Get instant discounts on hotels today",
                  "I want to do is type an email to the person asking if l can",
                  "let me confirm the current state of",
                  "I'll fix real friction instead of",
                  "remember to scan the paper where you showed your work for each question and uplo"]:
            assert not hits(t, source="authored"), t


# ── real commitments must still be caught (on authored surfaces) ─────────────

class TestRealPromisesCaught:
    def test_first_person_with_deadline(self):
        got = hits("Sounds good. I'll send you the report tomorrow.")
        assert got and got[0]["who"] == "me" and got[0]["due"]

    def test_first_person_no_deadline_authored(self):
        got = hits("ok I will send mavi a doc pic")
        assert got and got[0]["who"] == "me"

    def test_imperative_todos_with_time(self):
        for t in ["email manvi by the end of today",
                  "Send John an invite by the end of the week",
                  "call dona today", "ping the team on Monday"]:
            assert hits(t), t

    def test_broad_first_person_openers(self):
        for t in ["I need to submit the form by Friday", "gotta pay rent today",
                  "remember to book the flight this week",
                  "I have to finish the deck tonight"]:
            assert hits(t), t

    def test_request_to_you_with_deadline(self):
        got = hits("Hey, could you review the PR by Friday?".replace("?", ""))
        assert got and got[0]["who"] == "them"

    def test_strict_surface_needs_deadline(self):
        # On a random web page a bare "I'll send it" shouldn't fire…
        assert not hits("I will send mavi a doc pic", source="strict", bar=0.80)
        # …but a dated commitment should.
        assert hits("I'll send Dana the report by Friday", source="strict", bar=0.80)

    def test_bare_imperative_without_time_ignored(self):
        assert not hits("Send the file")     # UI button
        assert not hits("Reply All")

    def test_dedups_within_block(self):
        text = "I'll send the file by Friday. Also I'll send the file by Friday again."
        assert len(hits(text)) == 1


# ── hard rejects ──────────────────────────────────────────────────────────────

class TestHardRejects:
    def test_questions(self):
        assert not hits("will you send the report by Friday?")
        assert not hits("can you send it tomorrow?")

    def test_negation(self):
        assert not hits("I won't send the report by Friday")

    def test_hedges(self):
        assert not hits("maybe I'll email manvi tomorrow")
        assert not hits("I was going to send the report by Friday")

    def test_ad_speak(self):
        assert not hits("Subscribe today to get the best price on flights")
        assert not hits("Sign up by Friday for the free trial")

    def test_clipped_tails(self):
        assert not hits("I'll email the report to")
        assert not hits("I need to review the state of")


# ── store side ────────────────────────────────────────────────────────────────

class TestStore:
    def test_scan_stores_pending(self, conn):
        rid = db.insert_capture(conn, "Slack", None, None, "x")
        n = scan_and_store(conn, rid, "ok, I'll email the invoice by Friday", app="Slack")
        assert n == 1
        p = db.promises_by_status(conn, ("pending",))
        assert len(p) == 1 and p[0]["who"] == "me"

    def test_deadline_less_kept_on_authored_only(self, conn):
        rid = db.insert_capture(conn, "Notes", None, None, "x")
        assert scan_and_store(conn, rid, "ok I will send mavi a doc pic", app="Notes") == 1
        rid2 = db.insert_capture(conn, "Dia", None, None, "x")
        assert scan_and_store(conn, rid2, "ok I will send kavi a doc pic",
                              app="Dia", url="https://example.com") == 0

    def test_ocr_variant_not_stored_twice(self, conn):
        rid = db.insert_capture(conn, "Notes", None, None, "x")
        a = scan_and_store(conn, rid, "I'll send Dana the report by Friday", app="Notes")
        b = scan_and_store(conn, rid, "I'll send Dana the reporl by Friday", app="Notes")
        assert a == 1 and b == 0

    def test_max_two_per_capture(self, conn):
        rid = db.insert_capture(conn, "Notes", None, None, "x")
        text = ("I'll email Alice the notes by Monday.\n"
                "I'll call Bob about the quote by Tuesday.\n"
                "I'll send Carol the draft by Wednesday.")
        assert scan_and_store(conn, rid, text, app="Notes") == 2

    def test_status_transitions_and_due(self, conn):
        rid = db.insert_capture(conn, "Mail", None, None, "x")
        pid = db.add_promise(conn, rid, "me", "reply to Dana", "2020-01-01", 0.9)
        db.set_promise_status(conn, pid, "confirmed")
        assert len(db.due_promises(conn)) == 1
        db.set_promise_status(conn, pid, "done")
        assert db.promises_by_status(conn, ("confirmed",)) == []

    def test_cascade_delete_removes_promises(self, conn):
        rid = db.insert_capture(conn, "Mail", None, None, "x")
        db.add_promise(conn, rid, "me", "do thing", None, 0.9)
        db.delete_captures(conn, [rid])
        assert db.promises_by_status(conn, ("pending", "confirmed")) == []

    def test_weak_openers_need_time_anchor(self):
        assert hits("need to email the professor tonight")
        assert not hits("need to complete the refresher course and pass the test")
        assert not hits("have to update Namecheap once more")
