"""Numbers Over Time — detection, promotion to a series, lookup, cascade."""

from rewisp import db, numbers


class TestDetect:
    def test_basic_pairs(self):
        found = {d["key_label"]: d for d in numbers.detect("Weight 154.2 lbs\nBalance: $1,240.50\nGrade 92%")}
        assert found["weight"]["value"] == 154.2 and found["weight"]["unit"] == "lbs"
        assert found["balance"]["value"] == 1240.5 and found["balance"]["unit"] == "$"
        assert found["grade"]["value"] == 92 and found["grade"]["unit"] == "%"

    def test_refuses_credentials(self):
        found = numbers.detect("PIN 1234\nCard 4242\nSSN 123")
        assert found == []

    def test_skips_ids_and_years(self):
        found = numbers.detect("Account 12345678\nYear 2026\nOrder 9001234")
        # long ints (account/order) + bare year are filtered
        assert all(d["key_label"] not in ("account", "year", "order") for d in found)


class TestSeries:
    def _obs(self, conn, key_page, label_text, value, mins_ago):
        rid = conn.execute(
            "INSERT INTO captures (ts, app, ocr_text) VALUES (datetime('now', ?),'A','x')",
            (f"-{mins_ago} minutes",)).lastrowid
        conn.execute(
            "INSERT INTO series (key, label, value, unit, ts, wisp_id) "
            "VALUES (?, ?, ?, 'lbs', datetime('now', ?), ?)",
            (key_page, label_text, value, f"-{mins_ago} minutes", rid))
        conn.commit()
        return rid

    def test_needs_three_and_variance(self, conn):
        # two obs -> not promoted
        self._obs(conn, "app::p::weight", "weight", 150, 300)
        self._obs(conn, "app::p::weight", "weight", 151, 200)
        assert numbers.active_series(conn) == []
        # third, with variance -> promoted
        self._obs(conn, "app::p::weight", "weight", 149, 100)
        act = numbers.active_series(conn)
        assert len(act) == 1 and act[0]["label"] == "weight" and act[0]["n"] == 3

    def test_constant_value_not_promoted(self, conn):
        for m in (300, 200, 100):
            self._obs(conn, "app::p::footer", "year", 2026, m)
        assert numbers.active_series(conn) == []      # no variance

    def test_scan_and_store_dedups(self, conn):
        rid = db.insert_capture(conn, "App", None, None, "x")
        numbers.scan_and_store(conn, rid, "app::page", "Steps 8000")
        numbers.scan_and_store(conn, rid, "app::page", "Steps 8000")   # same value, same day
        assert conn.execute("SELECT COUNT(*) FROM series WHERE label LIKE 'Steps%'").fetchone()[0] == 1

    def test_lookup_matches(self, conn):
        self._obs(conn, "app::p::weight", "weight", 150, 300)
        self._obs(conn, "app::p::weight", "weight", 152, 200)
        self._obs(conn, "app::p::weight", "weight", 148, 100)
        r = numbers.lookup(conn, "how has my weight moved?")
        assert r and "weight" in r["answer"].lower() and r["model"] == "Series"

    def test_lookup_none_when_no_series(self, conn):
        assert numbers.lookup(conn, "how has my weight moved?") is None

    def test_cascade_delete_removes_series(self, conn):
        rid = db.insert_capture(conn, "App", None, None, "x")
        numbers.scan_and_store(conn, rid, "app::page", "Weight 150 lbs")
        assert conn.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 1
        db.delete_captures(conn, [rid])
        assert conn.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 0
