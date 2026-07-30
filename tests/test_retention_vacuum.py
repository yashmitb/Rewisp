"""Retention must reclaim disk, not just delete rows. SQLite parks freed pages in
the file, so without a VACUUM an always-on memory app's database only ever grows —
even as months age out. Real data: 259 MB in 23 days."""

import os
import sqlite3

from rewisp import db, config


def _fresh(path):
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA)
    db._migrate(c)
    return c


def test_retention_deletes_old_and_shrinks_file(tmp_path, monkeypatch):
    p = tmp_path / "r.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "VACUUM_MIN_DELETED", 100)
    c = _fresh(p)
    # 600 fat captures well past both the retention window and the 2x hard cap.
    for _ in range(600):
        c.execute("INSERT INTO captures(ts, app, ocr_text) "
                  "VALUES (datetime('now','-400 days'), 'A', ?)", ("x" * 3000,))
    c.execute("INSERT INTO captures(ts, app, ocr_text) VALUES (datetime('now'), 'A', 'keep me')")
    c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    size_before = os.path.getsize(p)

    deleted, _ = db.run_retention(c)

    assert deleted >= 500
    assert c.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 1   # recent row kept
    size_after = os.path.getsize(p)
    assert size_after < size_before, f"file did not shrink: {size_before} -> {size_after}"
    c.close()


def test_retention_skips_vacuum_when_little_freed(tmp_path, monkeypatch):
    # Below the threshold, no expensive VACUUM — just the cheap WAL checkpoint.
    p = tmp_path / "r.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "VACUUM_MIN_DELETED", 500)
    c = _fresh(p)
    for _ in range(10):
        c.execute("INSERT INTO captures(ts, app, ocr_text) "
                  "VALUES (datetime('now','-400 days'), 'A', 'old')")
    c.commit()
    deleted, _ = db.run_retention(c)   # 10 < 500 -> no VACUUM, must not error
    assert deleted == 10
    c.close()
