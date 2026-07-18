"""Capture daemon: polling loop with window-switch, URL-change, and scroll-settle triggers,
idle guard, kill list, dedupe. Screenshots live only in memory — OCR'd, then released."""

import logging
import time

from . import browser, config, db, screen
from .killlist import KillList

log = logging.getLogger("rewisp")

# Live capture state, read by the HTTP API (same process) for the menu bar icon.
STATE = {"capture": "starting"}


class Daemon:
    def __init__(self):
        self.conn = db.connect()
        self.kill = KillList()
        self.last_app = ""
        self.last_url: str | None = None
        self.prev_thumb: bytes | None = None
        self.last_url_poll = 0.0
        self.scroll_pending = False
        self.killlist_active = False
        self.last_capture = 0.0
        self.last_kill_check = 0.0
        self.private_window = False
        self.last_field_check = 0.0

    # -- state checks ---------------------------------------------------------

    def paused(self) -> bool:
        return config.PAUSE_FLAG.exists()

    def idle(self) -> bool:
        return screen.seconds_since_any_input() > config.IDLE_GUARD_SECONDS

    # -- capture --------------------------------------------------------------

    def capture(self, app: str, pid: int, title: str | None, url: str | None,
                reason: str) -> None:
        img = screen.capture_frontmost_display(pid)
        # Attempt counts for heartbeat pacing even if deduped — otherwise an
        # unchanged screen would re-screenshot every tick after the interval.
        self.last_capture = time.monotonic()
        if img is None:
            log.warning("capture failed (no image) app=%s", app)
            return
        thumb = screen.thumbnail_gray(img)
        if screen.is_duplicate(thumb, self.prev_thumb):
            log.debug("dedupe: discarded near-identical capture (%s)", reason)
            return
        self.prev_thumb = thumb
        try:
            text = screen.ocr_cgimage(img)
        finally:
            del img  # image existed only in memory; released here
        if len(text.strip()) < config.MIN_CAPTURE_CHARS:
            return   # video-subtitle fragments / near-empty screens aren't memories
        # Semantic vector for meaning-based retrieval. Best-effort: if the embedder
        # is offline the row stores NULL and the nightly backfill fills it later.
        emb = None
        try:
            from . import embed
            emb = embed.embed(text)
        except Exception:  # noqa: BLE001 — never let embedding break capture
            pass
        row_id = db.insert_capture(self.conn, app, title, url, text, embedding=emb)
        log.info("captured #%d [%s] app=%s title=%r url=%s chars=%d",
                 row_id, reason, app, (title or "")[:60], url or "-", len(text))
        # Proactive recall (Déjà Vu). No-op unless the user enabled nudges; reuses
        # the embedding we just computed, so detection is nearly free.
        if emb is not None:
            try:
                from . import dejavu, delta, embed
                pkey = delta.page_key(app, title, url)
                dejavu.maybe_nudge(self.conn, row_id, embed.to_vec(emb), app, pkey)
            except Exception:  # noqa: BLE001 — never let a nudge break capture
                log.debug("dejavu check failed", exc_info=True)
        # Catch commitments ("I'll send it Friday") into the Pending review flow.
        # Source-gated: only correspondence/notes surfaces can produce promises.
        try:
            from . import promises
            promises.scan_and_store(self.conn, row_id, text, app=app, url=url)
        except Exception:  # noqa: BLE001
            log.debug("promise scan failed", exc_info=True)
        # Track recurring label+number pairs on this page (weight, grade, price…).
        try:
            from . import delta, numbers
            numbers.scan_and_store(self.conn, row_id, delta.page_key(app, title, url), text)
        except Exception:  # noqa: BLE001
            log.debug("numbers scan failed", exc_info=True)

    # -- main loop ------------------------------------------------------------

    def tick(self) -> None:
        if self.paused():
            STATE["capture"] = "paused"
            return
        if screen.screen_locked_or_asleep() or self.idle():
            STATE["capture"] = "idle"
            return

        # Settings-window kill list edits apply live (cheap mtime check ~2s).
        now_mono = time.monotonic()
        if now_mono - self.last_kill_check > 2:
            self.last_kill_check = now_mono
            self.kill.reload_if_changed()

        app, pid, title = screen.frontmost_info()
        if not app:
            return

        # Never capture Rewisp's own UI. The search panel and chat would otherwise
        # index the questions you type as if they were memories — a feedback loop
        # that pollutes retrieval (you ask "what did I search?" and it finds your
        # own past questions). The digest is already stored separately.
        # Same for pseudo-apps (Dock/Mission Control): clicking the Dock makes the
        # whole desktop "frontmost" and stores a junk desktop capture.
        if app == "Rewisp" or app in config.CAPTURE_SKIP_APPS:
            STATE["capture"] = "idle"
            return

        # Kill-list app frontmost: full pause, reset trigger state so nothing leaks.
        if self.kill.blocks_app(app):
            if not self.killlist_active:
                log.info("kill list active: %s frontmost, capture paused", app)
            self.killlist_active = True
            self.last_app = app
            STATE["capture"] = "killlist"
            return
        self.killlist_active = False
        STATE["capture"] = "active"

        # Remember the frontmost app + pid so the search panel can walk ITS window
        # for a form on demand. The panel becomes key once summoned, so a live
        # AXFocusedApplication would return the panel — we walk by pid instead.
        STATE["frontmost"] = {"app": app, "pid": pid, "ts": time.time()}
        # Keep a Chromium browser's web AX tree alive while it's frontmost. This is
        # just an attribute set (safe on-main), NOT the crashy tree walk — that runs
        # in the isolated subprocess. Chromium only exposes the tree while the client
        # that enabled it stays alive, so the long-lived daemon must hold it.
        if now_mono - self.last_field_check > 1:
            try:
                from . import form
                if browser.is_browser(app):
                    form.enable(pid)   # via the isolated helper — daemon never touches AX
            except Exception:  # noqa: BLE001
                pass

        # Cache the focused form field (1s cadence) for the single-field "Find mine".
        # Via the helper — the daemon must never call AX itself (Chromium segfaults).
        if now_mono - self.last_field_check > 1:
            self.last_field_check = now_mono
            try:
                from . import form
                field = form.focused()
                if field and field.get("app") not in (None, "Rewisp"):
                    STATE["last_field"] = {**field, "ts": time.time()}
            except Exception:  # helper unavailable — feature just stays off
                pass

        url = None
        reason = None

        if browser.is_browser(app):
            now = time.monotonic()
            if now - self.last_url_poll >= config.URL_POLL_SECONDS:
                self.last_url_poll = now
                url, tab_title, private = browser.active_tab(app)
                self.private_window = private
                if tab_title:
                    title = tab_title
                if url and url != self.last_url:
                    reason = "url"
                self.last_url = url
            else:
                url = self.last_url
            # Private/incognito window: capture fully pauses, like a kill-list
            # app. (Chromium reports mode; Safari relies on title keywords.)
            if self.private_window:
                STATE["capture"] = "killlist"
                return
        else:
            self.private_window = False

        if self.kill.blocks(app, title, url):
            if reason:
                log.info("kill list: blocked capture app=%s url=%s", app, url)
            STATE["capture"] = "killlist"
            return

        if app != self.last_app:
            reason = "app-switch"
        self.last_app = app

        # Scroll settle: scroll seen recently -> arm; quiet for SETTLE seconds -> fire once.
        s = screen.seconds_since_scroll()
        if s < config.TICK_SECONDS:
            self.scroll_pending = True
        elif self.scroll_pending and s >= config.SCROLL_SETTLE_SECONDS:
            self.scroll_pending = False
            reason = reason or "scroll-settle"

        # Heartbeat: dense pages (long reads, homework) change without any trigger
        # firing. Capture periodically; the dedupe layer drops unchanged screens.
        if not reason and now_mono - self.last_capture > config.HEARTBEAT_SECONDS:
            reason = "heartbeat"

        if reason:
            try:
                self.capture(app, pid, title, url, reason)
            except Exception:
                log.exception("capture error")

    def run(self) -> None:
        log.info("rewisp daemon starting (db=%s)", config.DB_PATH)
        # API and hotkey come up first so the UI works (and can explain the
        # permission state) even while capture is blocked on Screen Recording.
        from . import hotkey, server
        hotkey.start_listener()
        server.start()
        if not screen.has_screen_recording_permission():
            print(
                "\nRewisp needs Screen Recording permission to capture your screen.\n\n"
                "  1. Open System Settings > Privacy & Security > Screen & System Audio Recording\n"
                "  2. Enable it for the app Rewisp runs as (under launchd this is 'Python';\n"
                "     add /Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app\n"
                "     with the + button if it isn't listed)\n\n"
                "A system prompt may appear now — 'Allow' works too.\n"
                "Also enable the same app under Privacy & Security > Accessibility\n"
                "(needed for the Cmd+Option+P pause hotkey).\n"
                "Waiting for permission — the daemon will start capturing once granted.\n"
            )
            screen.request_screen_recording_permission()
            # Stay alive and poll rather than exiting: launchd KeepAlive would
            # otherwise restart-loop us, and the user may grant it any minute.
            while not screen.has_screen_recording_permission():
                time.sleep(30)
            log.info("screen recording permission granted, starting capture")
        # Wall clock, not monotonic: mach monotonic time PAUSES while the Mac
        # sleeps, so a monotonic 15-min throttle can defer the digest catch-up
        # for hours of real time after wake (observed 2026-07-08).
        last_retention = 0.0
        last_catchup = 0.0
        while True:
            self.tick()
            now = time.time()
            if now - last_retention > 86_400:
                last_retention = now
                deleted = db.run_retention(self.conn)
                log.info("retention: deleted %d captures, %d chats", *deleted)
                from . import export
                try:
                    export.backup(self.conn)
                except Exception:
                    log.exception("daily backup failed")
            # Digest catch-up: Mac slept through 9 PM -> run on next check.
            # Local check is free; digest.run() itself is guarded to once/day.
            if now - last_catchup > 900:
                last_catchup = now
                from . import digest
                if digest.catchup_due():
                    log.info("digest: catch-up triggered")
                    try:
                        digest.run()
                    except Exception:
                        log.exception("digest catch-up failed")
                # Due-day promise reminders (one pill per promise per day).
                try:
                    from . import promises
                    promises.remind_due(self.conn)
                except Exception:  # noqa: BLE001
                    log.exception("promise reminders failed")
                # Backfill embeddings + page_keys for old / offline-stored rows, a
                # chunk at a time so history is covered without a big stall.
                try:
                    n = db.embeddings_backfill(self.conn, batch=1000)
                    if n:
                        log.info("embed backfill: %d rows (%d remaining)",
                                 n, db.missing_embeddings(self.conn))
                    pk = db.pagekey_backfill(self.conn, batch=2000)
                    if pk:
                        log.info("page_key backfill: %d rows", pk)
                except Exception:
                    log.exception("backfill failed")
                # Dream Mode: consolidate days aged past the raw window into
                # episodes (extractive, local — no cloud call).
                try:
                    from . import dream
                    n_ep = dream.run_pending(self.conn)
                    if n_ep:
                        log.info("dream: wrote %d episodes", n_ep)
                except Exception:
                    log.exception("dream consolidation failed")
                # Due-day promise reminders (gated by the nudge setting, same as
                # Déjà Vu). One pill per promise per day via the topic cooldown.
                try:
                    if config.load_settings().get("nudges_enabled", False):
                        for p in db.due_promises(self.conn):
                            topic = f"promise:{p['id']}"
                            if db.nudge_topic_recent(self.conn, topic, hours=20):
                                continue
                            owed = "You said you'd" if p["who"] == "me" else "Someone owes you"
                            db.enqueue_nudge(self.conn, "promise", "Promise due",
                                             f"{owed}: {p['what']}", topic_key=topic)
                except Exception:
                    log.exception("promise due-check failed")
            time.sleep(config.TICK_SECONDS)


def main() -> None:
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(config.LOG_PATH), logging.StreamHandler()],
    )
    Daemon().run()
