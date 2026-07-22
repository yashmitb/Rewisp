"""Numbers-over-time: unit consistency + robust outlier rejection."""

from rewisp import db, numbers


def _series_row(conn, key, label, value, unit, mins_ago):
    conn.execute(
        "INSERT INTO series (key, label, value, unit, ts, wisp_id) "
        "VALUES (?, ?, ?, ?, datetime('now', ?), 1)",
        (key, label, value, unit, f"-{mins_ago} minutes"))
    conn.commit()


# ── unit consistency ─────────────────────────────────────────────────────────

def test_conflicting_unit_is_rejected(conn):
    rid = db.insert_capture(conn, "Health", None, None, "x")
    numbers.scan_and_store(conn, rid, "health::body", "Weight 154 lbs")
    # A later reading that OCR paired with a '%' must not join the lbs series.
    numbers.scan_and_store(conn, rid, "health::body", "Weight 30 %")
    units = [r[0] for r in conn.execute(
        "SELECT unit FROM series WHERE key LIKE 'health::body%'")]
    assert units == ["lbs"], units


def test_unitless_reading_still_accepted(conn):
    rid = db.insert_capture(conn, "Health", None, None, "x")
    numbers.scan_and_store(conn, rid, "health::body", "Weight 154 lbs")
    numbers.scan_and_store(conn, rid, "health::body", "Weight 152")   # OCR dropped the unit
    vals = sorted(r[0] for r in conn.execute(
        "SELECT value FROM series WHERE key LIKE 'health::body%'"))
    assert vals == [152.0, 154.0]


def test_established_unit_helper(conn):
    _series_row(conn, "k::weight", "weight", 154, "lbs", 30)
    _series_row(conn, "k::weight", "weight", 155, "lbs", 20)
    _series_row(conn, "k::weight", "weight", 156, "", 10)   # one unitless
    assert numbers._established_unit(conn, "k::weight") == "lbs"
    assert numbers._established_unit(conn, "k::none") == ""


# ── outlier rejection ────────────────────────────────────────────────────────

def test_outlier_dropped_from_series(conn):
    # A realistic weight series with one OCR-garbled reading (9155 for 155).
    for i, (v, mins) in enumerate([(154, 50), (155, 40), (9155, 30), (153, 20), (154, 10)]):
        _series_row(conn, "k::weight", "weight", v, "lbs", mins)
    act = numbers.active_series(conn)
    assert len(act) == 1
    pts = act[0]["points"]
    assert 9155 not in pts, pts
    assert act[0]["current"] == 154        # latest kept reading, not the garbage
    assert max(pts) < 200


def test_small_series_keeps_all(conn):
    # Fewer than 4 points: not enough to judge an outlier, keep everything.
    for v, mins in [(10, 30), (500, 20), (12, 10)]:
        _series_row(conn, "k::score", "score", v, "", mins)
    act = numbers.active_series(conn)
    assert act and 500 in act[0]["points"]


def test_drop_outliers_never_empties():
    pts = [{"value": 5.0}, {"value": 5.0}, {"value": 5.0}, {"value": 5.0}]
    assert numbers._drop_outliers(pts) == pts   # mad==0 path, keep all
