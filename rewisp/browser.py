"""Active tab URL/title from Dia via AppleScript (verified working 2026-07-08, Phase 0)."""

import subprocess

from . import config

# NOTE: Dia returns tabs by id; holding one in a variable fails with
# "Can't make id ... into type specifier" (-1700). Query properties directly.
_SCRIPT = f'''
tell application "{config.BROWSER_APP}"
    if (count of windows) is 0 then return ""
    return (URL of active tab of front window) & "\\n" & (title of active tab of front window)
end tell
'''


def active_tab() -> tuple[str | None, str | None]:
    """(url, title) of Dia's active tab, or (None, None) if unavailable."""
    try:
        out = subprocess.run(
            ["osascript", "-e", _SCRIPT],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None, None
        parts = out.stdout.rstrip("\n").split("\n", 1)
        url = parts[0].strip() or None
        title = parts[1].strip() if len(parts) > 1 else None
        return url, title
    except (subprocess.TimeoutExpired, OSError):
        return None, None
