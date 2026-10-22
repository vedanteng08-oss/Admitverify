"""Date parsing for every format seen in the sample documents.

Seen in samples: 13-05-2026, 01/11/2021, 08.07.2008, 1st June, 2008,
28th June, 2026, 15 Jun 2018, 31-Mar-2027, 31st March 2029, 2026-06-24,
"Sun Dec 14 21:52:03 IST 2025" (digital-signature stamps).

Indian documents write day first, so ambiguous numeric dates are read as DD/MM/YYYY.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MONTHS = {
    "JAN": 1, "JANUARY": 1, "FEB": 2, "FEBRUARY": 2, "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4, "MAY": 5, "JUN": 6, "JUNE": 6, "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8, "SEP": 9, "SEPT": 9, "SEPTEMBER": 9, "OCT": 10,
    "OCTOBER": 10, "NOV": 11, "NOVEMBER": 11, "DEC": 12, "DECEMBER": 12,
}

# Devanagari digits ०-९ → 0-9 (Marathi documents and headers), plus the soft hyphen,
# en dash and non-breaking space found in government PDF text layers.
_DEVANAGARI_DIGITS = str.maketrans(
    {**{d: str(i) for i, d in enumerate("०१२३४५६७८९")},
     "\xad": "-", "–": "-", "—": "-", "\xa0": " "}
)

_NUMERIC = re.compile(r"\b(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{2,4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DAY_MONTH_YEAR = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/.,]+([A-Za-z]{3,9})[\s\-/.,]+(\d{4})\b",
    re.IGNORECASE,
)
_MONTH_DAY_YEAR = re.compile(
    r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(?:\d{1,2}:\d{2}(?::\d{2})?\s+\w+\s+)?(\d{4})\b",
    re.IGNORECASE,
)


@dataclass
class ParsedDate:
    value: date | None
    original: str
    ok: bool


def _make(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000 if y < 50 else 1900
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text: str | None) -> ParsedDate:
    """Parse the first date found in `text`. Never guesses beyond the formats above."""
    original = text or ""
    if not text:
        return ParsedDate(None, original, False)
    t = text.translate(_DEVANAGARI_DIGITS)

    m = _ISO.search(t)
    if m:
        d = _make(int(m[1]), int(m[2]), int(m[3]))
        if d:
            return ParsedDate(d, original, True)

    m = _NUMERIC.search(t)
    if m:
        d = _make(int(m[3]), int(m[2]), int(m[1]))  # day first
        if d:
            return ParsedDate(d, original, True)

    m = _DAY_MONTH_YEAR.search(t)
    if m and m[2].upper() in MONTHS:
        d = _make(int(m[3]), MONTHS[m[2].upper()], int(m[1]))
        if d:
            return ParsedDate(d, original, True)

    m = _MONTH_DAY_YEAR.search(t)
    if m and m[1].upper() in MONTHS:
        d = _make(int(m[3]), MONTHS[m[1].upper()], int(m[2]))
        if d:
            return ParsedDate(d, original, True)

    return ParsedDate(None, original, False)


def academic_year_covers(valid_for: str | None, admission_year_start: int) -> bool:
    """True if text like 'Valid for Year 2026-2027' covers the admission year 2026-27."""
    if not valid_for:
        return False
    years = [int(y) for y in re.findall(r"(\d{4})", valid_for.translate(_DEVANAGARI_DIGITS))]
    if not years:
        return False
    if len(years) == 1:
        return years[0] == admission_year_start
    return years[0] <= admission_year_start < years[-1] or years[0] == admission_year_start
