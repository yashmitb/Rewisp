"""Merging the whole-frame OCR pass with the 2x2 tile pass.

The tiles exist to catch small text the whole-frame pass under-resolves, but
they overlap it, so the merge decides what survives. Measured on live data
before this was fixed: 59% of captures contained doubled text.
"""

from rewisp import screen


def _render(boxes):
    """Same row assembly ocr_cgimage does, so tests read like output."""
    boxes = sorted(boxes, key=lambda b: -b[0])
    rows, row_y = [], None
    for mid_y, x, text in boxes:
        if row_y is None or row_y - mid_y > 0.012:
            rows.append([])
            row_y = mid_y
        rows[-1].append((x, text))
    return "\n".join("  ".join(t for _, t in sorted(r, key=lambda b: b[0])) for r in rows)


def test_a_longer_tile_read_replaces_the_shorter_whole_frame_one():
    """The bug: 'Finder' from the whole pass plus 'Finder File' from a tile
    rendered as 'Finder  Finder File'."""
    primary = [(0.98, 0.01, "Finder")]
    tiles = [(0.98, 0.01, "Finder File")]
    out = _render(screen._merge_boxes(primary, tiles))
    assert out == "Finder File", out


def test_a_shorter_tile_fragment_is_still_dropped():
    """The original direction must keep working."""
    primary = [(0.5, 0.1, "the quick brown fox jumps")]
    tiles = [(0.5, 0.1, "the quick brown")]
    out = _render(screen._merge_boxes(primary, tiles))
    assert out == "the quick brown fox jumps", out


def test_genuinely_new_tile_text_is_kept():
    """Tiles earn their cost by finding text the whole pass missed."""
    primary = [(0.9, 0.1, "heading")]
    tiles = [(0.4, 0.1, "small print the whole pass missed")]
    out = _render(screen._merge_boxes(primary, tiles))
    assert "heading" in out and "small print" in out


def test_identical_text_on_a_different_row_survives():
    """Repetition down the page is real content, not a merge artefact —
    a column of 'Delete' buttons, say."""
    primary = [(0.8, 0.1, "Delete"), (0.6, 0.1, "Delete")]
    out = _render(screen._merge_boxes(primary, []))
    assert out.count("Delete") == 2


def test_superseding_only_applies_within_a_row():
    """A word on a distant row must not be swallowed by a longer line."""
    primary = [(0.9, 0.1, "Code")]
    tiles = [(0.2, 0.1, "Code review notes")]
    out = _render(screen._merge_boxes(primary, tiles))
    assert "Code" in out and "Code review notes" in out
    assert len(out.splitlines()) == 2


def test_very_short_boxes_are_not_used_to_supersede():
    """Two-character glyphs from icons would otherwise eat real words."""
    primary = [(0.5, 0.1, "OK")]
    tiles = [(0.5, 0.2, "OKAY then")]
    out = _render(screen._merge_boxes(primary, tiles))
    assert "OKAY then" in out


def test_empty_inputs_are_safe():
    assert screen._merge_boxes([], []) == []
    assert len(screen._merge_boxes([(0.5, 0.1, "only")], [])) == 1
