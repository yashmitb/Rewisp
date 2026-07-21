"""Shadow A/B measurement for the two OCR engines.

The point of shadow mode is to gather evidence WITHOUT risk: the stored text is
unchanged, and the log must contain metrics only — never the screen text, which
would be the /tmp privacy leak all over again.
"""

import json

import pytest

from rewisp import config, screen


def test_count_doubled_catches_adjacent_repeats():
    assert screen._count_doubled("IDE IDE File File") == 2
    assert screen._count_doubled("no repeats here") == 0
    assert screen._count_doubled("a\nb b\nc") == 1  # per line, not across lines


def test_token_overlap_is_a_ratio_not_text():
    assert screen._token_overlap("the cat sat", "the cat sat") == 1.0
    assert screen._token_overlap("", "") == 1.0
    assert screen._token_overlap("a b c d", "a b") == pytest.approx(0.5)
    assert screen._token_overlap("x y", "p q") == 0.0


def test_shadow_log_writes_metrics_only_no_screen_text(tmp_path, monkeypatch):
    log = tmp_path / "ocr_ab.jsonl"
    monkeypatch.setattr(config, "OCR_AB_LOG", log)
    # Stub both engines: tiled has doubling + a secret word, swift is clean.
    monkeypatch.setattr(screen, "_boxes_tiled",
                        lambda cg, w, h: [(0.5, 0.1, "SECRETPASSWORD SECRETPASSWORD")])
    monkeypatch.setattr(screen, "_document_boxes_swift",
                        lambda cg: [(0.5, 0.1, "SECRETPASSWORD")])

    screen._log_ocr_ab(object(), 1920, 1080, app="Mail")

    text = log.read_text()
    assert "SECRETPASSWORD" not in text, "screen text must never reach the log"
    rec = json.loads(text.strip())
    assert rec["app"] == "Mail"
    assert rec["swift_ok"] is True
    assert rec["tiled_doubled"] == 1 and rec["swift_doubled"] == 0
    assert rec["overlap"] == 1.0
    assert set(rec) >= {"ts", "tiled_chars", "swift_chars", "tiled_ms", "swift_ms"}


def test_shadow_log_records_swift_failure_as_fallback(tmp_path, monkeypatch):
    log = tmp_path / "ocr_ab.jsonl"
    monkeypatch.setattr(config, "OCR_AB_LOG", log)
    monkeypatch.setattr(screen, "_boxes_tiled", lambda cg, w, h: [(0.5, 0.1, "text")])
    monkeypatch.setattr(screen, "_document_boxes_swift", lambda cg: None)  # helper down

    screen._log_ocr_ab(object(), 1920, 1080, app="Xcode")
    rec = json.loads(log.read_text().strip())
    assert rec["swift_ok"] is False
    assert rec["swift_chars"] == 0


def test_ocr_cgimage_shadow_never_changes_stored_text(tmp_path, monkeypatch):
    # Stored text must be the tiled result regardless of shadow logging.
    log = tmp_path / "ocr_ab.jsonl"
    monkeypatch.setattr(config, "OCR_AB_LOG", log)
    monkeypatch.setattr(config, "OCR_USE_DOCUMENTS", False)
    monkeypatch.setattr(config, "OCR_SHADOW_AB", True)
    monkeypatch.setattr(screen.Quartz, "CGImageGetWidth", lambda cg: 1920)
    monkeypatch.setattr(screen.Quartz, "CGImageGetHeight", lambda cg: 1080)
    monkeypatch.setattr(screen, "_boxes_tiled", lambda cg, w, h: [(0.5, 0.1, "stored line")])
    monkeypatch.setattr(screen, "_document_boxes_swift", lambda cg: [(0.5, 0.1, "other")])

    out = screen.ocr_cgimage(object(), app="Safari")
    assert out == "stored line"          # tiled path, unchanged
    assert log.exists() and log.read_text().strip()  # but a metric line was written


def test_shadow_off_writes_nothing(tmp_path, monkeypatch):
    log = tmp_path / "ocr_ab.jsonl"
    monkeypatch.setattr(config, "OCR_AB_LOG", log)
    monkeypatch.setattr(config, "OCR_USE_DOCUMENTS", False)
    monkeypatch.setattr(config, "OCR_SHADOW_AB", False)
    monkeypatch.setattr(screen.Quartz, "CGImageGetWidth", lambda cg: 800)
    monkeypatch.setattr(screen.Quartz, "CGImageGetHeight", lambda cg: 600)
    monkeypatch.setattr(screen, "_boxes_tiled", lambda cg, w, h: [(0.5, 0.1, "x")])

    screen.ocr_cgimage(object())
    assert not log.exists()
