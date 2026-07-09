"""Kill list enforcement. When it says no, capture pauses fully — no partial data."""

from . import config


class KillList:
    def __init__(self):
        self._mtime = 0.0
        self.reload()

    def reload(self) -> None:
        kl = config.load_kill_list()
        self.apps = {a.lower() for a in kl["apps"]}
        self.url_patterns = kl["url_patterns"]
        try:
            self._mtime = config.KILL_LIST_PATH.stat().st_mtime
        except OSError:
            self._mtime = 0.0

    def reload_if_changed(self) -> None:
        """Pick up Settings-window edits without a daemon restart."""
        try:
            m = config.KILL_LIST_PATH.stat().st_mtime
        except OSError:
            m = 0.0
        if m != self._mtime:
            self.reload()

    def blocks_app(self, app_name: str) -> bool:
        # Defense in depth: screen._clean_app_name() already strips invisible
        # Unicode at the source (a leading U+200E on "WhatsApp" once let 56
        # captures through an exact-match check) — normalize again here so
        # this comparison can never silently miss regardless of caller.
        from . import screen
        return screen._clean_app_name(app_name).lower() in self.apps

    def blocks_url(self, url: str | None) -> bool:
        if not url:
            return False
        u = url.lower()
        return any(p in u for p in self.url_patterns)

    def blocks_private_window(self, window_title: str | None) -> bool:
        if not window_title:
            return False
        t = window_title.lower()
        return any(k in t for k in config.PRIVATE_WINDOW_KEYWORDS)

    def blocks(self, app_name: str, window_title: str | None, url: str | None) -> bool:
        return (self.blocks_app(app_name)
                or self.blocks_url(url)
                or self.blocks_private_window(window_title))
