"""Global pause hotkey via Quartz event tap (needs Accessibility permission).

Default: Cmd+Option+P toggles the pause flag. Runs its own CFRunLoop thread.
(Cmd+Shift+P deliberately avoided — VS Code command palette.)
"""

import logging
import threading

import Quartz

from . import config

log = logging.getLogger("rewisp")

KEYCODE_P = 35
REQUIRED_FLAGS = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskAlternate


def _toggle_pause() -> None:
    if config.PAUSE_FLAG.exists():
        config.PAUSE_FLAG.unlink(missing_ok=True)
        log.info("hotkey: capture resumed")
    else:
        config.PAUSE_FLAG.touch()
        log.info("hotkey: capture paused")


def _tap_callback(proxy, etype, event, refcon):
    if etype == Quartz.kCGEventKeyDown:
        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        flags = Quartz.CGEventGetFlags(event)
        if keycode == KEYCODE_P and (flags & REQUIRED_FLAGS) == REQUIRED_FLAGS:
            _toggle_pause()
            return None  # swallow the keystroke
    return event


def start_listener() -> bool:
    """Start the hotkey event tap in a daemon thread. Returns False if the tap
    couldn't be created (Accessibility permission missing)."""
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionDefault,
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
        _tap_callback,
        None,
    )
    if tap is None:
        log.warning("hotkey: event tap creation failed (Accessibility permission missing?) "
                    "— pause hotkey disabled, CLI pause still works")
        return False

    def run():
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        log.info("hotkey: Cmd+Option+P pause toggle active")
        Quartz.CFRunLoopRun()

    threading.Thread(target=run, name="rewisp-hotkey", daemon=True).start()
    return True
