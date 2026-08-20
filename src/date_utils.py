"""Shared date parsing utilities."""

import re
from datetime import datetime, date, timedelta
from typing import Optional

from .config import START_DATE


# A year-less date ("Jan 15") that lands more than this many days before the
# reference date is assumed to belong to the *following* year.
#
# Without this, a December build parses "Jan 15" as January of the current year —
# a date ~11 months in the past — and every downstream `START_DATE <=` filter
# silently drops it (src/sources/venue_scrapers.py). The grace window keeps
# genuinely-recent past dates as-is, so a stale listing from last week is not
# flung 12 months into the future.
ROLLOVER_GRACE_DAYS = 45


def resolve_yearless_date(
    month: int, day: int, reference: Optional[date] = None
) -> Optional[date]:
    """Pick the year for a month/day pair that carried no year of its own.

    Returns the first candidate year (the reference year, then the next one)
    whose date is not more than ROLLOVER_GRACE_DAYS before `reference`.
    Returns None if neither candidate is a real calendar date — "Feb 29" when
    neither year is a leap year, for example.
    """
    ref = reference or START_DATE
    cutoff = ref - timedelta(days=ROLLOVER_GRACE_DAYS)
    for year in (ref.year, ref.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue  # e.g. Feb 29 in a non-leap year
        if candidate >= cutoff:
            return candidate
    return None


def parse_date_text(text: str, reference: Optional[date] = None) -> Optional[date]:
    """Try to parse a date string from various formats.

    Used by multiple scrapers (venue_scrapers, artifacts) and by the admin
    import path in backend/app.py. Formats without a year are resolved through
    resolve_yearless_date() so they roll over correctly across New Year.

    `reference` defaults to START_DATE, matching the window filter the scrapers
    apply to the result.
    """
    # Formats that carry an explicit year — used as-is.
    dated_formats = [
        "%b %d, %Y",   # "Feb 12, 2026"
        "%B %d, %Y",   # "February 12, 2026"
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m-%d-%Y",
        "%m-%d-%y",
        "%m.%d.%Y",
        "%m.%d.%y",
        "%Y-%m-%d",
    ]
    # Formats with no year — the year has to be inferred.
    yearless_formats = [
        "%b %d",        # "Feb 12"
        "%B %d",        # "February 12"
        "%m.%d",        # Period-separated (e.g., 2.13)
        "%m/%d",
    ]

    text = text.strip()

    for fmt in dated_formats:
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if dt.year < 2000:
            # Two-digit-year formats can still land pre-2000 (%y maps 69-99 to
            # 1969-1999); treat those as year-less rather than trusting them.
            return resolve_yearless_date(dt.month, dt.day, reference)
        return dt.date()

    for fmt in yearless_formats:
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return resolve_yearless_date(dt.month, dt.day, reference)

    # Try regex for "Feb 15", "Wed Feb 12", "February 15", etc.
    match = re.search(r'(\w{3,9})\s+(\d{1,2})(?:,?\s+(\d{4}))?', text)
    if match:
        month_str, day_str, year_str = match.groups()
        if year_str:
            for fmt in ("%b %d %Y", "%B %d %Y"):
                try:
                    return datetime.strptime(
                        f"{month_str} {day_str} {year_str}", fmt
                    ).date()
                except ValueError:
                    continue
            return None
        for fmt in ("%b", "%B"):
            try:
                month = datetime.strptime(month_str, fmt).month
            except ValueError:
                continue
            return resolve_yearless_date(month, int(day_str), reference)

    return None
