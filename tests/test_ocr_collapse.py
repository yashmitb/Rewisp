"""Adjacent-word doubling collapse. The overlapping tile OCR pass reads a UI label
in the seam twice ('Ask  Ask'); real data showed ~0.6 such pairs per capture.
Collapse them — but never numeric tables, counts, or single glyphs, where an
adjacent repeat is real data."""

from rewisp import screen


def test_collapses_doubled_words():
    assert screen._collapse_doubled_words("Ask  Ask  Save") == "Ask  Save"
    assert screen._collapse_doubled_words("free free buy buy") == "free buy"
    assert screen._collapse_doubled_words("Google  Google Verification") == "Google Verification"


def test_collapses_triples_and_case_wobble():
    assert screen._collapse_doubled_words("the the the end") == "the end"
    assert screen._collapse_doubled_words("Ask ask") == "Ask"          # OCR case variance


def test_preserves_numeric_tables_and_counts():
    assert screen._collapse_doubled_words("0 0 0 0") == "0 0 0 0"
    assert screen._collapse_doubled_words("426K 26K") == "426K 26K"
    assert screen._collapse_doubled_words("12 12") == "12 12"          # numbers untouched


def test_preserves_single_chars_and_phrases():
    assert screen._collapse_doubled_words("a a b") == "a a b"
    assert screen._collapse_doubled_words("New York New York") == "New York New York"


def test_assemble_applies_collapse():
    # Two boxes on the same visual row reading the same UI word -> one in output.
    boxes = [(0.5, 0.10, "Ask"), (0.5, 0.20, "Ask"), (0.5, 0.40, "Save")]
    out = screen._assemble(boxes, height=1000)
    assert out.count("Ask") == 1 and "Save" in out
