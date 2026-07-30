"""Numbers-over-time precision tuning from real data: the tracker was promoting
junk — 'Score: 0%' on unopened assignments and 'Step 1/2/3' wizard counters.
These lock the fixes without dropping legit metrics (GPA, weight, real scores)."""

from rewisp import db, numbers


def _labels(text):
    return [(d["label"], d["value"]) for d in numbers.detect(text)]


def test_wizard_step_counter_is_not_a_metric():
    assert numbers.detect("Step 1 of 5") == []
    assert numbers.detect("Step 2") == []


def test_fitness_steps_plural_still_tracked():
    assert _labels("Daily steps 8420") == [("steps", 8420.0)]


def test_zero_reading_rejected():
    assert numbers.detect("Score: 0%") == []
    assert numbers.detect("Score 0.0") == []
    assert numbers.detect("Weight 0 lbs") == []


def test_real_metrics_survive():
    assert _labels("Score: 96.1%") == [("score", 96.1)]
    assert _labels("GPA 3.89") == [("gpa", 3.89)]
    assert _labels("Weight 154.2 lbs") == [("weight", 154.2)]


def test_migration_purges_existing_junk(conn):
    # Old rows the previous detector stored.
    for v in (0.0, 0.0, 96.1):
        conn.execute("INSERT INTO series(key,label,value,unit,ts,wisp_id) "
                     "VALUES ('mylab::score','score',?,'%',datetime('now'),1)", (v,))
    conn.execute("INSERT INTO series(key,label,value,unit,ts,wisp_id) "
                 "VALUES ('gemini::step','step',2.0,'',datetime('now'),1)")
    conn.commit()
    # Force the one-time purge to run again.
    conn.execute("DELETE FROM meta WHERE key='series_junk_purged'")
    conn.commit()
    db._migrate(conn)
    rows = conn.execute("SELECT label, value FROM series ORDER BY value").fetchall()
    assert rows == [("score", 96.1)]          # zeros + step gone, real score kept
    # Idempotent: second run doesn't re-delete anything unexpected.
    db._migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 1
