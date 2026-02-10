"""
Bandsintown API source.
Searches for events in Memphis area by querying known venues.

API docs: https://artists.bandsintown.com/support/api-installation
Requires: BANDSINTOWN_APP_ID environment variable
"""

from typing import List
import os
import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.sources import Event, normalize_venue

logger = logging.getLogger("concert-calendar.bandsintown")

MEMPHIS_TZ = ZoneInfo("America/Chicago")
BASE_URL = "https://rest.bandsintown.com"

# Bandsintown doesn't have a great "search by city" endpoint,
# so we query by known artist names OR use their event search.
# The most reliable approach is using their location-based search.
MEMPHIS_LAT = 35.1495
MEMPHIS_LNG = -90.0490
SEARCH_RADIUS = 25  # miles


def fetch_bandsintown(start_date: datetime, end_date: datetime) -> List[Event]:
    """Fetch Memphis-area music events from Bandsintown."""
    app_id = os.environ.get("BANDSINTOWN_APP_ID", "")
    if not app_id:
        logger.warning("BANDSINTOWN_APP_ID not set — skipping Bandsintown")
        return []

    events = []
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    try:
        # Use the events search endpoint
        url = f"{BASE_URL}/events/search"
        params = {
            "app_id": app_id,
            "location": f"{MEMPHIS_LAT},{MEMPHIS_LNG}",
            "radius": SEARCH_RADIUS,
            "date": f"{start_str},{end_str}",
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list):
            logger.warning(f"Unexpected Bandsintown response format: {type(data)}")
            return []

        for item in data:
            try:
                artist_name = item.get("artist", {}).get("name", "")
                if not artist_name:
                    # Try lineup field
                    lineup = item.get("lineup", [])
                    artist_name = ", ".join(lineup) if lineup else "Unknown Artist"

                venue_data = item.get("venue", {})
                venue_name = venue_data.get("name", "Unknown Venue")
                venue_city = venue_data.get("city", "")

                # Skip events not in Memphis area
                if venue_city and "memphis" not in venue_city.lower():
                    continue

                event_date_str = item.get("datetime", "")
                if event_date_str:
                    event_dt = datetime.fromisoformat(event_date_str.replace("Z", "+00:00"))
                    event_dt = event_dt.astimezone(MEMPHIS_TZ)
                else:
                    continue

                # Extract time if available
                time_str = None
                if event_dt.hour != 0:
                    time_str = event_dt.strftime("%-I:%M %p").lstrip("0")

                events.append(Event(
                    artist=artist_name.strip(),
                    venue=normalize_venue(venue_name),
                    date=event_dt,
                    time=time_str,
                    source="Bandsintown",
                    url=item.get("url"),
                    raw_title=item.get("title", artist_name),
                ))
            except Exception as e:
                logger.debug(f"Skipping Bandsintown event: {e}")
                continue

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Bandsintown API error: {e}")

    return events
