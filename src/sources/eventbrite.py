"""Eventbrite API source.

API Docs: https://www.eventbrite.com/platform/api
Get API token: https://www.eventbrite.com/platform/api-keys
"""

import requests
from datetime import datetime
from ..models import Event, SourceResult
from ..config import (
    EVENTBRITE_API_TOKEN, START_DATE, END_DATE,
    MEMPHIS_LAT, MEMPHIS_LON,
    normalize_venue_name, is_music_event,
)

SOURCE_NAME = "Eventbrite"
BASE_URL = "https://www.eventbriteapi.com/v3/events/search/"


def fetch() -> SourceResult:
    """Fetch music events from Eventbrite API."""
    result = SourceResult(source_name=SOURCE_NAME)

    if not EVENTBRITE_API_TOKEN:
        result.success = False
        result.error_message = "No API token configured (set EVENTBRITE_API_TOKEN)"
        return result

    try:
        headers = {"Authorization": f"Bearer {EVENTBRITE_API_TOKEN}"}
        params = {
            "location.latitude": MEMPHIS_LAT,
            "location.longitude": MEMPHIS_LON,
            "location.within": "30mi",
            "categories": "103",  # Music category
            "start_date.range_start": f"{START_DATE.isoformat()}T00:00:00",
            "start_date.range_end": f"{END_DATE.isoformat()}T23:59:59",
            "expand": "venue",
            "sort_by": "date",
        }

        response = requests.get(BASE_URL, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        raw_events = data.get("events", [])
        result.events_found = len(raw_events)

        for event_data in raw_events:
            try:
                event = _parse_event(event_data)
                if event:
                    title = event.artist
                    category = event_data.get("category", {}).get("name", "")
                    description = event_data.get("description", {}).get("text", "")[:200]
                    if is_music_event(title, category, description):
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
    """Parse a single Eventbrite event."""
    name = data.get("name", {}).get("text", "").strip()
    if not name:
        return None

    # Parse date
    start = data.get("start", {})
    date_str = start.get("local", "")
    if not date_str:
        return None
    dt = datetime.fromisoformat(date_str)
    event_date = dt.date()

    # Parse time
    time_str = dt.strftime("%-I:%M %p").replace(":00 ", " ")

    # Parse venue
    venue_data = data.get("venue", {})
    venue_name = venue_data.get("name", "")
    if not venue_name:
        venue_name = venue_data.get("address", {}).get("localized_address_display", "Memphis, TN")
    venue_name = normalize_venue_name(venue_name)

    url = data.get("url")

    return Event(
        artist=name,
        venue=venue_name,
        date=event_date,
        time=time_str,
        source=SOURCE_NAME,
        url=url,
    )
