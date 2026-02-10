"""
Memphis Flyer calendar scraper.
The Flyer's event calendar is one of the best local sources for Memphis music.

Target: https://www.memphisflyer.com/memphis/EventSearch
"""

from typing import List, Optional
import json
import logging
import re
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

from scripts.sources import Event, normalize_venue

logger = logging.getLogger("concert-calendar.memphis_flyer")

MEMPHIS_TZ = ZoneInfo("America/Chicago")
BASE_URL = "https://www.memphisflyer.com"

# The Flyer's event search with music category
CALENDAR_URLS = [
    "https://www.memphisflyer.com/memphis/EventSearch?narrowByDate=Next+7+Days&eventCategory=1702709",
    "https://www.memphisflyer.com/memphis/EventSearch?narrowByDate=Next+7+Days&eventCategory=1702710",
]
# Category IDs may change — 1702709 is typically "Music" or "Concerts"
# We also try the generic music search
SEARCH_URL = "https://www.memphisflyer.com/memphis/EventSearch?narrowByDate=Next+7+Days&keywords=music+concert+live+dj"


def fetch_memphis_flyer(start_date: datetime, end_date: datetime) -> List[Event]:
    """Fetch music events from the Memphis Flyer calendar."""
    events = []
    seen_urls = set()

    all_urls = CALENDAR_URLS + [SEARCH_URL]

    for url in all_urls:
        try:
            page_events = _scrape_flyer_page(url, start_date, end_date)
            for event in page_events:
                # Deduplicate within this source
                key = (event.artist, event.venue, event.date.date())
                if key not in seen_urls:
                    seen_urls.add(key)
                    events.append(event)
        except Exception as e:
            logger.warning(f"Memphis Flyer page failed ({url}): {e}")

    return events


def _scrape_flyer_page(url: str, start_date: datetime, end_date: datetime) -> List[Event]:
    """Scrape a single Memphis Flyer calendar page."""
    events = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Strategy 1: JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Event":
                    event = _parse_flyer_jsonld(item, start_date, end_date)
                    if event:
                        events.append(event)
        except (json.JSONDecodeError, TypeError):
            continue

    # Strategy 2: Parse HTML event listings
    # Memphis Flyer typically uses a list of event entries
    event_entries = soup.select(".EventListing, .event-listing, .listing, article.event")
    if not event_entries:
        # Try broader selectors
        event_entries = soup.select("[class*='event'], [class*='Event']")

    for entry in event_entries:
        try:
            # Title / artist
            title_el = entry.select_one("h2 a, h3 a, .event-title a, .listing-title a")
            if not title_el:
                title_el = entry.select_one("h2, h3, .event-title, .listing-title")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            event_url = title_el.get("href", "")
            if event_url and not event_url.startswith("http"):
                event_url = f"{BASE_URL}{event_url}"

            # Venue
            venue_el = entry.select_one(".venue, .event-venue, .listing-venue, .location")
            venue = venue_el.get_text(strip=True) if venue_el else ""

            # Date
            date_el = entry.select_one(".event-date, .listing-date, .date, time")
            date_text = date_el.get_text(strip=True) if date_el else ""

            if not title:
                continue

            event_dt = _parse_flyer_date(date_text, start_date)
            if not event_dt:
                event_dt = start_date

            if event_dt.date() < start_date.date() or event_dt.date() >= end_date.date():
                continue

            # Time
            time_el = entry.select_one(".event-time, .time")
            time_text = time_el.get_text(strip=True) if time_el else None

            events.append(Event(
                artist=title.strip(),
                venue=normalize_venue(venue) if venue else "See Memphis Flyer",
                date=event_dt,
                time=time_text,
                source="Memphis Flyer",
                url=event_url or None,
                raw_title=title,
            ))
        except Exception as e:
            logger.debug(f"Skipping Flyer entry: {e}")
            continue

    return events


def _parse_flyer_jsonld(data: dict, start_date: datetime, end_date: datetime) -> Optional[Event]:
    """Parse a JSON-LD Event from the Memphis Flyer."""
    name = data.get("name", "")
    if not name:
        return None

    start_str = data.get("startDate", "")
    event_dt = None
    if start_str:
        try:
            event_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            event_dt = event_dt.astimezone(MEMPHIS_TZ)
        except ValueError:
            return None

    if not event_dt:
        return None

    if event_dt.date() < start_date.date() or event_dt.date() >= end_date.date():
        return None

    location = data.get("location", {})
    venue = location.get("name", "") if isinstance(location, dict) else ""

    display_time = None
    if event_dt.hour != 0:
        display_time = event_dt.strftime("%-I:%M %p").lstrip("0")

    return Event(
        artist=name.strip(),
        venue=normalize_venue(venue) if venue else "See Memphis Flyer",
        date=event_dt,
        time=display_time,
        source="Memphis Flyer",
        url=data.get("url"),
        raw_title=name,
    )


def _parse_flyer_date(text: str, fallback: datetime) -> Optional[datetime]:
    """Parse Memphis Flyer date strings."""
    if not text:
        return None

    clean = text.strip()

    formats = [
        "%A, %B %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%A, %B %d",
        "%B %d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(clean, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=fallback.year)
            return dt.replace(tzinfo=MEMPHIS_TZ)
        except ValueError:
            continue

    return None
