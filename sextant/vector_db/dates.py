"""
Dates written inside a document, so a reader can tell old evidence from new.

Personal papers disagree with each other over time: an identity card keeps the
address it was issued with, while a light bill from last month shows where the
person lives now. Search alone cannot say which passage is current, but it can
say how recent each document is, and the reader -- a person or Claude -- can
weigh that.

The dates come from the text, not the file: a download or a copy resets a
file's timestamp, while "Bill date 12/03/2024" survives both. Written dates are
read day first, as Indian and most non-US papers write them, unless the middle
number cannot be a month.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import date

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
# Longest first, so "sept" is not read as "sep" followed by a stray "t".
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))

_DAY_FIRST = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?!\d)")
_YEAR_FIRST = re.compile(r"(?<!\d)(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})(?!\d)")
_DAY_MONTH = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s-]+({_MONTH})\b\.?[\s,-]+(\d{{4}})(?!\d)", re.I
)
_MONTH_DAY = re.compile(
    rf"\b({_MONTH})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)", re.I
)
# "March 2024", "Mar-2024": a month with no day counts from its first.
_MONTH_YEAR = re.compile(rf"\b({_MONTH})\b\.?[\s,'-]+(\d{{4}})(?!\d)", re.I)

_EARLIEST_YEAR = 1900

# Most passages carry one or two dates; a statement can carry hundreds.
PASSAGE_DATES = 6


def _ascii_digits(text: str) -> str:
    if text.isascii():
        return text
    return "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text)


def _make(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def dates_in(text: str, today: date | None = None) -> list[date]:
    """Every date written in `text` up to `today`, oldest first, each once.

    Dates after today are dropped: on a bill that is a due date and on a
    passport an expiry, and neither says when the paper was written.
    """
    today = today or date.today()
    text = _ascii_digits(unicodedata.normalize("NFC", text))
    found: set[date] = set()

    for first, second, year in _DAY_FIRST.findall(text):
        day, month = int(first), int(second)
        if month > 12 >= day:  # 03/25/2024 can only be month first
            day, month = month, day
        found.add(_make(int(year), month, day) or date.min)
    for year, month, day in _YEAR_FIRST.findall(text):
        found.add(_make(int(year), int(month), int(day)) or date.min)
    for day, name, year in _DAY_MONTH.findall(text):
        found.add(_make(int(year), _MONTHS[name.lower()], int(day)) or date.min)
    for name, day, year in _MONTH_DAY.findall(text):
        found.add(_make(int(year), _MONTHS[name.lower()], int(day)) or date.min)
    # A month and year is only a date of its own outside a full date, or
    # "12 March 2024" would also count as the first of March.
    text = _MONTH_DAY.sub(" ", _DAY_MONTH.sub(" ", text))
    for name, year in _MONTH_YEAR.findall(text):
        found.add(_make(int(year), _MONTHS[name.lower()], 1) or date.min)

    return sorted(d for d in found if _EARLIEST_YEAR <= d.year and d <= today)


def newest(texts: Iterable[str], today: date | None = None) -> date | None:
    """The most recent date written anywhere in `texts`, or None."""
    latest: date | None = None
    for text in texts:
        found = dates_in(text, today)
        if found and (latest is None or found[-1] > latest):
            latest = found[-1]
    return latest
