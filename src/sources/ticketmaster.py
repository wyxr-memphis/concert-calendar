"""Ticketmaster Discovery API source.

API Docs: https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
Free tier: 5,000 calls/day — we use ~2-3 per run.
Get API key: https://developer-acct.ticketmaster.com/user/register
"""

import requests
from datetime import datetime
from ..models import Event, SourceResult
from ..config import (
    TICKETMASTER_API_KEY, START_DATE, END_DATE,
    MEMPHIS_LAT, MEMPHIS_LON, MEMPHIS_RADIUS,
    normalize_venue_name, is_music_event,
)

SOURCE_NAME = "Ticketmaster"
BASE_URL = "https://app.ticketmaster.com/discovery/v2/events.json"


def fetch() -> SourceResult:
    """Fetch music events from Ticketmaster Discovery API."""
    result = SourceResult(source_name=SOURCE_NAME)

    if not TICKETMASTER_API_KEY:
        result.success = False
        result.error_message = "No API key configured (set TICKETMASTER_API_KEY)"
        return result

    try:
        params = {
            "apikey": TICKETMASTER_API_KEY,
            "latlong": f"{MEMPHIS_LAT},{MEMPHIS_LON}",
            "radius": MEMPHIS_RADIUS,
            "unit": "miles",
            "classificationName": "music",
            "startDateTime": f"{START_DATE.isoformat()}T00:00:00Z",
            "endDateTime": f"{END_DATE.isoformat()}T23:59:59Z",
            "size": 100,
            "sort": "date,asc",
        }

        response = requests.get(BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if "_embedded" not in data or "events" not in data["_embedded"]:
            result.events_found = 0
            return result

        raw_events = data["_embedded"]["events"]
        result.events_found = len(raw_events)

        for event_data in raw_events:
            try:
                event = _parse_event(event_data)
                if event and is_music_event(event.artist, "music"):
                    result.events.append(event)
                else:
                    result.events_filtered += 1
            except Exception:
                continue

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"API request failed: {str(e)[:100]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Unexpected error: {str(e)[:100]}"

    return result


def _parse_event(data: dict) -> Event | None:
    """Parse a single Ticketmaster event into our Event model."""
    name = data.get("name", "").strip()
    if not name:
        return None

    # Parse date
    dates = data.get("dates", {}).get("start", {})
    date_str = dates.get("localDate")
    if not date_str:
        return None
    event_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    # Parse time (optional)
    time_str = None
    local_time = dates.get("localTime")
    if local_time:
        try:
            t = datetime.strptime(local_time, "%H:%M:%S")
            time_str = t.strftime("%-I:%M %p").replace(":00 ", " ")
        except ValueError:
            pass

    # Parse venue
    venue_name = "Unknown Venue"
    venues = data.get("_embedded", {}).get("venues", [])
    if venues:
        venue_name = venues[0].get("name", "Unknown Venue")
    venue_name = normalize_venue_name(venue_name)

    # Get URL
    url = data.get("url")

    return Event(
        artist=name,
        venue=venue_name,
        date=event_date,
        time=time_str,
        source=SOURCE_NAME,
        url=url,
    )
