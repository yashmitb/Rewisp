"""Delta Memory: page_key identity + the fuzzy line diff."""

from rewisp import delta


class TestPageKey:
    def test_url_strips_query_and_fragment(self):
        k = delta.page_key("Chrome", "Canvas", "https://Canvas.EDU/courses/5?token=abc#top")
        assert k == "https://canvas.edu/courses/5"

    def test_url_trailing_slash_normalized(self):
        a = delta.page_key("Chrome", "x", "https://example.com/page/")
        b = delta.page_key("Chrome", "x", "https://example.com/page")
        assert a == b

    def test_app_title_counter_stripped(self):
        a = delta.page_key("Mail", "Inbox (3)", None)
        b = delta.page_key("Mail", "Inbox (17)", None)
        assert a == b == "mail::inbox"

    def test_app_leading_count_stripped(self):
        assert delta.page_key("Slack", "(5) general", None) == "slack::general"

    def test_no_title_is_just_app(self):
        assert delta.page_key("Finder", "", None) == "finder"

    def test_non_http_url_falls_back_to_app(self):
        # file:// or app-internal urls shouldn't become the key
        k = delta.page_key("Preview", "doc.pdf", "file:///Users/x/doc.pdf")
        assert k == "preview::doc.pdf"


class TestDiff:
    def test_added_and_removed(self):
        old = "line one\nline two\nline three"
        new = "line one\nline three\nbrand new line here"
        d = delta.diff_texts(old, new)
        assert any("brand new line" in x for x in d["added"])
        assert any("line two" in x for x in d["removed"])

    def test_fuzzy_same_line_not_flagged(self):
        # >0.9 similar (one OCR-ish char off) should count as unchanged
        old = "The quarterly revenue report is ready"
        new = "The quarterly revenue report is  ready"  # double space
        d = delta.diff_texts(old, new)
        assert d["added"] == [] and d["removed"] == []

    def test_changed_line_detected(self):
        old = "Balance is 1200 dollars total"
        new = "Balance is 1450 dollars total"
        d = delta.diff_texts(old, new)
        assert d["changed"] and d["changed"][0]["old"] != d["changed"][0]["new"]

    def test_ignore_patterns_drop_churn(self):
        # a clock line changing shouldn't register as a diff
        old = "Dashboard\n3:14 pm\nStable content line"
        new = "Dashboard\n5:47 pm\nStable content line"
        d = delta.diff_texts(old, new)
        assert d["added"] == [] and d["removed"] == [] and d["changed"] == []

    def test_summarize_and_ratio(self):
        d = {"added": ["a", "b"], "removed": ["c"], "changed": [{"old": "x", "new": "y"}]}
        assert "added" in delta.summarize(d)
        assert delta.changed_ratio(d, new_line_count=4) == 0.75  # (2 added + 1 changed)/4

    def test_summarize_nothing(self):
        assert "Nothing" in delta.summarize({"added": [], "removed": [], "changed": []})
