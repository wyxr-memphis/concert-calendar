"""
Eventbrite source — scrapes the Memphis all-events page.
Eventbrite's public API was deprecated; we scrape their browse page instead.

Target: https://www.eventbrite.com/d/tn--memphis/all-events/
Filters results to music/DJ events based on title and category keywords.
"""

from typing import List, Optional
import logging
import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

from scripts.sources import Event, normalize_venue, MUSIC_KEYWORDS

logger = logging.getLogger("concert-calendar.eventbrite")

MEMPHIS_TZ = ZoneInfo("America/Chicago")

# Search specifically for music events
EVENTBRITE_URLS = [
    "https://www.eventbrite.com/d/tn--memphis/music/",
    "https://www.eventbrite.com/d/tn--memphis/music--performances/",
]

# Also try the main page and filter
EVENTBRITE_ALL = "https://www.eventbrite.com/d/tn--memphis/all-events/"


def _looks_like_music(title: str, description: str = "") -> bool:
    """Heuristic check if an event title/description suggests a music event."""
    text = f"{title} {description}".lower()
    return any(kw in text for kw in MUSIC_KEYWORDS)


def _parse_eventbrite_page(url: str, start_date: datetime, end_date: datetime) -> List[Event]:
    """Parse a single Eventbrite browse page for events."""
    events = []

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Eventbrite uses various structures; look for event cards
        # This targets their common card structure
        event_cards = soup.select("[data-testid='event-card']")
        if not event_cards:
            # Fallback: look for structured data
            event_cards = soup.select(".discover-search-desktop-card")
        if not event_cards:
            # Another fallback: look for JSON-LD structured data
            scripts = soup.find_all("script", type="application/ld+json")
            for script in scripts:
                try:
                    import json
                    data = json.loads(script.string)
                    if isinstance(data, list):
                        for item in data:
                            events.extend(_parse_jsonld_event(item, start_date, end_date))
                    elif isinstance(data, dict):
                        events.extend(_parse_jsonld_event(data, start_date, end_date))
                except (json.JSONDecodeError, TypeError):
                    continue
            return events

        for card in event_cards:
            try:
                # Extract title
                title_el = card.select_one("h2, h3, [data-testid='event-card-title']")
                title = title_el.get_text(strip=True) if title_el else ""

                # Extract venue/location
                location_el = card.select_one("[data-testid='event-card-location'], .card-text--truncated__one")
                venue = location_el.get_text(strip=True) if location_el else ""

                # Extract date
                date_el = card.select_one("[data-testid='event-card-date'], .card-text--truncated__one")
                date_text = date_el.get_text(strip=True) if date_el else ""

                # Extract URL
                link = card.select_one("a[href]")
                event_url = link["href"] if link else None

                if not title:
                    continue

                # Filter: only music events
                if not _looks_like_music(title, venue):
                    continue

                # Try to parse date (Eventbrite dates vary in format)
                event_dt = _parse_eventbrite_date(date_text, start_date)
                if not event_dt:
                    event_dt = start_date  # Fallback; will be within range

                # Skip if outside date range
                if event_dt.date() < start_date.date() or event_dt.date() >= end_date.date():
                    continue

                events.append(Event(
                    artist=title.strip(),
                    venue=normalize_venue(venue) if venue else "See listing",
                    date=event_dt,
                    source="Eventbrite",
                    url=event_url,
                    raw_title=title,
                ))
            except Exception as e:
                logger.debug(f"Skipping Eventbrite card: {e}")
                continue

    except requests.exceptions.RequestException as e:
        logger.warning(f"Eventbrite page fetch failed ({url}): {e}")

    return events


def _parse_jsonld_event(data: dict, start_date: datetime, end_date: datetime) -> List[Event]:
    """Parse a JSON-LD Event object from Eventbrite page."""
    events = []
    if data.get("@type") != "Event":
        return events

    name = data.get("name", "")
    if not name or not _looks_like_music(name, data.get("description", "")):
        return events

    # Parse date
    start_str = data.get("startDate", "")
    event_dt = None
    if start_str:
        try:
            event_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            event_dt = event_dt.astimezone(MEMPHIS_TZ)
        except ValueError:
            pass

    if not event_dt:
        return events

    if event_dt.date() < start_date.date() or event_dt.date() >= end_date.date():
        return events

    # Venue
    location = data.get("location", {})
    venue = location.get("name", "")

    # Time
    display_time = None
    if event_dt.hour != 0:
        display_time = event_dt.strftime("%-I:%M %p").lstrip("0")

    events.append(Event(
        artist=name.strip(),
        venue=normalize_venue(venue) if venue else "See listing",
        date=event_dt,
        time=display_time,
        source="Eventbrite",
        url=data.get("url"),
        raw_title=name,
    ))
    return events


def _parse_eventbrite_date(date_text: str, fallback: datetime) -> Optional[datetime]:
    """Best-effort parse of Eventbrite display dates like 'Sat, Feb 15, 7:00 PM'."""
    if not date_text:
        return None

    # Common Eventbrite formats
    formats = [
        "%a, %b %d, %Y, %I:%M %p",
        "%a, %b %d, %I:%M %p",
        "%b %d, %Y, %I:%M %p",
        "%b %d, %I:%M %p",
        "%A, %B %d, %Y",
        "%a, %b %d",
    ]

    # Clean up the text
    clean = date_text.strip()
    # Remove "at" and extra whitespace
    clean = re.sub(r"\s+at\s+", ", ", clean)
    clean = re.sub(r"\s+", " ", clean)

    for fmt in formats:
        try:
            dt = datetime.strptime(clean, fmt)
            # If year is missing, use the fallback year
            if dt.year == 1900:
                dt = dt.replace(year=fallback.year)
            return dt.replace(tzinfo=MEMPHIS_TZ)
        except ValueError:
            continue

    return None


def fetch_eventbrite(start_date: datetime, end_date: datetime) -> List[Event]:
    """Fetch Memphis music events from Eventbrite."""
    all_events = []

    for url in EVENTBRITE_URLS:
        events = _parse_eventbrite_page(url, start_date, end_date)
        all_events.extend(events)

    # Also check the all-events page for anything we might have missed
    all_page_events = _parse_eventbrite_page(EVENTBRITE_ALL, start_date, end_date)
    all_events.extend(all_page_events)

    logger.info(f"  Eventbrite: found {len(all_events)} music events across all pages")
    return all_events
