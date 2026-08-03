"""Excluded sites — the "don't bother" list, for the web.

The app-name list cannot reach a noisy website: everything in a browser shares
the browser's app name, so excluding a video site by app would exclude the whole
browser. These tests pin the matching rules and, more importantly, the ordering
against the privacy guards — a kill-listed or private page must stay privacy,
never get quietly reclassified as mere noise.
"""

import json

import pytest

from rewisp import config


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Point config at a throwaway settings file."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    def write(**kw):
        path.write_text(json.dumps(kw))
    return write


class TestMatching:
    def test_bare_domain_covers_the_whole_site(self, settings):
        settings(excluded_sites=["youtube.com"])
        assert config.site_excluded("https://www.youtube.com/watch?v=abc")
        assert config.site_excluded("https://m.youtube.com/feed/subscriptions")

    def test_a_bare_domain_matches_the_host_not_the_query_string(self, settings):
        # Found by replaying 30 days of real URLs: plain substring matching made
        # "youtube.com" skip a Google sign-in page whose redirect target merely
        # mentioned it. The whole point of the list is noise, and that page is
        # not noise — it's the user trying to log in.
        settings(excluded_sites=["youtube.com"])
        assert not config.site_excluded(
            "https://accounts.google.com/v3/signin/accountchooser"
            "?continue=http%3A%2F%2Fm.youtube.com%2Fsignin")
        assert config.site_excluded("https://m.youtube.com/signin")

    def test_subdomains_are_still_covered(self, settings):
        settings(excluded_sites=["youtube.com"])
        for u in ("https://youtube.com/feed", "https://www.youtube.com/watch",
                  "https://music.youtube.com/playlist"):
            assert config.site_excluded(u), u

    def test_a_lookalike_domain_is_not_covered(self, settings):
        settings(excluded_sites=["youtube.com"])
        assert not config.site_excluded("https://notyoutube.com/watch")
        assert not config.site_excluded("https://youtube.com.evil.example/watch")

    def test_port_and_credentials_do_not_defeat_the_host_match(self, settings):
        settings(excluded_sites=["example.com"])
        assert config.site_excluded("http://example.com:8080/x")
        assert config.site_excluded("http://user:pw@example.com/x")

    def test_a_path_covers_just_that_page(self, settings):
        settings(excluded_sites=["reddit.com/r/all"])
        assert config.site_excluded("https://reddit.com/r/all/top")
        assert not config.site_excluded("https://reddit.com/r/macapps")

    def test_case_insensitive(self, settings):
        settings(excluded_sites=["YouTube.COM"])
        assert config.site_excluded("https://www.youtube.com/watch")

    def test_unrelated_urls_are_untouched(self, settings):
        settings(excluded_sites=["youtube.com"])
        assert not config.site_excluded("https://github.com/yashmitb/Rewisp")

    def test_no_url_is_never_excluded(self, settings):
        settings(excluded_sites=["youtube.com"])
        assert not config.site_excluded(None)
        assert not config.site_excluded("")

    def test_empty_list_excludes_nothing(self, settings):
        settings(excluded_sites=[])
        assert not config.site_excluded("https://www.youtube.com/watch")

    def test_blank_entries_are_ignored(self, settings):
        # A stray empty string would otherwise be a substring of every URL and
        # silently switch off capture everywhere.
        settings(excluded_sites=["", "   "])
        assert config.excluded_sites() == []
        assert not config.site_excluded("https://example.com")

    def test_patterns_can_be_passed_in(self, settings):
        # The daemon caches the list and passes it, rather than re-reading
        # settings on every tick.
        settings(excluded_sites=[])
        assert config.site_excluded("https://youtube.com/watch", ["youtube.com"])


class TestOrderingAgainstPrivacy:
    """A privacy guard must win. Noise exclusion runs after all of them."""

    def test_source_order_puts_site_check_after_every_privacy_guard(self):
        src = (__import__("pathlib").Path(__file__).parent.parent
               / "rewisp" / "daemon.py").read_text()
        site = src.index("config.site_excluded(url, self.excluded_sites)")
        assert src.index("self.kill.blocks_app(app)") < site
        assert src.index("if self.private_window:") < site
        assert src.index("if self.kill.blocks(app, title, url):") < site

    def test_site_check_sets_excluded_not_killlist(self):
        # The menu-bar icon distinguishes these: "excluded" is a quiet skip,
        # "killlist" means privacy stopped the capture. Conflating them would
        # misreport why nothing is being remembered.
        src = (__import__("pathlib").Path(__file__).parent.parent
               / "rewisp" / "daemon.py").read_text()
        after = src[src.index("config.site_excluded(url, self.excluded_sites)"):][:220]
        assert '"excluded"' in after
        assert '"killlist"' not in after


class TestSettings:
    def test_round_trips_through_save(self, settings):
        settings()
        config.save_settings({"excluded_sites": ["youtube.com", "twitch.tv"]})
        assert config.excluded_sites() == ["youtube.com", "twitch.tv"]

    def test_defaults_to_empty(self):
        assert config.DEFAULT_SETTINGS["excluded_sites"] == []
