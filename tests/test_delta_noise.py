"""Delta must not report OCR jitter as a real page change.

The 0.6-0.9 similarity band is where a line 'changed' — but it's also where the
SAME line lands when OCR read it differently twice. These lock the distinction:
per-word jitter with aligned words and equal numbers is noise (no change), while
a swapped word or a changed number is a real change.
"""

from rewisp import delta


def test_word_level_ocr_jitter_is_not_a_change():
    old = "the quick brown fox jumps over the lazy dog"
    new = "the qulck browm fox jvmps over the Iazy dog"   # several OCR slips, same words
    d = delta.diff_texts(old, new)
    assert d["changed"] == [], d
    assert d["added"] == [] and d["removed"] == []


def test_real_word_swap_is_a_change():
    old = "the quick brown fox jumps over the lazy dog"
    new = "the quick red fox jumps over the lazy dog"      # brown -> red
    d = delta.diff_texts(old, new)
    assert d["changed"], d


def test_number_change_survives_noise_filter():
    # Same words, but a number moved: must stay a change even amid OCR jitter.
    old = "invoice total is 1200 dollars due friday"
    new = "invoice total is 1450 dollars due friday"
    d = delta.diff_texts(old, new)
    assert d["changed"], d


def test_added_word_is_not_swallowed_as_noise():
    old = "review the draft before monday"
    new = "please review the final draft before monday"    # words added
    d = delta.diff_texts(old, new)
    assert d["added"] or d["changed"], d


def test_is_ocr_noise_unit():
    assert delta._is_ocr_noise("meeting notes summary", "meetlng notes svmmary")
    assert not delta._is_ocr_noise("price is 10 total", "price is 20 total")   # number
    assert not delta._is_ocr_noise("send the report", "send the invoice")      # word swap
    assert not delta._is_ocr_noise("a b c", "a b c d")                          # length
    assert not delta._is_ocr_noise("", "")                                      # empty -> not "same content"
