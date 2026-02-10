"""
Ticketmaster Discovery API source.
Searches for music events in Memphis, TN.

API docs: https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
Requires: TICKETMASTER_API_KEY environment variable
Free tier: 5,000 API calls per day
"""

import os
import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.sources import Event, normalize_venue

logger = logging.getLogger("concert-calendar.ticketmaster")

MEMPHIS_TZ = ZoneInfo("America/Chicago")
BASE_URL = "https://app.ticketmaster.com/discovery/v2"


def fetch_ticketmaster(start_date: datetime, end_date: datetime) -> list[Event]:
    """Fetch Memphis music events from Ticketmaster Discovery API."""
    api_key = os.environ.get("TICKETMASTER_API_KEY", "")
    if not api_key:
        logger.warning("TICKETMASTER_API_KEY not set — skipping Ticketmaster")
        return []

    events = []
    start_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        params = {
            "apikey": api_key,
            "city": "Memphis",
            "stateCode": "TN",
            "classificationName": "music",
            "startDateTime": start_str,
            "endDateTime": end_str,
            "size": 100,  # Max per page
            "sort": "date,asc",
        }

        response = requests.get(f"{BASE_URL}/events.json", params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        embedded = data.get("_embedded", {})
        raw_events = embedded.get("events", [])

        for item in raw_events:
            try:
                name = item.get("name", "Unknown Event")

                # Get venue info
                venues = item.get("_embedded", {}).get("venues", [])
                venue_name = venues[0].get("name", "Unknown Venue") if venues else "Unknown Venue"

                # Get date/time
                dates = item.get("dates", {})
                start_info = dates.get("start", {})
                date_str = start_info.get("localDate", "")

                if not date_str:
                    continue

                time_str = start_info.get("localTime")
                event_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=MEMPHIS_TZ)

                # Format display time
                display_time = None
                if time_str:
                    try:
                        t = datetime.strptime(time_str, "%H:%M:%S")
                        display_time = t.strftime("%-I:%M %p").lstrip("0")
                        event_dt = event_dt.replace(hour=t.hour, minute=t.minute)
                    except ValueError:
                        pass

                # Get event URL
                url = item.get("url")

                events.append(Event(
                    artist=name.strip(),
                    venue=normalize_venue(venue_name),
                    date=event_dt,
                    time=display_time,
                    source="Ticketmaster",
                    url=url,
                    raw_title=name,
                ))
            except Exception as e:
                logger.debug(f"Skipping Ticketmaster event: {e}")
                continue

        # Handle pagination if more results exist
        page_info = data.get("page", {})
        total_pages = page_info.get("totalPages", 1)
        if total_pages > 1:
            logger.info(f"  Ticketmaster has {total_pages} pages, fetched page 1")
            # For now, one page (100 events) should be sufficient for Memphis

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Ticketmaster API error: {e}")

    return events
