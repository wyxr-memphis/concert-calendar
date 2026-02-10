"""
Manual events source — reads from a Google Sheet (or local CSV fallback).

This handles events from Instagram-only venues (Bar DKDC, B-Side, etc.)
that team members enter manually.

Google Sheet format (4 columns):
  Date       | Artist            | Venue         | Time (optional)
  2026-02-15 | DJ Sista Sel      | Bar DKDC      | 9 PM
  2026-02-16 | Some Band         | B-Side Memphis|

CSV fallback uses the same format.

To use Google Sheets:
1. Create a Google Sheet with the above columns
2. Share it with the service account email (or make it public/link-accessible)
3. Set GOOGLE_SHEET_ID in your environment or .env file
4. Set GOOGLE_SHEET_RANGE (default: "Sheet1!A2:D")

To use CSV fallback:
- Place a file called manual_events.csv in the project root
"""

import csv
import logging
import os
import requests
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.sources import Event, normalize_venue

logger = logging.getLogger("concert-calendar.google_sheets")

MEMPHIS_TZ = ZoneInfo("America/Chicago")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def fetch_manual_events(start_date: datetime, end_date: datetime) -> list[Event]:
    """
    Fetch manually entered events.
    Tries Google Sheets first, falls back to local CSV.
    """
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
    api_key = os.environ.get("GOOGLE_SHEETS_API_KEY", "")

    if sheet_id and api_key:
        try:
            return _fetch_from_google_sheets(sheet_id, api_key, start_date, end_date)
        except Exception as e:
            logger.warning(f"Google Sheets fetch failed, trying CSV fallback: {e}")

    # CSV fallback
    csv_path = PROJECT_ROOT / "manual_events.csv"
    if csv_path.exists():
        return _fetch_from_csv(csv_path, start_date, end_date)

    logger.info("No manual events source configured (no Google Sheet ID or CSV file)")
    return []


def _fetch_from_google_sheets(sheet_id: str, api_key: str, start_date: datetime, end_date: datetime) -> list[Event]:
    """Fetch events from a public Google Sheet via the Sheets API."""
    events = []
    range_name = os.environ.get("GOOGLE_SHEET_RANGE", "Sheet1!A2:D")

    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        f"/values/{range_name}?key={api_key}"
    )

    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()

    rows = data.get("values", [])
    logger.info(f"  Google Sheets: {len(rows)} manual entries found")

    for i, row in enumerate(rows):
        try:
            event = _parse_manual_row(row, start_date, end_date, source="Google Sheets")
            if event:
                events.append(event)
        except Exception as e:
            logger.debug(f"  Skipping row {i + 2}: {e}")

    return events


def _fetch_from_csv(csv_path: Path, start_date: datetime, end_date: datetime) -> list[Event]:
    """Fetch events from a local CSV file."""
    events = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # Skip header row

        for i, row in enumerate(reader):
            try:
                event = _parse_manual_row(row, start_date, end_date, source="Manual CSV")
                if event:
                    events.append(event)
            except Exception as e:
                logger.debug(f"  Skipping CSV row {i + 2}: {e}")

    logger.info(f"  CSV: {len(events)} manual events in date range")
    return events


def _parse_manual_row(row: list, start_date: datetime, end_date: datetime, source: str) -> Event | None:
    """Parse a single row from the manual events sheet/CSV."""
    if len(row) < 3:
        return None

    date_str = row[0].strip()
    artist = row[1].strip()
    venue = row[2].strip()
    time_str = row[3].strip() if len(row) > 3 else None

    if not date_str or not artist:
        return None

    # Parse date
    event_dt = None
    date_formats = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"]
    for fmt in date_formats:
        try:
            event_dt = datetime.strptime(date_str, fmt).replace(tzinfo=MEMPHIS_TZ)
            break
        except ValueError:
            continue

    if not event_dt:
        return None

    # Check date range
    if event_dt.date() < start_date.date() or event_dt.date() >= end_date.date():
        return None

    return Event(
        artist=artist,
        venue=normalize_venue(venue) if venue else "Unknown Venue",
        date=event_dt,
        time=time_str if time_str else None,
        source=source,
        raw_title=artist,
    )
