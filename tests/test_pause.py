"""Timed pause.

Requested on launch day: "a way to mark something as do-not-track when I'm
working on sensitive stuff... a shortcut to pause for 15 or 30 minutes". The
indefinite pause that already existed conflates "stop for a moment" with "stop
recording my life", and a forgotten pause is indistinguishable from a broken
app — no wisps, no error, no explanation.
"""

import time

import pytest

from rewisp import config


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PAUSE_FLAG", tmp_path / "paused")
    yield


def test_no_flag_means_running():
    assert not config.is_paused()


def test_empty_flag_is_an_indefinite_pause():
    config.PAUSE_FLAG.write_text("")
    assert config.is_paused()
    assert config.pause_until() is None


def test_a_future_deadline_is_still_paused():
    config.PAUSE_FLAG.write_text(str(time.time() + 900))
    assert config.is_paused()
    assert config.pause_until() > time.time()


def test_an_expired_pause_resumes_itself():
    config.PAUSE_FLAG.write_text(str(time.time() - 1))
    assert not config.is_paused()
    assert not config.PAUSE_FLAG.exists(), "expired flag should be cleared"


def test_expiry_is_checked_not_timed():
    """Correct across sleep, restarts, and a daemon that wasn't running when the
    deadline passed — none of which a scheduled timer survives."""
    config.PAUSE_FLAG.write_text(str(time.time() - 3600))
    assert not config.is_paused()


def test_garbage_in_the_flag_fails_safe():
    """An unreadable deadline must mean paused, never 'capture anyway'."""
    config.PAUSE_FLAG.write_text("not-a-timestamp")
    assert config.is_paused()


def test_video_call_apps_are_blocked_by_default():
    """Screen-sharing means someone else's confidential document on your screen.
    They did not agree to being stored in your database."""
    for app in ("zoom.us", "Microsoft Teams", "FaceTime", "Webex"):
        assert app in config.DEFAULT_KILL_APPS, app
