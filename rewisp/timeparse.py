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

    return None, None, question
