"""Repeated context lines cost latency and quality.

Captures overlap by design (app-switch, scroll-settle, heartbeat all catch the
same page), so an assembled context repeats itself. Measured on a real corpus:
27% of context lines were duplicates — 3.5 KB of 14.8 KB sent on every question.
"""

from rewisp.ask import dedupe_context_lines as dd


def test_identical_lines_collapse():
    out = dd("the quiz is due on July 12\nthe quiz is due on July 12\n")
    assert out.count("the quiz is due") == 1


def test_ocr_noise_does_not_defeat_it():
    """Same line captured twice can differ by punctuation or case."""
    out = dd("Quiz 3.2 is due July 12!\nquiz 32 is due july 12\n")
    assert len(out.strip().splitlines()) == 1


def test_the_original_line_is_kept_not_the_normalised_one():
    out = dd("Quiz 3.2 is due July 12!\n")
    assert out.strip() == "Quiz 3.2 is due July 12!"


def test_order_is_preserved():
    """Recency ordering is a signal retrieval worked to produce."""
    out = dd("first line here\nsecond line here\nthird line here\n")
    assert out.splitlines() == ["first line here", "second line here", "third line here"]


def test_short_lines_are_never_dropped():
    """Headers and labels repeat legitimately and carry structure."""
    out = dd("## Today\n- a\n## Today\n- b\n")
    assert out.count("## Today") == 2


def test_distinct_content_survives():
    text = "\n".join(f"a genuinely distinct sentence number {i}" for i in range(20))
    assert len(dd(text).splitlines()) == 20


def test_empty_and_blank_input():
    assert dd("") == ""
    assert dd("\n\n") == "\n\n"


def test_measurably_shrinks_a_realistic_context():
    lines = []
    for i in range(30):
        lines.append(f"unique observation {i}")
        lines.append("Rewisp — an ambient memory for your Mac")   # the repeat
    before = "\n".join(lines)
    after = dd(before)
    assert len(after) < len(before) * 0.75
    assert after.count("ambient memory") == 1
