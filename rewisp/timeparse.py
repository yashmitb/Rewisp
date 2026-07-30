"""Local time-phrase parsing. No AI. Turns "last tuesday afternoon" into a UTC window.

Returns (since, until) as 'YYYY-MM-DD HH:MM:SS' UTC strings (either may be None),
plus the question with the time phrase stripped, for cleaner FTS keywords.
"""

import re
from datetime import datetime, timedelta, timezone

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

DAYPARTS = {
    "morning": (5, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
    "night": (21, 24),
}


def _to_utc(dt_local: datetime) -> str:
    return dt_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _day_window(day: datetime, part: str | None) -> tuple[str, str]:
    start_h, end_h = DAYPARTS.get(part or "", (0, 24))
    start = day.replace(hour=start_h, minute=0, second=0, microsecond=0)
    if end_h == 24:
        end = day.replace(hour=23, minute=59, second=59, microsecond=0)
    else:
        end = day.replace(hour=end_h, minute=0, second=0, microsecond=0)
    return _to_utc(start), _to_utc(end)


def parse(question: str, now: datetime | None = None) -> tuple[str | None, str | None, str]:
    """(since_utc, until_utc, question_without_time_phrase)"""
    now = now or datetime.now().astimezone()
    q = question.lower()
    part_m = re.search(r"\b(morning|afternoon|evening|night)\b", q)
    part = part_m.group(1) if part_m else None

    def strip(*phrases: str) -> str:
        out = question
        for p in phrases:
            out = re.sub(p, " ", out, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", out).strip()

    if re.search(r"\btoday\b", q):
        s, u = _day_window(now, part)
        return s, u, strip(r"\btoday\b", r"\b(this\s+)?(morning|afternoon|evening|night)\b")

    if re.search(r"\byesterday\b", q):
        s, u = _day_window(now - timedelta(days=1), part)
        return s, u, strip(r"\byesterday\b", r"\b(morning|afternoon|evening|night)\b")

    m = re.search(r"\b(\d+)\s+days?\s+ago\b", q)
    if m:
        s, u = _day_window(now - timedelta(days=int(m.group(1))), part)
        return s, u, strip(r"\b\d+\s+days?\s+ago\b", r"\b(morning|afternoon|evening|night)\b")

    m = re.search(r"\b(last|this|on)?\s*(" + "|".join(WEEKDAYS) + r")\b", q)
    if m:
        target = WEEKDAYS.index(m.group(2))
        delta = (now.weekday() - target) % 7
        if delta == 0 and m.group(1) == "last":
            delta = 7
        elif delta == 0:
            delta = 0  # today, same weekday
        day = now - timedelta(days=delta if delta else (7 if m.group(1) == "last" else 0))
        s, u = _day_window(day, part)
        return s, u, strip(r"\b(last|this|on)?\s*(" + "|".join(WEEKDAYS) + r")\b",
                           r"\b(morning|afternoon|evening|night)\b")

    if re.search(r"\blast\s+week\b", q):
        start = (now - timedelta(days=now.weekday() + 7)).replace(hour=0, minute=0, second=0)
        end = start + timedelta(days=6, hours=23, minutes=59)
        return _to_utc(start), _to_utc(end), strip(r"\blast\s+week\b")

    if re.search(r"\bthis\s+week\b", q):
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
        return _to_utc(start), None, strip(r"\bthis\s+week\b")

    if part_m and re.search(r"\bthis\b", q):  # "this morning" with no day word
        s, u = _day_window(now, part)
        return s, u, strip(r"\bthis\s+(morning|afternoon|evening|night)\b")

    # Rolling relative windows: "last 2 hours", "past 30 minutes", "past 3 days",
    # "last couple weeks" — a span ending now, not a calendar bucket. These were
    # the biggest gap: real questions like "what did I do in the past 3 days"
    # parsed to nothing and fell back to today.
    m = re.search(r"\b(?:last|past|previous)\s+"
                  r"(\d+|an?|a?\s*few|a?\s*couple(?:\s+of)?)\s+"
                  r"(hour|hr|minute|min|day|week)s?\b", q)
    if m:
        word = re.sub(r"\s+", " ", m.group(1).strip())
        n = {"a": 1, "an": 1, "few": 3, "a few": 3, "couple": 2, "a couple": 2,
             "couple of": 2, "a couple of": 2}.get(word)
        if n is None:
            try:
                n = int(word)
            except ValueError:
                n = 1
        unit = m.group(2)
        span = {"hour": timedelta(hours=n), "hr": timedelta(hours=n),
                "minute": timedelta(minutes=n), "min": timedelta(minutes=n),
                "day": timedelta(days=n), "week": timedelta(weeks=n)}[unit]
        return _to_utc(now - span), _to_utc(now), strip(
            r"\b(?:last|past|previous)\s+(?:\d+|an?|a?\s*few|a?\s*couple(?:\s+of)?)"
            r"\s+(?:hours?|hrs?|minutes?|mins?|days?|weeks?)\b")

    if re.search(r"\b(?:past|last|this)\s+hour\b", q):  # single-hour window
        return _to_utc(now - timedelta(hours=1)), _to_utc(now), strip(r"\b(?:past|last|this)\s+hour\b")

    if re.search(r"\bpast\s+week\b", q):                # rolling 7 days (vs calendar "last week")
        return _to_utc(now - timedelta(days=7)), _to_utc(now), strip(r"\bpast\s+week\b")

    if re.search(r"\bthis\s+month\b", q):
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return _to_utc(start), None, strip(r"\bthis\s+month\b")
    if re.search(r"\b(?:last|past)\s+month\b", q):
        first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_end = first_this - timedelta(seconds=1)
        last_start = last_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return _to_utc(last_start), _to_utc(last_end), strip(r"\b(?:last|past)\s+month\b")

    # Weekend = Saturday 00:00 → Sunday 23:59. "this/over the weekend" is the most
    # recent (or current) weekend; "last weekend" is the one before.
    if re.search(r"\bweekend\b", q):
        days_since_sat = (now.weekday() - 5) % 7      # Mon=0 … Sat=5, Sun=6
        sat = (now - timedelta(days=days_since_sat)).replace(hour=0, minute=0, second=0, microsecond=0)
        if re.search(r"\blast\s+weekend\b", q):
            sat -= timedelta(days=7)
        sun_end = sat + timedelta(days=1, hours=23, minutes=59, seconds=59)
        return _to_utc(sat), _to_utc(sun_end), strip(r"\b(?:this\s+|last\s+|over\s+the\s+|on\s+the\s+|the\s+)?weekend\b")

    if re.search(r"\btonight\b", q):                   # this evening onward
        start = now.replace(hour=17, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        return _to_utc(start), _to_utc(end), strip(r"\btonight\b")

    if re.search(r"\blast\s+night\b", q):              # yesterday evening into early today
        start = (now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        end = now.replace(hour=6, minute=0, second=0, microsecond=0)
        return _to_utc(start), _to_utc(end), strip(r"\blast\s+night\b")

    return None, None, question
