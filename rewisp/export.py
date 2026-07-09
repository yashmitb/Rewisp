"""Export everything human-readable to ~/Rewisp/export/: daily summaries,
memory, chat history (markdown), captures (CSV). Local files only."""

import csv
import json
import logging
import shutil
from datetime import datetime

from . import config, db

log = logging.getLogger("rewisp")

EXPORT_DIR = config.DATA_DIR / "export"


def run(conn=None) -> dict:
    conn = conn or db.connect()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}

    # summaries.md — every digest ever, newest first
    rows = conn.execute(
        "SELECT date, summary_md, threads_md, time_report_json FROM summaries "
        "ORDER BY date DESC").fetchall()
    parts = ["# Rewisp — daily summaries\n"]
    for date, summary, threads, report_json in rows:
        parts.append(f"\n## {date}\n\n{summary or '(no summary)'}")
        if threads and threads.strip() not in ("", "None."):
            parts.append(f"\n### Loose threads\n{threads}")
        if report_json:
            report = json.loads(report_json)
            top = sorted(report.items(), key=lambda kv: -kv[1])[:8]
            if top:
                parts.append("\n### Time\n" + "\n".join(
                    f"- {app}: {m} min" for app, m in top if m > 0))
    (EXPORT_DIR / "summaries.md").write_text("\n".join(parts) + "\n")
    counts["summaries"] = len(rows)

    # chats.md
    rows = conn.execute("SELECT ts, role, content FROM chats ORDER BY id").fetchall()
    parts = ["# Rewisp — ask history\n"]
    for ts, role, content in rows:
        prefix = "**You:**" if role == "user" else "**Rewisp:**"
        parts.append(f"\n{prefix} {content}\n<sub>{ts} UTC</sub>")
    (EXPORT_DIR / "chats.md").write_text("\n".join(parts) + "\n")
    counts["chats"] = len(rows)

    # captures.csv — the raw memory, for grep/spreadsheets
    rows = conn.execute(
        "SELECT ts, app, window_title, url, ocr_text FROM captures ORDER BY id").fetchall()
    with (EXPORT_DIR / "captures.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_utc", "app", "window_title", "url", "text"])
        w.writerows(rows)
    counts["captures"] = len(rows)

    # memory.md — straight copy
    if config.MEMORY_PATH.exists():
        shutil.copy(config.MEMORY_PATH, EXPORT_DIR / "memory.md")
        counts["memory"] = 1

    log.info("export: %s -> %s", counts, EXPORT_DIR)
    return {"path": str(EXPORT_DIR), **counts}


def backup(conn=None) -> None:
    """Daily safety net: summaries + memory only (small, precious). Runs from
    the daemon's daily tick; full export stays user-triggered."""
    conn = conn or db.connect()
    bdir = EXPORT_DIR / "backup"
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT date, summary_md, threads_md FROM summaries ORDER BY date").fetchall()
    (bdir / f"summaries-{stamp}.md").write_text("\n\n".join(
        f"## {d}\n{s or ''}\n### Threads\n{t or ''}" for d, s, t in rows) or "(none)")
    if config.MEMORY_PATH.exists():
        shutil.copy(config.MEMORY_PATH, bdir / f"memory-{stamp}.md")
    # keep last 14 backups of each
    for pattern in ("summaries-*.md", "memory-*.md"):
        old = sorted(bdir.glob(pattern))[:-14]
        for p in old:
            p.unlink()


def weekly_report(conn=None) -> dict:
    """Last 7 days of per-app minutes: stored digests + live compute for today."""
    conn = conn or db.connect()
    from . import digest
    days = {}
    rows = conn.execute(
        "SELECT date, time_report_json FROM summaries "
        "WHERE date >= date('now', 'localtime', '-6 days') ORDER BY date").fetchall()
    for date, report_json in rows:
        if report_json:
            days[date] = json.loads(report_json)
    today = datetime.now().astimezone()
    days[today.strftime("%Y-%m-%d")] = digest.compute_time_report(conn, today)
    totals: dict = {}
    for report in days.values():
        for app, m in report.items():
            totals[app] = totals.get(app, 0) + m
    return {"days": days,
            "totals": dict(sorted(totals.items(), key=lambda kv: -kv[1]))}
