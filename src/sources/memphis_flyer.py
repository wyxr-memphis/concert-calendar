"""Memphis Flyer music calendar scraper.

The Memphis Flyer maintains a comprehensive local events calendar.
URL: https://www.memphisflyer.com/memphis/EventSearch
"""

from typing import List, Optional
import requests
from datetime import datetime, timedelta, date
from bs4 import BeautifulSoup
from ..models import Event, SourceResult
from ..config import (
    START_DATE, END_DATE,
    normalize_venue_name, is_music_event,
)

SOURCE_NAME = "Memphis Flyer"
# The Flyer calendar can be filtered by category — "Music" is usually category 1
# This URL pattern may need updating if they change their site
CALENDAR_URLS = [
    "https://www.memphisflyer.com/memphis/EventSearch?narrowByDate=Next+7+Days&eventCategory=1702498",
    "https://www.memphisflyer.com/memphis/EventSearch?narrowByDate=Next+7+Days&eventSection=702498",
    "https://www.memphisflyer.com/search/event/music/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch() -> SourceResult:
    """Fetch music events from Memphis Flyer calendar."""
    result = SourceResult(source_name=SOURCE_NAME)

    # Try each URL pattern until one works
    for url in CALENDAR_URLS:
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                events = _parse_calendar(soup)
                if events:
                    result.events_found = len(events)
                    for event in events:
                        if is_music_event(event.artist, "music"):
                            if START_DATE <= event.date <= END_DATE:
                                result.events.append(event)
                            else:
                                result.events_filtered += 1
                        else:
                            result.events_filtered += 1
                    return result
        except Exception:
            continue

    # If all URLs failed
    result.success = False
    result.error_message = "Could not access Memphis Flyer calendar — all URL patterns failed"
    return result


def _parse_calendar(soup: BeautifulSoup) -> List[Event]:
    """Parse Memphis Flyer event listings.
    
    The Flyer uses Foundation CMS (Euclid Media). Common patterns:
    - Event titles in h3 or .EventListing elements
    - Dates in .EventDate or similar
    - Venues in .EventVenue
    """
    events = []

    # Try common Euclid Media / Foundation patterns
    listings = soup.select(".EventListing, .event-listing, [class*='event-item'], article.event")
    if not listings:
        listings = soup.select(".fdn-listing-item, .listing-item")
    if not listings:
        # Broader fallback
        listings = soup.find_all("div", class_=lambda c: c and "event" in c.lower()) if soup else []

    for listing in listings:
        try:
            # Title
            title_el = listing.select_one(
                "h3 a, h2 a, .fdn-listing-title a, .event-title a, [class*='title'] a"
            )
            if not title_el:
                title_el = listing.select_one("h3, h2, .event-title")
            title = title_el.get_text(strip=True) if title_el else ""

            # Venue
            venue_el = listing.select_one(
                ".EventVenue, .event-venue, [class*='venue'], [class*='location']"
            )
            venue = venue_el.get_text(strip=True) if venue_el else ""

            # Date
            date_el = listing.select_one(
                ".EventDate, .event-date, [class*='date'], time"
            )
            date_text = date_el.get_text(strip=True) if date_el else ""

            # Time
            time_el = listing.select_one(
                ".EventTime, .event-time, [class*='time']"
            )
            time_text = time_el.get_text(strip=True) if time_el else None

            if not title:
                continue

            event_date = _parse_flyer_date(date_text)
            if not event_date:
                continue

            # URL
            url = None
            if title_el and title_el.name == "a":
                url = title_el.get("href")
            elif title_el:
                link = title_el.find("a")
                if link:
                    url = link.get("href")
            if url and not url.startswith("http"):
                url = f"https://www.memphisflyer.com{url}"

            events.append(Event(
                artist=title,
                venue=normalize_venue_name(venue) if venue else "Venue TBA",
                date=event_date,
                time=time_text,
                source=SOURCE_NAME,
                url=url,
            ))
        except Exception:
            continue

    return events


def _parse_flyer_date(text: str) -> Optional[date]:
    """Parse date from Memphis Flyer format."""
    from .bandsintown import _parse_date_text
    return _parse_date_text(text)
