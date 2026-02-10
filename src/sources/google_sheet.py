"""Google Sheet manual events source.

Reads events from a published Google Sheet CSV.
Setup: 
1. Create a Google Sheet with columns: date, artist, venue, time, source_note
2. File → Share → Publish to web → select the sheet tab → CSV → Publish
3. Copy the URL and set it as GOOGLE_SHEET_CSV_URL environment variable

The sheet is your catch-all for:
- Instagram-only venues (Bar DKDC, B-Side, etc.)
- Pop-up shows and house shows
- Events spotted on social media
- User-submitted events (approved)
- Anything the automated scrapers miss
"""

import csv
import io
import requests
from datetime import datetime
from pathlib import Path
from ..models import Event, SourceResult
from ..config import GOOGLE_SHEET_CSV_URL, START_DATE, END_DATE, normalize_venue_name

SOURCE_NAME = "Manual (Google Sheet)"
LOCAL_CSV_PATH = Path(__file__).parent.parent.parent / "manual_events.csv"


def fetch() -> SourceResult:
    """Fetch events from published Google Sheet, falling back to local CSV."""
    result = SourceResult(source_name=SOURCE_NAME)

    csv_text = None

    # Try Google Sheet URL first
    if GOOGLE_SHEET_CSV_URL:
        try:
            response = requests.get(GOOGLE_SHEET_CSV_URL, timeout=10)
            response.raise_for_status()
            csv_text = response.text
        except requests.exceptions.RequestException as e:
            result.error_message = f"Sheet URL failed ({str(e)[:60]}), trying local CSV..."

    # Fall back to local manual_events.csv
    if csv_text is None and LOCAL_CSV_PATH.exists():
        try:
            csv_text = LOCAL_CSV_PATH.read_text(encoding="utf-8")
            result.source_name = "Manual (local CSV)"
        except Exception as e:
            pass

    if csv_text is None:
        result.success = True  # Not an error — just not configured yet
        result.error_message = "No Google Sheet URL or local CSV found"
        return result

    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        
        for row in reader:
            try:
                event = _parse_row(row)
                if event and START_DATE <= event.date <= END_DATE:
                    result.events.append(event)
                    result.events_found += 1
            except Exception:
                continue

        if result.events_found == 0:
            result.error_message = "CSV accessible but no events in date range"

    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:100]}"

    return result


def _parse_row(row: dict) -> Event | None:
    """Parse a single row from the Google Sheet.
    
    Expected columns (case-insensitive, flexible naming):
    - date: Event date (various formats accepted)
    - artist: Artist/event name
    - venue: Venue name
    - time: Optional time string
    - source_note: Optional note about source (e.g., "from Bar DKDC Instagram")
    """
    # Find columns flexibly (handle different header capitalization)
    def get_field(row, names):
        for name in names:
            for key in row:
                if key.strip().lower() == name.lower():
                    return row[key].strip()
        return ""

    date_str = get_field(row, ["date", "event_date", "event date"])
    artist = get_field(row, ["artist", "event", "act", "name", "artist/event"])
    venue = get_field(row, ["venue", "location", "place"])
    time = get_field(row, ["time", "showtime", "doors", "show time"])
    source_note = get_field(row, ["source_note", "source", "notes", "note"])

    if not date_str or not artist:
        return None

    # Parse date — accept many formats
    event_date = None
    date_formats = [
        "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y",
        "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y",
        "%B %d", "%b %d",  # No year — assume current
        "%m/%d",  # No year — assume current
    ]
    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.year < 2000:
                dt = dt.replace(year=START_DATE.year)
            event_date = dt.date()
            break
        except ValueError:
            continue

    if not event_date:
        return None

    source = SOURCE_NAME
    if source_note:
        source = f"Manual ({source_note})"

    return Event(
        artist=artist,
        venue=normalize_venue_name(venue) if venue else "Venue TBA",
        date=event_date,
        time=time if time else None,
        source=source,
    )
