"""Shared date parsing utilities."""

import re
from datetime import datetime, date
from typing import Optional

from .config import START_DATE


def parse_date_text(text: str) -> Optional[date]:
    """Try to parse a date string from various formats.

    Used by multiple scrapers (bandsintown, memphis_flyer, venue_scrapers, artifacts).
    """
    formats = [
        "%b %d, %Y",   # "Feb 12, 2026"
        "%B %d, %Y",   # "February 12, 2026"
        "%b %d",        # "Feb 12"
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m-%d-%Y",
        "%m-%d-%y",
        "%m.%d.%Y",
        "%m.%d.%y",
        "%m.%d",        # Period-separated (e.g., 2.13)
        "%Y-%m-%d",
        "%B %d",
        "%m/%d",
    ]

    text = text.strip()
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.year < 2000:
                dt = dt.replace(year=START_DATE.year)
            return dt.date()
        except ValueError:
            continue

    # Try regex for "Feb 15", "Wed Feb 12", "February 15", etc.
    match = re.search(r'(\w{3,9})\s+(\d{1,2})(?:,?\s+(\d{4}))?', text)
    if match:
        month_str, day_str, year_str = match.groups()
        year = int(year_str) if year_str else START_DATE.year
        try:
            return datetime.strptime(f"{month_str} {day_str} {year}", "%b %d %Y").date()
        except ValueError:
            try:
                return datetime.strptime(f"{month_str} {day_str} {year}", "%B %d %Y").date()
            except ValueError:
                pass

    return None
