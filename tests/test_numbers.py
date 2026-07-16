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


class TestPrecisionGate:
    """Audit fix: reject menu-bar chrome + require unit-or-metric so OCR noise
    (battery %, 'Thought for 15s', episode/version numbers) isn't tracked."""
    def test_menu_bar_chrome_rejected(self):
        assert numbers.detect("Dia File Edit View History Extensions Window Help 49%") == []

    def test_ai_ui_noise_rejected(self):
        assert numbers.detect("Thought for 15s") == []
        assert numbers.detect("Claude Sonnet 4.6") == []
        assert numbers.detect("Episode 3 recap") == []

    def test_bare_number_without_unit_or_metric_rejected(self):
        assert numbers.detect("python 3 installed") == []

    def test_real_metrics_kept(self):
        assert numbers.detect("My weight 178 lbs")
        assert numbers.detect("Grade 92%")
        assert numbers.detect("Score 88 today")      # metric word, no unit
        assert numbers.detect("Balance $1,240.50")


class TestLabelNormalization:
    def test_phrasing_variants_merge_into_one_series(self):
        from rewisp import numbers
        a = numbers.detect("My weight today 182 lbs")[0]
        b = numbers.detect("Weight 182 lbs")[0]
        assert a["key_label"] == b["key_label"] == "weight"

    def test_lookup_phrasings(self, conn):
        from rewisp import db, numbers
        rid = db.insert_capture(conn, "Health", None, None, "x")
        for val, ago in [(182, "-6 days"), (180, "-4 days"), (179, "-2 days")]:
            numbers.scan_and_store(conn, rid, "health::w", f"Weight {val} lbs")
            conn.execute("UPDATE series SET ts=datetime('now',?) WHERE value=?", (ago, val))
        conn.commit()
        for q in ["how has my weight moved", "weight over time", "how is my weight doing"]:
            assert numbers.lookup(conn, q), q
