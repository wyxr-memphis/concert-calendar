"""
Format events into date-grouped structure for display.
"""

from typing import Dict, List
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.sources import Event

MEMPHIS_TZ = ZoneInfo("America/Chicago")


def format_events_by_date(
    events: List[Event],
    start_date: datetime,
    end_date: datetime,
) -> Dict[str, List[Event]]:
    """
    Group events by date and return an ordered dict.
    Keys are formatted date strings like "WEDNESDAY, FEB 11".
    Includes empty dates so every day in the range appears.
    """
    # Group by date
    by_date: Dict[str, List[Event]] = defaultdict(list)

    for event in events:
        date_key = event.date.strftime("%Y-%m-%d")
        by_date[date_key].append(event)

    # Sort events within each date by time (events with time first), then alphabetically
    for date_key in by_date:
        by_date[date_key].sort(key=lambda e: (
            0 if e.time else 1,  # Events with times first
            e.time or "",
            e.artist.lower(),
        ))

    # Build ordered output with display-formatted date keys
    result = {}
    current = start_date
    while current.date() < end_date.date():
        date_key = current.strftime("%Y-%m-%d")
        display_key = current.strftime("%A, %B %-d").upper()  # e.g. "WEDNESDAY, FEBRUARY 11"
        result[display_key] = by_date.get(date_key, [])
        current += timedelta(days=1)

    return result
