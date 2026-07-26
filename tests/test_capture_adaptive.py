"""Adaptive capture: activity-aware cadence + same-surface content-change trigger.

The tick loop needs the window server, so screen calls are mocked. The point is
the DECISION logic: what reason fires, and that the extra work is gated on being
active and throttled so it can't run up resource use when you're away.
"""

import pytest

from rewisp import config, screen, daemon as daemon_mod


# ── pure helpers ─────────────────────────────────────────────────────────────

def test_pixel_change_fraction_bounds():
    a = bytes([0] * 100)
    assert screen.pixel_change_fraction(a, None) == 1.0        # nothing to compare
    assert screen.pixel_change_fraction(a, a) == 0.0           # identical
    b = bytes([255] * 50 + [0] * 50)
    assert screen.pixel_change_fraction(b, a) == pytest.approx(0.5)


def test_is_duplicate_still_consistent():
    a = bytes([0] * 100)
    assert screen.is_duplicate(a, a) is True                   # 0% changed -> dup
    assert screen.is_duplicate(a, None) is False               # nothing prior -> not dup
    changed = bytes([255] * 20 + [0] * 80)                     # 20% changed
    assert screen.is_duplicate(changed, a) is False


# ── tick decision logic ──────────────────────────────────────────────────────

class _Kill:
    def reload_if_changed(self): pass
    def blocks_app(self, app): return False
    def blocks(self, app, title, url): return False


@pytest.fixture
def dmn(monkeypatch):
    monkeypatch.setattr(daemon_mod.db, "connect", lambda: object())
    monkeypatch.setattr(daemon_mod, "KillList", _Kill)
    d = daemon_mod.Daemon()
    # stable, non-browser, non-skipped frontmost app; not paused / locked / idle
    monkeypatch.setattr(daemon_mod.config, "is_paused", lambda: False)
    monkeypatch.setattr(screen, "screen_locked_or_asleep", lambda: False)
    monkeypatch.setattr(screen, "frontmost_info", lambda: ("Notes", 1, "Doc"))
    monkeypatch.setattr(screen, "seconds_since_scroll", lambda: 999)
    monkeypatch.setattr(daemon_mod.browser, "is_browser", lambda app: False)
    d.last_app = "Notes"          # avoid an app-switch trigger
    d.prev_thumb = bytes([0] * 1024)
    fired = {}
    def fake_capture(app, pid, title, url, reason, img=None):
        fired["reason"] = reason
        fired["img"] = img
        d.last_capture = 1e9      # so heartbeat doesn't refire
    monkeypatch.setattr(d, "capture", fake_capture)
    return d, fired, monkeypatch


def _active(monkeypatch, seconds_since_input):
    monkeypatch.setattr(screen, "seconds_since_any_input", lambda: seconds_since_input)


def test_content_change_fires_when_active_and_screen_changed(dmn):
    d, fired, mp = dmn
    _active(mp, 1)                                  # active
    mp.setattr(screen, "capture_frontmost_display", lambda pid: "IMG")
    mp.setattr(screen, "thumbnail_gray", lambda img: bytes([255] * 1024))  # very different
    d.last_capture = 1e9                            # heartbeat not due
    d.tick()
    assert fired.get("reason") == "content-change"
    assert fired.get("img") == "IMG"                # grabbed frame handed off (no double grab)


def test_no_content_capture_when_idle(dmn):
    d, fired, mp = dmn
    _active(mp, 999)                                # NOT active (but < idle guard? 999>300 -> idle)
    # idle() would short-circuit; force not-idle but still "inactive" for the window
    mp.setattr(d, "idle", lambda: False)
    grabbed = {"n": 0}
    def grab(pid): grabbed["n"] += 1; return "IMG"
    mp.setattr(screen, "capture_frontmost_display", grab)
    mp.setattr(screen, "thumbnail_gray", lambda img: bytes([255] * 1024))
    d.last_capture = 1e9
    d.tick()
    assert fired.get("reason") is None              # inactive -> no content probe
    assert grabbed["n"] == 0                         # and crucially: no display grab at all


def test_content_probe_is_throttled(dmn):
    d, fired, mp = dmn
    _active(mp, 1)
    grabbed = {"n": 0}
    def grab(pid): grabbed["n"] += 1; return "IMG"
    mp.setattr(screen, "capture_frontmost_display", grab)
    mp.setattr(screen, "thumbnail_gray", lambda img: bytes([0] * 1024))  # NO change
    d.last_capture = 1e9
    d.tick(); d.tick(); d.tick()                     # 3 rapid ticks
    assert grabbed["n"] == 1                          # throttled to one probe within the window
    assert fired.get("reason") is None                # no change -> nothing fired


def test_adaptive_heartbeat_tighter_when_active(dmn):
    d, fired, mp = dmn
    _active(mp, 1)                                    # active
    mp.setattr(screen, "capture_frontmost_display", lambda pid: "IMG")
    mp.setattr(screen, "thumbnail_gray", lambda img: bytes([0] * 1024))
    # last capture 30s ago: > active heartbeat (20s), < idle heartbeat (60s)
    import time
    d.last_capture = time.monotonic() - 30
    d.tick()
    assert fired.get("reason") == "heartbeat"         # active cadence fired
