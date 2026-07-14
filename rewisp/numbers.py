"""Numbers Over Time — passively track any number you see repeatedly.

A weight in an app, a grade on Canvas, a price, tracked hours. Rewisp sees the
same `label + number` on the same page over and over; store the series and chart
it. "How has my weight moved?" -> a sparkline from your own screen history. No
integrations — the screen is the API.

Detection is a cheap regex per capture. A label+number only becomes a real
*series* once the same key shows up >= 3 times with different timestamps and some
variance (filters static numbers like footer years). Credential-shaped numbers are
refused (same spirit as the Vault).
"""

import logging
import re

from . import db

log = logging.getLogger("rewisp")

# label (letters/spaces) then optional colon, optional currency, the number,
# optional unit. Tuned for "Weight 154.2 lbs", "Balance: $1,240.50", "Grade 92%".
_PAIR = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z ]{2,28}?)\s*[:=]?\s*"
    r"(?P<cur>[$€£])?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|kg|lbs?|hrs?|hours?|mins?|GB|MB|pts?|points?)?")

_CRED_LABEL = re.compile(r"\b(card|cvv|cvc|ssn|pin|password|passcode|otp|code|account|routing|phone|zip|id)\b", re.I)


def _norm_label(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()[:40]


def _looks_like_id(num_str: str, value: float) -> bool:
    digits = re.sub(r"[^\d]", "", num_str)
    if len(digits) >= 7:                       # long int = id / phone / card
        return True
    if "." not in num_str and 1900 <= value <= 2100:   # bare year
        return True
    return False


def detect(text: str) -> list[dict]:
    """Extract label+number observations from a block of text."""
    out: list[dict] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) < 4 or len(line) > 120:
            continue
        for m in _PAIR.finditer(line):
            label = m.group("label").strip()
            if len(label) < 3 or _CRED_LABEL.search(label):
                continue
            num_str = m.group("num")
            try:
                value = float(num_str.replace(",", ""))
            except ValueError:
                continue
            if _looks_like_id(num_str, value):
                continue
            unit = m.group("unit") or m.group("cur") or ""
            klabel = _norm_label(label)
            if klabel in seen:
                continue
            seen.add(klabel)
            out.append({"label": label.strip(), "value": value,
                        "unit": unit, "key_label": klabel})
    return out


def scan_and_store(conn, wisp_id: int, page_key: str, text: str,
                   max_per_capture: int = 8) -> int:
    """Store observations for this capture. Dedups the same key+value seen again
    within ~a day (a static number that keeps appearing shouldn't pile up rows)."""
    if not page_key:
        return 0
    found = detect(text)[:max_per_capture]
    added = 0
    for p in found:
        key = f"{page_key}::{p['key_label']}"
        dup = conn.execute(
            "SELECT 1 FROM series WHERE key=? AND value=? AND ts >= datetime('now','-1 day') LIMIT 1",
            (key, p["value"])).fetchone()
        if dup:
            continue
        conn.execute(
            "INSERT INTO series (key, label, value, unit, ts, wisp_id) VALUES (?, ?, ?, ?, ?, ?)",
            (key, p["label"], p["value"], p["unit"], db.utcnow(), wisp_id))
        added += 1
    if added:
        conn.commit()
    return added


def _promoted(conn) -> list[str]:
    """Keys that qualify as a real series: >= 3 observations at distinct times,
    and not all the same value (some variance)."""
    rows = conn.execute(
        "SELECT key, COUNT(DISTINCT ts) n, MIN(value) mn, MAX(value) mx "
        "FROM series GROUP BY key HAVING n >= 3 AND mx > mn").fetchall()
    return [r[0] for r in rows]


def series_points(conn, key: str) -> list[dict]:
    cols = ["value", "unit", "ts"]
    return [dict(zip(cols, r)) for r in conn.execute(
        "SELECT value, unit, ts FROM series WHERE key=? ORDER BY ts ASC", (key,))]


def active_series(conn, limit: int = 5) -> list[dict]:
    """Promoted series with their latest value + label, most-recently-seen first."""
    out = []
    for key in _promoted(conn):
        pts = series_points(conn, key)
        label = conn.execute("SELECT label FROM series WHERE key=? ORDER BY ts DESC LIMIT 1",
                             (key,)).fetchone()[0]
        out.append({"key": key, "label": label, "unit": pts[-1]["unit"],
                    "current": pts[-1]["value"], "first": pts[0]["value"],
                    "n": len(pts), "last_ts": pts[-1]["ts"], "points": [p["value"] for p in pts]})
    out.sort(key=lambda s: s["last_ts"], reverse=True)
    return out[:limit]


def lookup(conn, question: str) -> dict | None:
    """Match a 'how has X moved/changed/trended' question to a promoted series."""
    if not re.search(r"\b(how (has|have|much)|trend|over time|moved|changed|progress|history) \b", question, re.I) \
       and not re.search(r"\b(my|the)\b.*\b(weight|grade|score|price|balance|hours|streak)\b", question, re.I):
        return None
    q = _norm_label(re.sub(r"[^a-zA-Z ]", " ", question))
    qwords = set(q.split())
    best = None
    for s in active_series(conn, limit=50):
        lw = set(_norm_label(s["label"]).split())
        overlap = len(qwords & lw)
        if overlap and (best is None or overlap > best[0]):
            best = (overlap, s)
    if not best:
        return None
    s = best[1]
    delta = s["current"] - s["first"]
    unit = s["unit"]
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    answer = (f"{s['label'].strip().capitalize()}: {_fmt(s['current'], unit)} now "
              f"({arrow} {_fmt(abs(delta), unit)} from {_fmt(s['first'], unit)}, "
              f"over {s['n']} readings).")
    spark = " ".join(_fmt(v, unit) for v in s["points"][-8:])
    return {"answer": answer, "detail": f"Recent: {spark}", "source": "Numbers over time",
            "copy_text": answer, "model": "Series", "series": s}


def _fmt(v: float, unit: str) -> str:
    if unit in ("$", "€", "£"):
        return f"{unit}{v:,.2f}"
    n = f"{v:g}"
    return f"{n}{unit}" if unit else n
