"""Missed-promise sweeps: the digest sweep and the manual 'Update promises'
watermark sweep. The live detector caps at 2 promises per capture for precision;
the sweep catches the rest with the same bar, deduped — and the manual sweep is
idempotent so rapid re-clicks are cheap no-ops."""

from rewisp import db, promises

# One busy Notes capture with FOUR firm, deadline-bearing commitments. The live
# path stores at most 2; a sweep should recover all four.
BUSY = ("Notes\n"
        "I'll email Dana the report by Friday.\n"
        "I'll call the vendor tomorrow.\n"
        "I'll submit the tax form by EOD.\n"
        "I'll review the design draft tonight.")


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM promises").fetchone()[0]


def test_live_scan_is_capped_then_sweep_recovers_the_rest(conn):
    rid = db.insert_capture(conn, "Notes", "Scratch", None, BUSY)
    stored = conn.execute("SELECT ocr_text FROM captures WHERE id=?", (rid,)).fetchone()[0]
    promises.scan_and_store(conn, rid, stored, app="Notes")     # live: capped at 2
    assert _count(conn) == 2

    rows = [(rid, "Notes", None, stored)]
    added = promises.sweep_missed(conn, rows)                    # higher cap, same bar
    assert added >= 1
    assert _count(conn) == 4                                     # all four now present


def test_sweep_is_deduped_second_pass_adds_nothing(conn):
    rid = db.insert_capture(conn, "Notes", None, None, BUSY)
    stored = conn.execute("SELECT ocr_text FROM captures WHERE id=?", (rid,)).fetchone()[0]
    rows = [(rid, "Notes", None, stored)]
    promises.sweep_missed(conn, rows)
    n = _count(conn)
    assert promises.sweep_missed(conn, rows) == 0               # nothing new
    assert _count(conn) == n


def test_sweep_since_first_run_scans_recent_and_sets_watermark(conn):
    rid = db.insert_capture(conn, "Notes", None, None, BUSY)
    stored = conn.execute("SELECT ocr_text FROM captures WHERE id=?", (rid,)).fetchone()[0]
    conn.execute("UPDATE captures SET ocr_text=? WHERE id=?", (stored, rid))  # ensure redacted stored
    res = promises.sweep_since(conn)
    assert res["scanned"] >= 1 and res["added"] >= 1
    assert db.get_meta(conn, "promise_sweep_id") == str(rid)     # watermark advanced


def test_sweep_since_rapid_reclick_is_a_noop(conn):
    db.insert_capture(conn, "Notes", None, None, BUSY)
    promises.sweep_since(conn)                                   # first sweep
    again = promises.sweep_since(conn)                           # clicked again, nothing new
    assert again == {"added": 0, "scanned": 0}


def test_same_promise_across_many_captures_stored_once(conn):
    # The same commitment is visible on five captures through the day.
    line = "Notes\nI'll email Dana the quarterly report by Friday."
    rows = []
    for _ in range(5):
        rid = db.insert_capture(conn, "Notes", None, None, line)
        rows.append((rid, "Notes", None, line))
    promises.sweep_missed(conn, rows)
    assert _count(conn) == 1                                     # exactly one, no doubles


def test_open_promise_older_than_14_days_not_redoubled(conn):
    # An open (pending) promise made long ago; the sweep re-encounters the same
    # commitment now. It must not be added a second time.
    db.add_promise(conn, 1, "me", "I'll email Dana the quarterly report by Friday",
                   "2026-06-01", 0.9)
    conn.execute("UPDATE promises SET created_at = datetime('now','-40 days'), status='pending'")
    conn.commit()
    rid = db.insert_capture(conn, "Notes", None, None,
                            "Notes\nI'll email Dana the quarterly report by Friday.")
    stored = conn.execute("SELECT ocr_text FROM captures WHERE id=?", (rid,)).fetchone()[0]
    added = promises.sweep_missed(conn, [(rid, "Notes", None, stored)])
    assert added == 0 and _count(conn) == 1                     # still just the original


def test_sweep_since_picks_up_only_new_captures(conn):
    db.insert_capture(conn, "Notes", None, None, BUSY)
    promises.sweep_since(conn)                                   # watermark now past it
    n = _count(conn)
    # a NEW capture with a fresh commitment
    rid2 = db.insert_capture(conn, "Notes", None, None,
                             "Notes\nI'll ship the release notes by Monday.")
    res = promises.sweep_since(conn)
    assert res["scanned"] == 1                                   # only the new one
    assert _count(conn) == n + res["added"]
    assert db.get_meta(conn, "promise_sweep_id") == str(rid2)
