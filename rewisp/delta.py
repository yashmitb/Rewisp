"""Delta Memory — "what changed on this page since last time?"

Rewisp already stores every version of a page as text. This diffs two versions
of the same page (identified by page_key) at the line level, fuzzily (OCR is
noisy), ignoring churn like clocks and counters.

Also home of `page_key`: a stable identity for a page/screen, shared with feature
#6 (Numbers Over Time). Web = normalized URL; apps = app + normalized title.
"""

import json
import re
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit

from . import config

# Lines matching any of these are ignored on both sides — pure churn that would
# otherwise drown the real diff. Hot-reloadable via ~/Rewisp/delta_ignore.json.
DEFAULT_IGNORE = [
    r"^\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?$",   # clocks
    r"^\d{1,3}%$",                             # bare percentages (progress bars)
    r"^[•·]?\s*\d+\s*(views?|comments?|likes?|new|unread|notifications?)$",
    r"^\(\d+\)$",                              # bare counters like "(3)"
    r"^\d{1,2}/\d{1,2}/\d{2,4}$",              # dates alone
    r"^page \d+ of \d+$",
]

_TITLE_COUNTER = re.compile(r"\s*[\(\[]\s*\d+\s*[\)\]]\s*$")   # "Inbox (3)"
_LEADING_COUNT = re.compile(r"^\s*[\(\[]?\d+[\)\]]?\s+")        # "(3) Inbox"

# Menu-bar / browser chrome vocabulary. OCR reads the menu bar on every frame
# ("Dia File Edit View Tabs Bookmarks History … Help 21% Sun Jul 14"), and those
# lines otherwise show up as added/removed rows in every diff. A line with 3+
# of these words is chrome, not content.
_CHROME_WORDS = frozenset(
    "file edit view tabs tab bookmarks bookmark history extensions extension "
    "window help format selection develop favorites menu toolbar profiles "
    "run go terminal dock mon tue wed thu fri sat sun jan feb mar apr may jun "
    "jul aug sep oct nov dec".split())


def _is_chrome(line: str) -> bool:
    toks = re.findall(r"[a-z]+", line.lower())
    if not toks:
        return False
    return sum(1 for t in toks if t in _CHROME_WORDS) >= 3


def page_key(app: str | None, window_title: str | None, url: str | None) -> str:
    """Stable identity for a page/screen across time.

    Web: scheme://host/path, lowercased, query + fragment stripped (so a Canvas
    page is 'the same page' whether or not it carries a session token). Apps:
    'app::normalized-title' with notification counters stripped."""
    if url:
        try:
            s = urlsplit(url.strip())
            if s.scheme in ("http", "https") and s.netloc:
                path = s.path.rstrip("/") or "/"
                return urlunsplit((s.scheme.lower(), s.netloc.lower(), path, "", "")).lower()
        except ValueError:
            pass
    title = (window_title or "").strip()
    title = _TITLE_COUNTER.sub("", title)
    title = _LEADING_COUNT.sub("", title)
    title = re.sub(r"\s+", " ", title).strip().lower()
    app = (app or "").strip().lower()
    return f"{app}::{title}" if title else app


def _ignore_patterns() -> list[re.Pattern]:
    pats = list(DEFAULT_IGNORE)
    f = config.DATA_DIR / "delta_ignore.json"
    if f.exists():
        try:
            pats += list(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return [re.compile(p, re.I) for p in pats]


def _clean_lines(text: str) -> list[str]:
    """Split into meaningful lines: collapse whitespace, drop blanks, drop
    lines that match an ignore pattern (clocks, counters, ad slots)."""
    ignore = _ignore_patterns()
    out = []
    for raw in text.splitlines():
        ln = re.sub(r"\s+", " ", raw).strip()
        if len(ln) < 3:
            continue
        if any(p.match(ln) for p in ignore) or _is_chrome(ln):
            continue
        out.append(ln)
    return out


_NUM = re.compile(r"-?\$?\d[\d,]*\.?\d*%?")


def _is_ocr_noise(a: str, b: str) -> bool:
    """True when two lines differ only by OCR jitter, not a real edit.

    The line-level ratio alone can't tell 'the quick brown fox' -> 'the qulck
    brown f0x' (noise) from 'the quick brown fox' -> 'the quick red fox' (a real
    word change): both can land in the 0.6-0.9 band. This looks word by word:
    same number of words, identical numbers, and every aligned word either equal
    or a close variant (a short OCR slip, ratio >= 0.75). A real edit adds/removes
    a word, changes a number, or swaps in a genuinely different word — all of
    which fail here and stay classified as a change."""
    if _numbers(a) != _numbers(b):
        return False                       # a changed number is always a real change
    wa, wb = a.lower().split(), b.lower().split()
    if len(wa) != len(wb) or not wa:
        return False                       # words added/removed = real change
    return all(x == y or SequenceMatcher(None, x, y).ratio() >= 0.75
               for x, y in zip(wa, wb))


def diff_texts(old: str, new: str) -> dict:
    """Line-level fuzzy diff. Two lines count as the same when their similarity
    ratio > 0.9 (OCR jitter); a 0.6-0.9 near-match is a *changed* line — unless it
    is only OCR noise (see _is_ocr_noise); everything else is added/removed.
    Returns {added:[], removed:[], changed:[{old,new}]}."""
    o = _clean_lines(old)
    n = _clean_lines(new)
    used: set[int] = set()
    added: list[str] = []
    changed: list[dict] = []
    for nl in n:
        best_r, best_i = 0.0, -1
        for i, ol in enumerate(o):
            if i in used:
                continue
            r = SequenceMatcher(None, ol.lower(), nl.lower()).ratio()
            if r > best_r:
                best_r, best_i = r, i
        if best_i < 0 or best_r < 0.6:
            added.append(nl)                    # no line is close enough: it's new
            continue
        ol = o[best_i]
        used.add(best_i)
        # One decision for every matched line: is the difference a real edit, or
        # just the same line read differently? _is_ocr_noise handles both the
        # near-identical case (a changed number in an otherwise-equal line is real;
        # pure jitter is not) and the high-ratio case a single word swap hides in
        # ('brown' -> 'red' in a long line barely dents the char ratio but is a
        # real change).
        if not _is_ocr_noise(ol, nl):
            changed.append({"old": ol, "new": nl})
    removed = [ol for i, ol in enumerate(o) if i not in used]
    return {"added": added, "removed": removed, "changed": changed}


def _numbers(line: str) -> list[str]:
    return _NUM.findall(line)


def summarize(diff: dict) -> str:
    """One-line headline for the structured answer's ANSWER field."""
    a, r, c = len(diff["added"]), len(diff["removed"]), len(diff["changed"])
    if not (a or r or c):
        return "Nothing changed on this page."
    bits = []
    if a:
        bits.append(f"{a} added")
    if c:
        bits.append(f"{c} changed")
    if r:
        bits.append(f"{r} removed")
    return "This page changed: " + ", ".join(bits) + "."


def changed_ratio(diff: dict, new_line_count: int) -> float:
    """Fraction of lines that changed vs the new version — drives the passive
    'this page changed a lot' nudge (>0.30) once the nudge pill exists."""
    if new_line_count <= 0:
        return 0.0
    return (len(diff["added"]) + len(diff["changed"])) / new_line_count
