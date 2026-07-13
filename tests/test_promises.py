"""Promise detection + storage/dedup."""

from rewisp import db, promises


class TestDetect:
    def test_detects_my_commitment(self):
        found = promises.detect("Sounds good. I'll send you the report tomorrow.")
        assert found and found[0]["who"] == "me"
        assert "send" in found[0]["what"].lower()

    def test_detects_owed_to_me(self):
        found = promises.detect("Hey, could you review the PR by Friday?")
        assert found and found[0]["who"] == "them"

    def test_deadline_raises_confidence(self):
        withdl = promises.detect("I'll submit the form by Monday")[0]
        without = promises.detect("I'll submit the form at some point")
        assert withdl["confidence"] >= 0.85
        # 'at some point' has no verb-deadline; still a commitment but lower conf
        if without:
            assert without[0]["confidence"] < withdl["confidence"]

    def test_ignores_non_commitment(self):
        assert promises.detect("The weather is nice and the sky is blue today.") == []

    def test_dedups_within_block(self):
        text = "I'll send the file. Also I'll send the file again later."
        found = promises.detect(text)
        assert len(found) == 1


class TestStore:
    def test_scan_stores_pending(self, conn):
        rid = db.insert_capture(conn, "Slack", None, None, "ok, I'll email the invoice by Friday")
        n = promises.scan_and_store(conn, rid, "ok, I'll email the invoice by Friday")
        assert n == 1
        p = db.promises_by_status(conn, ("pending",))
        assert len(p) == 1 and p[0]["who"] == "me"

    def test_dedup_across_captures(self, conn):
        rid = db.insert_capture(conn, "Slack", None, None, "x")
        promises.scan_and_store(conn, rid, "I'll email the invoice by Friday")
        promises.scan_and_store(conn, rid, "I'll email the invoice by Friday")   # same
        assert len(db.promises_by_status(conn, ("pending",))) == 1

    def test_status_transitions_and_due(self, conn):
        rid = db.insert_capture(conn, "Mail", None, None, "x")
        pid = db.add_promise(conn, rid, "me", "reply to Dana", "2020-01-01", 0.9)
        db.set_promise_status(conn, pid, "confirmed")
        assert len(db.due_promises(conn)) == 1          # past due date
        db.set_promise_status(conn, pid, "done")
        assert db.promises_by_status(conn, ("confirmed",)) == []

    def test_cascade_delete_removes_promises(self, conn):
        rid = db.insert_capture(conn, "Mail", None, None, "x")
        db.add_promise(conn, rid, "me", "do thing", None, 0.9)
        db.delete_captures(conn, [rid])
        assert db.promises_by_status(conn, ("pending", "confirmed")) == []
