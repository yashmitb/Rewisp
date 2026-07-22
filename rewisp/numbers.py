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

# Menu-bar / window chrome — OCR reads it every frame and the battery % rides
# along, so "…History Extensions Window Help 49%" would become a bogus series.
_CHROME_LABEL = re.compile(
    r"\b(file|edit|view|tabs?|bookmarks?|history|extensions?|window|help|"
    r"format|selection|develop|terminal|toolbar|menu|favorites?|profiles?|"
    r"thought|episode|season|sonnet|opus|haiku|gpt|claude|version|chapter)\b", re.I)

# A number is tracked only if its LABEL *is* a personal metric — not merely
# contains a metric-ish word. The old "has a unit OR a metric word" gate promoted
# ad prices ("up to $20"), file sizes ("jpeg 11MB"), progress bars ("checkpoint
# 31%"), and drive usage ("ve used 99%"). Precision-first: the label, stripped of
# modifiers, must consist ENTIRELY of known metric words. Money/price/count
# metrics are excluded on purpose — they're indistinguishable from ad/UI noise on
# the open web.
_METRIC_WORDS = {
    "weight", "bodyweight", "bmi", "grade", "gpa", "score", "sleep", "streak",
    "steps", "step", "calorie", "calories", "cal", "cals", "kcal", "macros",
    "protein", "carbs", "heart", "rate", "bpm", "pulse", "hydration", "hrv",
    "spo2", "rank", "elo", "rating", "level", "reps", "sets", "pace", "mileage",
    "temperature", "temp", "streaks",
}
_METRIC_MODIFIERS = {
    "my", "the", "your", "our", "current", "total", "today", "todays", "now",
    "this", "week", "weekly", "daily", "avg", "average", "resting", "max", "min",
    "goal", "value", "latest", "so", "far",
}


def _is_metric_label(label: str) -> bool:
    words = re.findall(r"[a-z]+", label.lower())
    content = [w for w in words if w not in _METRIC_MODIFIERS]
    return bool(content) and all(w in _METRIC_WORDS for w in content)


# Surfaces that are pure number-noise: streaming/torrent, search, shopping/ads,
# file managers, AI chats. Number tracking is skipped there entirely.
_NOISE_KEY = re.compile(
    r"(stream|torrent|soccer|/watch|youtube\.com|netflix|twitch|hulu|tiktok|"
    r"instagram|reddit\.com|google\.com/search|bing\.com|duckduckgo|amazon\.|"
    r"ebay\.|aliexpress|/opportunities|automatiq|outlier\.ai|claude\.ai|"
    r"chatgpt\.com|chat\.openai|gemini\.google|perplexity|"
    r"^(finder|dock|claude|gemini|chatgpt|antigravity ide|cursor|code|terminal|system settings)::)",
    re.I)

# Labels that are pure churn no matter what: engagement counters, relative
# timestamps ("3 hours ago"), K/M-suffix fragments, and the literal word "label".
_JUNK_LABEL = re.compile(
    r"\b(views?|subscribers?|likes?|comments?|commented|watching|ago|label|"
    r"followers?|shares?d?|upvotes?|replies|reposts?)\b|^[kmb]\b", re.I)

def _norm_label(s: str) -> str:
    """Normalize a label to its metric core: 'My resting heart rate' -> 'heart
    rate', 'Daily steps' -> 'steps'. Drops modifier words so phrasing variants
    merge into one series."""
    words = re.findall(r"[a-z]+", s.lower())
    core = [w for w in words if w not in _METRIC_MODIFIERS]
    return " ".join(core)[:40] if core else s.strip().lower()[:40]


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
            if len(label) < 3 or _CRED_LABEL.search(label) or _CHROME_LABEL.search(label) \
               or _JUNK_LABEL.search(label):
                continue
            num_str = m.group("num")
            try:
                value = float(num_str.replace(",", ""))
            except ValueError:
                continue
            if _looks_like_id(num_str, value):
                continue
            unit = m.group("unit") or m.group("cur") or ""
            # Precision gate: the label must BE a personal metric (weight, grade,
            # steps…). A unit alone is not enough — $/MB/% appear all over the web.
            if not _is_metric_label(label):
                continue
            klabel = _norm_label(label)
            if klabel in seen:
                continue
            seen.add(klabel)
            # Store the normalized core as the label too ("weight", not "My
            # weight today") — phrasing variants merge and the UI reads clean.
            out.append({"label": klabel, "value": value,
                        "unit": unit, "key_label": klabel})
    return out


def _established_unit(conn, key: str) -> str:
    """The series' settled unit: the most common non-empty unit already stored for
    this key. '' when the series has no unit yet."""
    row = conn.execute(
        "SELECT unit, COUNT(*) c FROM series WHERE key=? AND unit != '' "
        "GROUP BY unit ORDER BY c DESC LIMIT 1", (key,)).fetchone()
    return row[0] if row else ""


def scan_and_store(conn, wisp_id: int, page_key: str, text: str,
                   max_per_capture: int = 8) -> int:
    """Store observations for this capture. Dedups the same key+value seen again
    within ~a day (a static number that keeps appearing shouldn't pile up rows)."""
    if not page_key or _NOISE_KEY.search(page_key):
        return 0
    found = detect(text)[:max_per_capture]
    added = 0
    for p in found:
        key = f"{page_key}::{p['key_label']}"
        # Unit consistency: once a series has a settled unit, refuse an observation
        # whose unit conflicts. A 'weight … lbs' series must not absorb a stray
        # 'weight 2020' or a '%' the OCR grabbed from an adjacent progress bar —
        # mixing units makes the chart meaningless. A unitless reading is still
        # accepted (OCR often drops the unit); only an actively different one is cut.
        est = _established_unit(conn, key)
        if est and p["unit"] and p["unit"] != est:
            continue
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


def _drop_outliers(points: list[dict]) -> list[dict]:
    """Remove gross outliers from a series before it's charted or answered, so a
    single OCR-garbled reading ('154, 155, 153, 9155') doesn't wreck the trend.
    Uses the median absolute deviation (robust, unlike mean/stddev which the
    outlier itself corrupts). Needs >= 4 points to act, and never returns empty."""
    vals = [p["value"] for p in points]
    n = len(vals)
    if n < 4:
        return points
    s = sorted(vals)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    dev = sorted(abs(v - med) for v in vals)
    mad = dev[n // 2] if n % 2 else (dev[n // 2 - 1] + dev[n // 2]) / 2
    if mad == 0:
        return points                       # no spread among the bulk: keep all
    kept = [p for p in points if abs(p["value"] - med) <= 6 * mad]
    return kept or points


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
        pts = _drop_outliers(series_points(conn, key))
        if not pts:
            continue
        label = conn.execute("SELECT label FROM series WHERE key=? ORDER BY ts DESC LIMIT 1",
                             (key,)).fetchone()[0]
        out.append({"key": key, "label": label, "unit": pts[-1]["unit"],
                    "current": pts[-1]["value"], "first": pts[0]["value"],
                    "n": len(pts), "last_ts": pts[-1]["ts"], "points": [p["value"] for p in pts]})
    out.sort(key=lambda s: s["last_ts"], reverse=True)
    return out[:limit]


def lookup(conn, question: str) -> dict | None:
    """Match a 'how has X moved/changed/trended' question to a promoted series."""
    if not re.search(r"\b(how (has|have|much|is|are)|what'?s my|trend(ing)?|over time|"
                     r"moved|changed|changing|progress|history|doing)\b", question, re.I) \
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
