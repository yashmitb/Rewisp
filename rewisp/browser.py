"""Active tab URL/title from whatever browser is frontmost, via AppleScript.

Chromium family (Chrome, Arc, Edge, Brave, Dia, Vivaldi, Opera) shares the
Chrome scripting dictionary; Safari has its own; Firefox exposes nothing —
title-only there (no URL trigger, no URL kill list; title heuristics still
apply). First automation of each browser triggers one macOS consent prompt.

NOTE (Dia, applies to all Chromium): holding `active tab` in a variable fails
with -1700 ("Can't make id ... into type specifier"). Query properties directly.
"""

import subprocess

# app name -> scripting flavor
CHROMIUM = "chromium"
SAFARI = "safari"
TITLE_ONLY = "title-only"

BROWSERS: dict[str, str] = {
    "Dia": CHROMIUM,
    "Google Chrome": CHROMIUM,
    "Arc": CHROMIUM,
    "Microsoft Edge": CHROMIUM,
    "Brave Browser": CHROMIUM,
    "Vivaldi": CHROMIUM,
    "Opera": CHROMIUM,
    "Chromium": CHROMIUM,
    "Safari": SAFARI,
    "Firefox": TITLE_ONLY,
}

# Chromium: URL, title, and window mode ("incognito" -> private, never capture).
# `mode` isn't in every fork's dictionary (Dia lacks it) — soft-fail to "".
_CHROMIUM_SCRIPT = '''
tell application "{app}"
    if (count of windows) is 0 then return ""
    set theURL to URL of active tab of front window
    set theTitle to title of active tab of front window
    set theMode to ""
    try
        set theMode to mode of front window
    end try
    return theURL & "\\n" & theTitle & "\\n" & theMode
end tell
'''

# Safari: no incognito property at all — private windows fall back to the
# window-title keyword heuristic in the kill list.
_SAFARI_SCRIPT = '''
tell application "Safari"
    if (count of documents) is 0 then return ""
    return (URL of front document) & "\\n" & (name of front document) & "\\n"
end tell
'''


def is_browser(app: str) -> bool:
    return app in BROWSERS


def active_tab(app: str) -> tuple[str | None, str | None, bool]:
    """(url, title, is_private) for the frontmost tab of `app`.
    (None, None, False) when unavailable (no window, consent denied, Firefox)."""
    flavor = BROWSERS.get(app)
    if flavor == CHROMIUM:
        script = _CHROMIUM_SCRIPT.format(app=app.replace('"', ""))
    elif flavor == SAFARI:
        script = _SAFARI_SCRIPT
    else:
        return None, None, False
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None, None, False
        parts = (out.stdout.rstrip("\n") + "\n\n").split("\n")
        url = parts[0].strip() or None
        title = parts[1].strip() or None
        private = "incognito" in parts[2].strip().lower()
        return url, title, private
    except (subprocess.TimeoutExpired, OSError):
        return None, None, False
