"""The OCR A/B verdict.

The document engine has been built, signed and shipped switched off since v0.25
because nothing ever turned the shadow log into a decision. These tests pin the
decision rule — above all that a faster engine which reads LESS of the screen
must lose, since that regression would be silent and would degrade every future
answer rather than announcing itself.
"""

import json

import pytest

from rewisp import bench, config


@pytest.fixture
def ab_log(tmp_path, monkeypatch):
    path = tmp_path / "ocr_ab.jsonl"
    monkeypatch.setattr(config, "OCR_AB_LOG", path)

    def write(records):
        path.write_text("\n".join(json.dumps(r) for r in records))
    return write


def _rec(**kw):
    base = dict(swift_ok=True, tiled_chars=1000, swift_chars=1000,
                tiled_lines=40, swift_lines=40, tiled_doubled=0.6,
                swift_doubled=0.0, overlap=0.95, tiled_ms=400, swift_ms=100)
    base.update(kw)
    return base


class TestVerdict:
    def test_no_log_says_how_to_start(self, tmp_path, monkeypatch):
        # Must point at a path that does not exist. Reading the real
        # config.OCR_AB_LOG made this pass only on a machine that had never run
        # the shadow — it went red the moment the A/B was actually switched on,
        # which is exactly backwards for a test.
        monkeypatch.setattr(config, "OCR_AB_LOG", tmp_path / "absent.jsonl")
        r = bench.ocr_ab()
        assert r["records"] == 0
        assert "REWISP_OCR_SHADOW" in r["verdict"]

    def test_faster_and_cleaner_with_equal_text_wins(self, ab_log):
        ab_log([_rec() for _ in range(200)])
        r = bench.ocr_ab()
        assert "SWITCH IT ON" in r["verdict"]
        assert "4.0x faster" in r["verdict"]

    def test_faster_but_reads_less_text_loses(self, ab_log):
        # The failure that must never be waved through: it looks like a win on
        # every timing number while quietly capturing less of the screen.
        ab_log([_rec(swift_chars=700) for _ in range(200)])
        r = bench.ocr_ab()
        assert "KEEP THE TILED PATH" in r["verdict"]
        assert "LESS text" in r["verdict"]

    def test_engines_disagreeing_about_content_loses(self, ab_log):
        ab_log([_rec(overlap=0.55) for _ in range(200)])
        r = bench.ocr_ab()
        assert "KEEP THE TILED PATH" in r["verdict"]
        assert "disagree" in r["verdict"]

    def test_no_speed_or_cleanliness_gain_is_not_a_reason_to_switch(self, ab_log):
        ab_log([_rec(swift_ms=400, swift_doubled=0.6) for _ in range(200)])
        assert "No clear win" in bench.ocr_ab()["verdict"]

    def test_much_worse_doubling_loses_even_when_faster(self, ab_log):
        # This is the documented failure of the flat pyobjc path: 130 doubled
        # pairs vs 6. Speed must not buy its way past that.
        ab_log([_rec(swift_doubled=9.0) for _ in range(200)])
        r = bench.ocr_ab()
        assert "KEEP THE TILED PATH" in r["verdict"]
        assert "doubles words" in r["verdict"]

    def test_a_helper_that_never_answers_is_reported_plainly(self, ab_log):
        ab_log([_rec(swift_ok=False) for _ in range(50)])
        r = bench.ocr_ab()
        assert "never returned anything" in r["verdict"]

    def test_a_thin_sample_is_flagged(self, ab_log):
        ab_log([_rec() for _ in range(12)])
        r = bench.ocr_ab()
        assert "only 12 comparable" in r["verdict"]

    def test_failed_helper_runs_are_excluded_from_the_means(self, ab_log):
        # A run where the helper produced nothing would otherwise drag the
        # document engine's character count to zero and fake a regression.
        ab_log([_rec() for _ in range(100)] + [_rec(swift_ok=False, swift_chars=0)
                                               for _ in range(20)])
        r = bench.ocr_ab()
        assert r["comparable"] == 100 and r["helper_failed"] == 20
        assert r["chars"]["swift"] == 1000
