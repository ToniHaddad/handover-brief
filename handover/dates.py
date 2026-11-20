"""Resolve date expressions in a chat message against the message's own date.

Rules (each one is tested in tests/test_dates.py):

- A bare weekday ("Friday", "Thursday's visit") is the next such day strictly
  after the message date.
- "this Friday" is the Friday of the message's week if it has not passed,
  otherwise the next one.
- "next Monday" is the Monday of the following calendar week (weeks start on
  Monday). Said on Wednesday 4 March, "next Monday" is 9 March and
  "next Friday" is 13 March.
- A weekday after a past-tense verb ("sent it on Friday") or after "last" is
  the most recent such day before the message date.
- "the 14th" is the next 14th on or after the message date.
- "today", "end of day", "EOD" are the message date; "tomorrow" (with or
  without "end of day") is the day after; "end of the week" is the Friday of
  the message's week; "end of the month" is its last day.
- "in two weeks", "in 3 days", "within a week" count from the message date.
- Explicit dates: "14 March", "March 14", "14th of March", "2026-03-14",
  "14/03" (day first). A year is taken from the message when missing; a date
  more than four months in the past rolls into the next year.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4, "saturday": 5, "sunday": 6,
}
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "a couple of": 2, "couple of": 2,
    "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10,
}
PAST_MARKERS = re.compile(
    r"\b(sent|was|were|did|had|received|delivered|paid|finished|happened|told|"
    r"visited|met|called|came|went|gave|signed|submitted|shared)\b"
)
# Ordinals followed by these nouns are not dates ("2nd floor", "3rd round").
NOT_DATE_NOUNS = re.compile(
    r"\s*(floor|time|round|run|quarter|place|line|week|draft|batch|phase|"
    r"tranche|instal|option|attempt|version|truck|aisle|row|grade|person)",
    re.I,
)

WD = r"(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|wed|thurs?|thu|fri)"
WD2 = WD.replace("?P<wd>", "?P<wd2>")
MON = r"(?P<mon>january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)"
ORD = r"(?:st|nd|rd|th)"
NUM = r"(?P<n>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|a couple of)"

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("iso", re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")),
    ("dm_num", re.compile(r"(?<![\d/])(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/(?P<y>\d{2,4}))?(?![\d/])")),
    ("day_month", re.compile(
        rf"\b(?:{WD},?\s+)?(?:the\s+)?(?P<d>\d{{1,2}}){ORD}?\s+(?:of\s+)?{MON}\b(?:,?\s+(?P<y>\d{{4}}))?", re.I)),
    ("month_day", re.compile(
        rf"\b(?:{WD},?\s+)?{MON}\s+(?:the\s+)?(?P<d>\d{{1,2}}){ORD}?\b(?:,?\s+(?P<y>\d{{4}}))?", re.I)),
    ("eod_tomorrow", re.compile(
        r"\b(?:(?:by\s+)?(?:the\s+)?(?:end\s+of\s+(?:the\s+)?day|eod|cob|close\s+of\s+business)\s+tomorrow"
        r"|tomorrow\s+(?:end\s+of\s+(?:the\s+)?day|eod|cob|noon|morning|afternoon|evening))\b", re.I)),
    ("eod_weekday", re.compile(
        rf"\b(?:end\s+of\s+(?:the\s+)?day|eod|cob|close\s+of\s+business)\s+(?:on\s+)?{WD}\b", re.I)),
    ("day_after_tomorrow", re.compile(r"\bday\s+after\s+tomorrow\b", re.I)),
    ("tomorrow", re.compile(r"\btomorrow\b", re.I)),
    ("today", re.compile(r"\b(?:today|tonight|this\s+(?:morning|afternoon|evening)|end\s+of\s+(?:the\s+)?day|eod|cob)\b", re.I)),
    ("end_week", re.compile(r"\bend\s+of\s+(?P<next>next\s+)?(?:the\s+|this\s+)?week\b", re.I)),
    ("end_month", re.compile(r"\bend\s+of\s+(?:the\s+|this\s+)?month\b", re.I)),
    ("in_n", re.compile(
        rf"\b(?:in|within)\s+{NUM}\s+(?P<unit>days?|weeks?|working\s+days?)\b(?!\s+of\b)", re.I)),
    ("weekday_ord", re.compile(rf"\b(?P<mod>this|next|last|coming)?\s*{WD}(?:'s)?,?\s+(?:the\s+)?(?P<d>\d{{1,2}}){ORD}?\b(?!\s*(?::|am|pm|h\b|\.\d))", re.I)),
    ("weekday", re.compile(rf"\b(?:(?P<mod>this|next|last|coming)\s+)?{WD}(?:'s)?\b", re.I)),
    ("ordinal", re.compile(rf"\b(?:the\s+)?(?P<d>\d{{1,2}}){ORD}\b", re.I)),
]


@dataclass(frozen=True)
class DateMention:
    start: int
    end: int
    text: str
    value: date
    kind: str  # explicit | relative | weekday | ordinal | past


def _next_weekday(base: date, wd: int) -> date:
    days = (wd - base.weekday()) % 7
    return base + timedelta(days=days or 7)


def _prev_weekday(base: date, wd: int) -> date:
    days = (base.weekday() - wd) % 7
    return base - timedelta(days=days or 7)


def _weekday(base: date, wd: int, mod: str | None, past: bool) -> date:
    mod = (mod or "").lower()
    if mod == "last" or (past and not mod):
        return _prev_weekday(base, wd)
    if mod == "next":
        monday_next = base - timedelta(days=base.weekday()) + timedelta(days=7)
        return monday_next + timedelta(days=wd)
    if mod == "this":
        this_week = base - timedelta(days=base.weekday()) + timedelta(days=wd)
        return this_week if this_week >= base else this_week + timedelta(days=7)
    return _next_weekday(base, wd)


def _next_day_of_month(base: date, d: int) -> date | None:
    y, m = base.year, base.month
    for _ in range(13):
        if d <= calendar.monthrange(y, m)[1]:
            candidate = date(y, m, d)
            if candidate >= base:
                return candidate
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return None


def _explicit(base: date, d: int, m: int, y: int | None) -> date | None:
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return None
    if y is not None and y < 100:
        y += 2000
    year = y or base.year
    try:
        value = date(year, m, d)
    except ValueError:
        return None
    if y is None and (base - value).days > 120:
        value = value.replace(year=year + 1)
    return value


def _overlaps(spans: list[tuple[int, int]], s: int, e: int) -> bool:
    return any(s < b and e > a for a, b in spans)


def find_dates(text: str, base: date) -> list[DateMention]:
    """All date expressions in `text`, resolved against `base`, in text order."""
    found: list[DateMention] = []
    spans: list[tuple[int, int]] = []
    lower = text.lower()
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(text):
            s, e = m.span()
            if _overlaps(spans, s, e):
                continue
            g = m.groupdict()
            value: date | None = None
            out_kind = "relative"
            if kind == "iso":
                value = _explicit(base, int(g["d"]), int(g["m"]), int(g["y"]))
                out_kind = "explicit"
            elif kind == "dm_num":
                if m.group(0) in ("24/7",):
                    continue
                y = int(g["y"]) if g.get("y") else None
                value = _explicit(base, int(g["d"]), int(g["m"]), y)
                out_kind = "explicit"
            elif kind in ("day_month", "month_day"):
                y = int(g["y"]) if g.get("y") else None
                value = _explicit(base, int(g["d"]), MONTHS[g["mon"].lower()], y)
                out_kind = "explicit"
            elif kind == "eod_tomorrow" or kind == "tomorrow":
                value = base + timedelta(days=1)
            elif kind == "day_after_tomorrow":
                value = base + timedelta(days=2)
            elif kind == "eod_weekday":
                value = _next_weekday(base, WEEKDAYS[g["wd"].lower()])
                out_kind = "weekday"
            elif kind == "today":
                value = base
            elif kind == "end_week":
                friday = base - timedelta(days=base.weekday()) + timedelta(days=4)
                if g.get("next"):
                    friday += timedelta(days=7)
                elif friday < base:
                    friday += timedelta(days=7)
                value = friday
            elif kind == "end_month":
                value = date(base.year, base.month, calendar.monthrange(base.year, base.month)[1])
            elif kind == "in_n":
                raw = g["n"].lower()
                n = int(raw) if raw.isdigit() else NUMBER_WORDS[raw]
                unit = g["unit"].lower()
                if unit.startswith("week"):
                    value = base + timedelta(weeks=n)
                elif unit.startswith("working"):
                    value, left = base, n
                    while left:
                        value += timedelta(days=1)
                        if value.weekday() < 5:
                            left -= 1
                else:
                    value = base + timedelta(days=n)
            elif kind == "weekday_ord":
                d = int(g["d"])
                value = _next_day_of_month(base, d)
                out_kind = "ordinal"
            elif kind == "weekday":
                if re.match(r"[,\s]+\d{1,2}/\d", text[e:]):
                    continue  # "Fri 10/04": the explicit date that follows is the mention
                wd = WEEKDAYS[g["wd"].lower()]
                clause_start = max(lower.rfind(c, 0, s) for c in ".!?;,")
                before = lower[clause_start + 1:s]
                past = bool(PAST_MARKERS.search(before)) and (g.get("mod") or "").lower() != "next"
                value = _weekday(base, wd, g.get("mod"), past)
                out_kind = "past" if value < base else "weekday"
            elif kind == "ordinal":
                if NOT_DATE_NOUNS.match(text, e):
                    continue
                value = _next_day_of_month(base, int(g["d"]))
                out_kind = "ordinal"
            if value is None:
                continue
            spans.append((s, e))
            found.append(DateMention(s, e, text[s:e], value, out_kind))
    found.sort(key=lambda x: x.start)
    return found
