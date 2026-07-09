"""CLI: python3 -m rewisp [daemon|once|pause|resume|status|search <q>|ask <q>|digest [--force]|vault|memory|export|report]"""

import sys

from . import config, db


def cmd_daemon():
    from . import daemon
    daemon.main()


def cmd_once():
    """Single test capture of the current screen, printed and stored."""
    from . import browser, screen
    if not screen.has_screen_recording_permission():
        print("Screen Recording permission missing — grant it in System Settings.")
        screen.request_screen_recording_permission()
        return
    app, pid = screen.frontmost_app()
    title = screen.frontmost_window_title(pid)
    url = None
    if browser.is_browser(app):
        url, tab_title, _private = browser.active_tab(app)
        title = tab_title or title
    img = screen.capture_frontmost_display(pid)
    text = screen.ocr_cgimage(img)
    del img
    conn = db.connect()
    row_id = db.insert_capture(conn, app, title, url, text)
    print(f"capture #{row_id}  app={app}  title={title!r}  url={url}")
    print(f"--- OCR ({len(text)} chars) ---")
    print(text[:1500])


def cmd_pause():
    config.ensure_dirs()
    config.PAUSE_FLAG.touch()
    print("capture paused")


def cmd_resume():
    config.PAUSE_FLAG.unlink(missing_ok=True)
    print("capture resumed")


def cmd_status():
    conn = db.connect()
    n, = conn.execute("SELECT COUNT(*) FROM captures").fetchone()
    oldest, = conn.execute("SELECT MIN(ts) FROM captures").fetchone()
    latest, = conn.execute("SELECT MAX(ts) FROM captures").fetchone()
    size_mb = config.DB_PATH.stat().st_size / 1e6 if config.DB_PATH.exists() else 0
    paused = config.PAUSE_FLAG.exists()
    print(f"captures: {n}   oldest: {oldest}   latest: {latest}")
    print(f"db: {config.DB_PATH} ({size_mb:.1f} MB)   paused: {paused}")


def cmd_search(query: str):
    conn = db.connect()
    rows = db.search_captures(conn, query, limit=10)
    if not rows:
        print("no matches")
        return
    for r in rows:
        print(f"#{r['id']}  {r['ts']}Z  {r['app']}  {r['url'] or r['window_title'] or ''}")
        print(f"    {r['snippet']}")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "daemon"
    if cmd == "daemon":
        cmd_daemon()
    elif cmd == "once":
        cmd_once()
    elif cmd == "pause":
        cmd_pause()
    elif cmd == "resume":
        cmd_resume()
    elif cmd == "status":
        cmd_status()
    elif cmd == "search" and len(args) > 1:
        cmd_search(" ".join(args[1:]))
    elif cmd == "ask" and len(args) > 1:
        from . import ask as ask_mod
        question = " ".join(args[1:])
        answer, meta = ask_mod.ask(question)
        window = f"{meta['since']} .. {meta['until']}" if meta.get("since") else "all time"
        print(f"[{meta.get('n_captures', 0)} captures matched, window: {window}]\n")
        print(answer)
    elif cmd == "digest":
        from . import digest
        result = digest.run(force="--force" in args)
        if result is None:
            print("digest already ran today (use --force to rerun)")
        else:
            print(f"digest done for {result['date']}: "
                  f"{result['memory_proposals']} memory proposals, "
                  f"time report: {result['time_report']}")
            print(f"\n{result['sections']['Summary'][:800]}")
        print(f"\ndigest calls this month: {digest.calls_this_month()}")
    elif cmd == "vault":
        from . import vault
        r = vault.reindex()
        print(f"vault: {r['indexed']} indexed, {r['removed']} removed")
        for path, reason in r["refused"]:
            print(f"  REFUSED {path}: looks like it contains a {reason} — "
                  "never store credentials in the Vault")
    elif cmd == "export":
        from . import export
        r = export.run()
        print(f"exported to {r['path']}: {r.get('summaries', 0)} summaries, "
              f"{r.get('chats', 0)} chat lines, {r.get('captures', 0)} captures")
    elif cmd == "report":
        from . import export
        r = export.weekly_report()
        print("last 7 days, minutes per app:")
        for app, m in list(r["totals"].items())[:12]:
            if m > 0:
                print(f"  {app:<24} {m:>5}  {'█' * min(m // 15, 40)}")
    elif cmd == "memory":
        from . import memory
        confirmed, pending = memory.read_sections()
        print(f"Confirmed ({len(confirmed)}):")
        for c in confirmed:
            print(f"  - {c}")
        print(f"Pending ({len(pending)}) — edit ~/Rewisp/memory.md to approve/delete:")
        for p in pending:
            print(f"  - {p}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
