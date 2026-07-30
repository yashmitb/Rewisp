"""User-excluded apps: 'don't remember this' for games/media/noise. Distinct from
the kill list (privacy). Data showed one game ('java'/'Lunar Client') was ~24% of
all captures — pure noise — so users need a way to drop it."""

import pytest

from rewisp import config, screen, daemon as daemon_mod


def test_excluded_apps_helper_normalizes(monkeypatch):
    monkeypatch.setattr(config, "load_settings",
                        lambda: {"excluded_apps": ["Lunar Client", "  java ", "", "STEAM"]})
    assert config.excluded_apps() == {"lunar client", "java", "steam"}


def test_excluded_apps_default_empty(monkeypatch):
    monkeypatch.setattr(config, "load_settings", lambda: {})
    assert config.excluded_apps() == set()


class _Kill:
    def reload_if_changed(self): pass
    def blocks_app(self, app): return False
    def blocks(self, app, title, url): return False


def _daemon(monkeypatch, excluded):
    monkeypatch.setattr(daemon_mod.db, "connect", lambda: object())
    monkeypatch.setattr(daemon_mod, "KillList", _Kill)
    monkeypatch.setattr(config, "excluded_apps", lambda: set(excluded))
    d = daemon_mod.Daemon()
    monkeypatch.setattr(daemon_mod.config, "is_paused", lambda: False)
    monkeypatch.setattr(screen, "screen_locked_or_asleep", lambda: False)
    monkeypatch.setattr(screen, "seconds_since_any_input", lambda: 1)
    fired = {"captured": False}
    monkeypatch.setattr(d, "capture",
                        lambda *a, **k: fired.__setitem__("captured", True))
    return d, fired


def test_excluded_app_is_never_captured(monkeypatch):
    d, fired = _daemon(monkeypatch, {"java"})
    monkeypatch.setattr(screen, "frontmost_info", lambda: ("java", 1, "Minecraft"))
    d.last_content_check = 1e9
    d.tick()
    assert fired["captured"] is False
    from rewisp.daemon import STATE
    assert STATE.get("capture") == "excluded"


def test_excluded_match_is_case_and_prefix_insensitive(monkeypatch):
    # A left-to-right mark or different case must not sneak the app past the check.
    d, fired = _daemon(monkeypatch, {"lunar client"})
    monkeypatch.setattr(screen, "frontmost_info", lambda: ("‎Lunar Client", 1, None))
    d.tick()
    assert fired["captured"] is False


def test_non_excluded_app_still_captures(monkeypatch):
    d, fired = _daemon(monkeypatch, {"java"})
    monkeypatch.setattr(screen, "frontmost_info", lambda: ("Notes", 1, "Doc"))
    monkeypatch.setattr(screen, "seconds_since_scroll", lambda: 999)
    monkeypatch.setattr(daemon_mod.browser, "is_browser", lambda app: False)
    d.last_app = "Notes"
    import time
    d.last_capture = time.monotonic() - 999   # force a heartbeat
    d.tick()
    assert fired["captured"] is True
