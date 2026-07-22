"""Digest: THE one automated Claude call per day. Runs at 9 PM via launchd; the daemon
also runs a catch-up check (local, free) in case the Mac slept through 9 PM.

Input assembled locally: day's captures (deduped, grouped by hour+app), day's chats,
yesterday's open threads. Output: daily summary, loose threads, subtext notes,
memory proposals (Pending only), plus a locally computed time report."""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import config, db, memory
from .ask import call_llm

log = logging.getLogger("rewisp")

DIGEST_STATE = config.DATA_DIR / "digest_state.json"
DIGEST_LOG = config.DATA_DIR / "digest_log.jsonl"
MAX_INPUT_CHARS = 60_000  # truncate locally rather than making multiple calls

PROMPT_RULES = """You are Rewisp's nightly digest. Analyze the user's day from his own screen
history below. Answer ONLY from the provided context; do not invent events.
Return EXACTLY these four markdown sections:

## Summary
What the user worked on, read, and decided today. Short paragraphs, concrete.

## Threads
Loose/unfinished things: emails opened but not replied to, applications started but not
finished, tasks/tabs abandoned. Carry over any still-unresolved threads from yesterday's
list. One bullet each. If none, write "None."

## Subtext
For important emails/messages seen on screen today, one short tone/meaning note each
(e.g. "this rejection leaves the door open"). If none, write "None."

## Memory proposals
Durable facts or preferences about the user learned from today (especially his chat
questions). Only things worth remembering for months. One bullet each, no speculation.
If none, write "None."
"""


def _local_day_bounds(day: datetime) -> tuple[str, str]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    fmt = "%Y-%m-%d %H:%M:%S"
    return (start.astimezone(timezone.utc).strftime(fmt),
            end.astimezone(timezone.utc).strftime(fmt))


def compress_captures(rows: list, per_topic_lines: int = 30) -> str:
    """Cluster the day by topic (page_key), not by clock hour, and order topics by
    how much unique content each carried. Local, free.

    The old layout bucketed by (hour, app): a task you returned to all day was
    scattered across every hour it touched, and because build_input truncates at a
    fixed budget, a busy day lost its whole evening to the cut. Grouping by
    page_key collapses each topic into one block regardless of when you visited it,
    global line-dedup removes the redundancy a revisited page produces, and
    ordering by unique-line count means the budget is spent on the substantive
    topics first — a page refreshed 50 times but carrying little text sinks, and
    truncation drops the least, not the latest.
    """
    from . import delta
    groups: dict = {}
    order: list = []                              # preserve first-seen order for ties
    seen_lines: set = set()
    for ts, app, title, url, text in rows:
        pk = delta.page_key(app, title, url) or (app or "misc")
        g = groups.get(pk)
        if g is None:
            g = groups[pk] = {"app": app, "head": url or title or "",
                              "first": ts, "last": ts, "count": 0, "lines": []}
            order.append(pk)
        g["last"] = ts
        g["count"] += 1
        if not g["app"]:
            g["app"] = app
        if not g["head"]:
            g["head"] = url or title or ""
        for line in text.splitlines():
            s = line.strip()
            key = s.lower()
            if len(key) < 4 or key in seen_lines:
                continue
            seen_lines.add(key)
            g["lines"].append(s)
    # Richest topics first (most unique content), ties by when first seen.
    ranked = sorted(order, key=lambda pk: (-len(groups[pk]["lines"]),
                                           groups[pk]["first"]))
    parts = []
    for pk in ranked:
        g = groups[pk]
        if not g["lines"] and not g["head"]:
            continue
        span = f"{g['first'][11:16]}–{g['last'][11:16]} UTC"
        label = g["head"] or g["app"] or pk
        parts.append(f"### {label} — {g['app']}, {g['count']}× , {span}")
        parts.extend(g["lines"][:per_topic_lines])
    return "\n".join(parts)


def build_input(conn, day: datetime) -> str:
    since, until = _local_day_bounds(day)
    caps = conn.execute(
        "SELECT ts, app, window_title, url, ocr_text FROM captures "
        "WHERE ts >= ? AND ts < ? ORDER BY ts", (since, until)).fetchall()
    chats = conn.execute(
        "SELECT ts, role, content FROM chats WHERE ts >= ? AND ts < ? ORDER BY ts",
        (since, until)).fetchall()
    prev = conn.execute(
        "SELECT date, threads_md FROM summaries WHERE date < ? ORDER BY date DESC LIMIT 1",
        (day.strftime("%Y-%m-%d"),)).fetchone()

    parts = [f"# Screen history for {day.strftime('%Y-%m-%d %A')} (times UTC, user is "
             f"{datetime.now().astimezone().tzname()})",
             compress_captures(caps) or "(no captures today)"]
    if chats:
        parts.append("# Today's Ask conversations")
        parts.extend(f"[{r}] {c[:500]}" for _, r, c in chats)
    if prev and prev[1]:
        parts.append(f"# Open threads from {prev[0]}\n{prev[1]}")
    text = "\n\n".join(parts)
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS] + "\n\n[truncated locally to stay within one call]"
    return text


def compute_time_report(conn, day: datetime) -> dict:
    """App time breakdown from capture timestamps. Gap between consecutive captures
    attributed to the earlier capture's app, capped at 5 min. Local, no AI."""
    since, until = _local_day_bounds(day)
    rows = conn.execute("SELECT ts, app FROM captures WHERE ts >= ? AND ts < ? ORDER BY ts",
                        (since, until)).fetchall()
    seconds: dict = defaultdict(float)
    fmt = "%Y-%m-%d %H:%M:%S"
    for (ts1, app), (ts2, _) in zip(rows, rows[1:]):
        gap = (datetime.strptime(ts2, fmt) - datetime.strptime(ts1, fmt)).total_seconds()
        seconds[app] += min(gap, 300)
    return {app: round(s / 60) for app, s in
            sorted(seconds.items(), key=lambda kv: -kv[1])}


def parse_sections(answer: str) -> dict:
    out = {}
    for name in ("Summary", "Threads", "Subtext", "Memory proposals"):
        m = re.search(rf"## {name}\s*\n(.*?)(?=\n## |\Z)", answer, re.DOTALL)
        out[name] = m.group(1).strip() if m else ""
    return out


def last_run_date() -> str | None:
    if DIGEST_STATE.exists():
        try:
            return json.loads(DIGEST_STATE.read_text()).get("last_run_date")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def already_ran(date_str: str) -> bool:
    return last_run_date() == date_str


def _state() -> dict:
    if DIGEST_STATE.exists():
        try:
            return json.loads(DIGEST_STATE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _record_failure(date_str: str) -> None:
    s = _state()
    s["last_fail_ts"] = db.utcnow()
    s["fail_date"] = date_str
    DIGEST_STATE.write_text(json.dumps(s))


def _in_backoff(now: datetime) -> bool:
    """True within 30 min of the last failed attempt — retry soon, not every tick."""
    ts = _state().get("last_fail_ts")
    if not ts:
        return False
    try:
        last = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (now.astimezone(timezone.utc) - last).total_seconds() < 1800


def _interval_elapsed(now: datetime) -> bool:
    """Respect the user's digest frequency (Settings): nightly / every N days."""
    last = last_run_date()
    if last is None:
        return True
    days = (now.date() - datetime.strptime(last, "%Y-%m-%d").date()).days
    return days >= int(config.load_settings().get("digest_interval_days", 1))


def run(day: datetime | None = None, force: bool = False) -> dict | None:
    """Run the digest for `day` (default: today, local). One Claude call."""
    day = day or datetime.now().astimezone()
    date_str = day.strftime("%Y-%m-%d")
    if not force and (already_ran(date_str) or not _interval_elapsed(day)):
        log.info("digest: not due for %s (ran %s, every %s day(s)), skipping",
                 date_str, last_run_date(),
                 config.load_settings().get("digest_interval_days", 1))
        return None

    conn = db.connect()
    text = build_input(conn, day)
    # A whole day of screen text, going to a cloud engine. Highest-volume path
    # for attacker-controlled content in the app, so it gets the same treatment.
    from . import sanitize
    fence = sanitize.new_fence()
    prompt = (f"{PROMPT_RULES}\n\n{sanitize.TRUST_NOTICE}\n\n"
              f"# CAPTURED [begin {fence}]\n{sanitize.scrub(text, fence)}\n"
              f"[end {fence}]")
    log.info("digest: calling engine chain for %s (%d chars input)", date_str, len(prompt))
    # Engine CHAIN, not Claude-only: when Claude's session limit is hit at 9 PM
    # the digest used to fail all night even with Gemini available. Still exactly
    # one cloud call — whichever engine answers first. On total failure, record it
    # so the catch-up loop backs off (30 min) instead of hammering a rate limit,
    # then runs the digest as soon as an engine responds.
    try:
        answer, engine = call_llm(prompt)
    except Exception:
        _record_failure(date_str)
        raise
    log.info("digest: answered by %s", engine)
    sections = parse_sections(answer)
    time_report = compute_time_report(conn, day)

    # "About to fade" — the forgetting model's rescue slot. Computed locally
    # (no cloud), one mention per wisp ever, appended to the digest summary at
    # the moment spaced-repetition science says a reminder works best: right
    # before the memory crosses your predicted forgetting cliff.
    fade_md = ""
    try:
        from . import forgetting
        fading = forgetting.about_to_fade(conn, limit=2)
        if fading:
            lines = [f"- {f['snippet'][:120]} — seen in {f['app']}, {f['ts'][:10]}"
                     for f in fading]
            fade_md = "\n\n### About to fade\n" + "\n".join(lines)
            forgetting.mark_rescued(conn, [f["wisp_id"] for f in fading])
    except Exception:  # noqa: BLE001 — rescue is a bonus, never breaks the digest
        log.exception("about-to-fade failed")

    conn.execute(
        "INSERT INTO summaries (date, summary_md, threads_md, time_report_json) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(date) DO UPDATE SET summary_md=excluded.summary_md, "
        "threads_md=excluded.threads_md, time_report_json=excluded.time_report_json",
        (date_str,
         sections["Summary"] + ("\n\n### Subtext\n" + sections["Subtext"]
                                if sections["Subtext"] not in ("", "None.") else "")
         + fade_md,
         sections["Threads"],
         json.dumps(time_report)))
    conn.commit()

    proposals = [ln[2:].strip() for ln in sections["Memory proposals"].splitlines()
                 if ln.startswith("- ") and ln[2:].strip().lower() != "none."]
    n_added = memory.add_pending(proposals)

    DIGEST_STATE.write_text(json.dumps({"last_run_date": date_str}))
    with DIGEST_LOG.open("a") as f:
        f.write(json.dumps({"date": date_str, "ts": db.utcnow(),
                            "input_chars": len(prompt), "output_chars": len(answer),
                            "memory_proposals": n_added}) + "\n")
    log.info("digest: done for %s (%d memory proposals)", date_str, n_added)
    return {"date": date_str, "sections": sections, "time_report": time_report,
            "memory_proposals": n_added}


def catchup_due() -> bool:
    """True if it's past the configured digest hour and one is due (frequency-aware).
    Local check, free."""
    now = datetime.now().astimezone()
    hour = int(config.load_settings().get("digest_hour", 21))
    return (now.hour >= hour and not already_ran(now.strftime("%Y-%m-%d"))
            and _interval_elapsed(now) and not _in_backoff(now))


def calls_this_month() -> int:
    if not DIGEST_LOG.exists():
        return 0
    month = datetime.now().strftime("%Y-%m")
    return sum(1 for line in DIGEST_LOG.read_text().splitlines()
               if json.loads(line).get("date", "").startswith(month))
