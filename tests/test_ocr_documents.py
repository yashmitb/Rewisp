"""The macOS 26 document-OCR path (Swift helper).

The recogniser is Swift-only, so the daemon pipes a PNG to a subprocess and reads
line boxes back as JSON. These lock the contract: well-formed output parses into
the same (mid_y, x, text) shape the tiled path produces, and EVERY failure mode
returns None so ocr_cgimage falls back rather than losing a capture.
"""

import json

import pytest

from rewisp import screen


@pytest.fixture(autouse=True)
def _stub_encode_and_locate(monkeypatch):
    # A real CGImage isn't needed to test the contract; the PNG bytes are opaque
    # to everything downstream of the encode.
    monkeypatch.setattr(screen, "_cgimage_to_png", lambda cg: b"PNGBYTES")
    monkeypatch.setattr(screen, "_locate_ocr_helper", lambda: "/fake/rewisp-ocr")
    yield


class _Proc:
    def __init__(self, returncode=0, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def _run_returns(monkeypatch, proc):
    monkeypatch.setattr(screen.subprocess, "run", lambda *a, **k: proc)


def test_wellformed_json_parses_to_boxes(monkeypatch):
    rows = [{"y": 0.9, "x": 0.1, "t": "File"}, {"y": 0.5, "x": 0.2, "t": "body"}]
    _run_returns(monkeypatch, _Proc(0, json.dumps(rows).encode()))
    boxes = screen._document_boxes_swift(object())
    assert boxes == [(0.9, 0.1, "File"), (0.5, 0.2, "body")]


def test_empty_text_rows_are_dropped(monkeypatch):
    rows = [{"y": 0.9, "x": 0.1, "t": ""}, {"y": 0.5, "x": 0.2, "t": "keep"}]
    _run_returns(monkeypatch, _Proc(0, json.dumps(rows).encode()))
    assert screen._document_boxes_swift(object()) == [(0.5, 0.2, "keep")]


def test_no_helper_binary_returns_none(monkeypatch):
    monkeypatch.setattr(screen, "_locate_ocr_helper", lambda: None)
    assert screen._document_boxes_swift(object()) is None


def test_nonzero_exit_returns_none(monkeypatch):
    _run_returns(monkeypatch, _Proc(2, b""))
    assert screen._document_boxes_swift(object()) is None


def test_empty_stdout_returns_none(monkeypatch):
    _run_returns(monkeypatch, _Proc(0, b""))
    assert screen._document_boxes_swift(object()) is None


def test_malformed_json_returns_none(monkeypatch):
    _run_returns(monkeypatch, _Proc(0, b"not json{"))
    assert screen._document_boxes_swift(object()) is None


def test_subprocess_raising_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("spawn failed")
    monkeypatch.setattr(screen.subprocess, "run", boom)
    assert screen._document_boxes_swift(object()) is None


def test_all_empty_rows_returns_none_not_empty_list(monkeypatch):
    # An all-blank read must fall back, not report "no text on screen".
    rows = [{"y": 0.9, "x": 0.1, "t": ""}]
    _run_returns(monkeypatch, _Proc(0, json.dumps(rows).encode()))
    assert screen._document_boxes_swift(object()) is None
