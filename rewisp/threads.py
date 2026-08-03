"""Loose threads — the unfinished things, and how long they have been unfinished.

The digest has always written a list of loose ends. What it could never say is the
part that actually creates pressure: **this one has been open for four days.**

Each night's digest re-derives its threads from that day alone, so the same
unfinished thing reappears worded differently ("Gmail inbox untouched all day",
then "Gmail inbox opened but nothing appears to have been answered"). To a reader
those are the same thread; to string equality they are nothing alike. So matching
here is on the content words rather than the characters, which is what survives a
rewrite.

The age is the whole point. A loose end that showed up once is a note; one that has
survived five nightly reviews is a decision you keep not making, and it should look
different on the page. Everything is computed locally from summaries already
stored — no model call, no extra cloud call.
"""

import logging
import re
from datetime import datetime

from . import db

log = logging.getLogger("rewisp")

# How far back to look when ageing a thread. Six months of digests is the
# retention window for summaries, but a thread older than a few weeks has stopped
# being a loose end and become a fact of life.
MAX_LOOKBACK_DAYS = 30
# Two threads are "the same" at this OVERLAP COEFFICIENT of their content words
# — shared words over the size of the smaller set. Deliberately not character
# similarity (the digest rewords a thread nightly, so the characters move and the
# nouns do not), and deliberately not Jaccard: one night's thread is often a
# single clause and the next night's is three, which inflates the union and
# scores two identical concerns as unrelated.
SAME_THREAD = 0.50
# ...but overlap on a single shared word is a coincidence, not a match. This is
# what stops every thread mentioning "Amazon" from fusing into one.
MIN_SHARED_WORDS = 2

_BULLET = re.compile(r"^\s*[-*•]\s+")
# The digest sometimes marks a carry-over itself. Useful corroboration, but it is
# noise in the text the user reads, and the dates are computed here anyway.
_CARRIED = re.compile(r"\*?\(?\s*carried (?:over )?from [^)*]+\)?\*?\s*", re.I)
_MD = re.compile(r"[*_`]+")

_STOP = frozenset("""
a an the and or but of to in on at for from with without by as is are was were be
been being it its this that these those there here he she they them his her their
you your i my me we our not no still yet only just any some over into out up down
about after before during while than then so if when what which who whom whose
had has have do does did done get got make made take taken go goes went
""".split())


def parse(threads_md: str | None) -> list[str]:
    """Bullet list → clean thread lines, in order."""
    out: list[str] = []
    for raw in (threads_md or "").splitlines():
        line = raw.strip()
        if not _BULLET.match(line):
            continue
        line = _BULLET.sub("", line)
        line = _CARRIED.sub("", line).strip()
        if not line or line.lower().rstrip(".") in ("none", "none."):
            continue
        if len(line) < 8:
            continue
        out.append(line)
    return out


def _stem(w: str) -> str:
    """Crudest useful stemmer, and it earns its place.

    A thread written as "nothing answered" one night and "still unanswered" the
    next shares no token at all without this, so the two nights read as two
    separate loose ends and the age — the entire point of this module — comes out
    as 1. Same for untouched/touched, opened/open, models/model.

    Guarded so it only ever shortens a word that stays recognisable: no stripping
    below four characters, which keeps "under" and "until" intact, and no chopping
    a double-s ("address").
    """
    if w.startswith("un") and len(w) >= 6:
        w = w[2:]
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            if suffix == "s" and w.endswith("ss"):
                break
            return w[: -len(suffix)]
    return w


def _words(text: str) -> set[str]:
    """Content words — what a thread is *about*, once the wording is stripped."""
    plain = _MD.sub("", text.lower())
    return {_stem(w) for w in re.findall(r"[a-z0-9]{3,}", plain) if w not in _STOP}


def _same(a: set[str], b: set[str]) -> bool:
    """Overlap coefficient: shared words over the smaller set."""
    if not a or not b:
        return False
    shared = a & b
    if len(shared) < MIN_SHARED_WORDS:
        return False
    return len(shared) / min(len(a), len(b)) >= SAME_THREAD


def key_for(text: str) -> str:
    """Stable-ish identity for dismissal. The wording changes nightly, so this is
    the sorted content words rather than the sentence — a reworded thread the user
    already dismissed must stay dismissed."""
    return " ".join(sorted(_words(text)))[:200]


def _ensure_table(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS thread_state (
        key TEXT PRIMARY KEY,
        status TEXT,
        updated_at TEXT)""")
    conn.commit()


def dismiss(conn, text: str) -> str:
    """Mark a thread handled so it stops being surfaced. Keyed on content words,
    so tomorrow's rephrasing of the same thread stays dismissed too."""
    _ensure_table(conn)
    k = key_for(text)
    conn.execute("INSERT OR REPLACE INTO thread_state (key, status, updated_at) "
                 "VALUES (?, 'dismissed', ?)", (k, db.utcnow()))
    conn.commit()
    return k


def restore(conn, text: str) -> bool:
    """Undo a dismissal.

    Dismissal is keyed on meaning rather than wording, which is what makes it
    survive the digest rewriting a thread every night — and also what makes a
    mis-click expensive, because there is no wording to search for to get it
    back. Undo removes the key outright, so the thread reappears on the next
    read. Returns whether anything was actually undone.
    """
    _ensure_table(conn)
    # Match the way dismissal is APPLIED, not the way it was written. A key is
    # the exact stemmed word set, so deleting by key only works when undo is
    # handed back the identical sentence. Dismissal itself blocks by fuzzy
    # overlap, which means tomorrow's rewording of a thread stays hidden — and
    # an exact-key undo could never reach it, leaving the thread permanently
    # gone with nothing to type to get it back.
    w = _words(text)
    gone = [k for (k,) in conn.execute("SELECT key FROM thread_state WHERE status='dismissed'")
            if _same(w, set(k.split()))]
    if not gone:
        return False
    conn.executemany("DELETE FROM thread_state WHERE key = ?", [(k,) for k in gone])
    conn.commit()
    log.info("threads: restored %d dismissed thread(s)", len(gone))
    return True


def dismissed_keys(conn) -> list[set[str]]:
    _ensure_table(conn)
    return [set(k.split()) for (k,) in
            conn.execute("SELECT key FROM thread_state WHERE status='dismissed'")]


def open_threads(conn, limit: int = 8) -> list[dict]:
    """The latest digest's loose ends, aged against every digest before them.

    Returns [{text, first_seen, days_open, nights, key}] with the longest-running
    first — a thread that has survived five nightly reviews is more urgent than
    one written for the first time last night, and sorting by recency would bury
    exactly the wrong ones.
    """
    rows = conn.execute(
        "SELECT date, threads_md FROM summaries "
        "WHERE threads_md IS NOT NULL AND threads_md != '' "
        "ORDER BY date DESC LIMIT ?", (MAX_LOOKBACK_DAYS,)).fetchall()
    if not rows:
        return []

    latest_date, latest_md = rows[0]
    current = parse(latest_md)
    if not current:
        return []

    history = [(d, [(t, _words(t)) for t in parse(md)]) for d, md in rows[1:]]
    skip = dismissed_keys(conn)

    out: list[dict] = []
    for text in current:
        w = _words(text)
        if any(_same(w, d) for d in skip):
            continue
        first_seen, nights = latest_date, 1
        # Walk backwards only while the thread keeps appearing. A gap means it was
        # resolved and came back, which is a new thread, not a longer-running one.
        for day, entries in history:
            if any(_same(w, hw) for _t, hw in entries):
                first_seen, nights = day, nights + 1
            else:
                break
        out.append({
            "text": text,
            "first_seen": first_seen,
            "days_open": _days_between(first_seen, latest_date) + 1,
            "nights": nights,
            "key": key_for(text),
        })

    out.sort(key=lambda t: (-t["days_open"], -t["nights"]))
    return out[:limit]


def _days_between(a: str, b: str) -> int:
    try:
        return abs((datetime.strptime(b, "%Y-%m-%d")
                    - datetime.strptime(a, "%Y-%m-%d")).days)
    except (ValueError, TypeError):
        return 0
