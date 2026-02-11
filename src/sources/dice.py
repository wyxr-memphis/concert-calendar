"""DICE events source.

Scrapes the DICE Memphis browse page.
URL: https://dice.fm/browse/Memphis:35.149844:-90.049566
"""

from typing import List, Optional
import requests
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup
from ..models import Event, SourceResult
from ..config import (
    START_DATE, END_DATE,
    normalize_venue_name, is_music_event,
)
from ..date_utils import parse_date_text

SOURCE_NAME = "DICE"
BROWSE_URL = "https://dice.fm/browse/Memphis:35.149844:-90.049566"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch() -> SourceResult:
    """Fetch events from DICE Memphis browse page."""
    result = SourceResult(source_name=SOURCE_NAME)

    try:
        response = requests.get(BROWSE_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        events = _parse_page(soup, response.text)

        result.events_found = len(events)
        for event in events:
            if is_music_event(event.artist, "music"):
                if START_DATE <= event.date <= END_DATE:
                    result.events.append(event)
                else:
                    result.events_filtered += 1
            else:
                result.events_filtered += 1

        if result.events_found == 0:
            result.error_message = "Page may require JS rendering — 0 events parsed"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Request failed: {str(e)[:100]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:100]}"

    return result


def _parse_page(soup: BeautifulSoup, raw_html: str) -> List[Event]:
    """Parse DICE browse page. Try JSON-LD first, then DOM parsing."""
    events = []

    # Strategy 1: Look for JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                for item in data:
                    event = _parse_jsonld(item)
                    if event:
                        events.append(event)
            elif isinstance(data, dict):
                event = _parse_jsonld(data)
                if event:
                    events.append(event)
        except (json.JSONDecodeError, Exception):
            continue

    if events:
        return events

    # Strategy 2: Look for __NEXT_DATA__ or similar embedded JSON
    next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', raw_html, re.DOTALL)
    if next_data_match:
        try:
            next_data = json.loads(next_data_match.group(1))
            events = _parse_next_data(next_data)
            if events:
                return events
        except (json.JSONDecodeError, Exception):
            pass

    # Strategy 3: DOM parsing fallback
    event_cards = soup.select("[class*='event'], [class*='Event'], [data-testid*='event']")
    for card in event_cards:
        try:
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='name']")
            venue_el = card.select_one("[class*='venue'], [class*='location']")
            date_el = card.select_one("time, [class*='date'], [datetime]")

            title = title_el.get_text(strip=True) if title_el else ""
            venue = venue_el.get_text(strip=True) if venue_el else ""

            if not title:
                continue

            # Try parsing date
            event_date = None
            if date_el:
                datetime_attr = date_el.get("datetime")
                if datetime_attr:
                    event_date = datetime.fromisoformat(datetime_attr.replace("Z", "+00:00")).date()
                else:
                    event_date = parse_date_text(date_el.get_text(strip=True))

            if not event_date:
                continue

            link = card.find("a")
            url = link.get("href", "") if link else ""
            if url and not url.startswith("http"):
                url = f"https://dice.fm{url}"

            events.append(Event(
                artist=title,
                venue=normalize_venue_name(venue) if venue else "Venue TBA",
                date=event_date,
                source=SOURCE_NAME,
                url=url or None,
            ))
        except Exception:
            continue

    return events


def _parse_jsonld(data: dict) -> Optional[Event]:
    """Parse a JSON-LD Event object."""
    if data.get("@type") not in ("Event", "MusicEvent"):
        return None

    name = data.get("name", "").strip()
    if not name:
        return None

    # Date
    start_date = data.get("startDate", "")
    if not start_date:
        return None
    try:
        dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        event_date = dt.date()
        time_str = dt.strftime("%-I:%M %p").replace(":00 ", " ")
    except ValueError:
        return None

    # Venue
    location = data.get("location", {})
    venue = location.get("name", "") if isinstance(location, dict) else ""

    # URL
    url = data.get("url")

    return Event(
        artist=name,
        venue=normalize_venue_name(venue) if venue else "Venue TBA",
        date=event_date,
        time=time_str,
        source=SOURCE_NAME,
        url=url,
    )


def _parse_next_data(data: dict) -> List[Event]:
    """Try to extract events from Next.js page data."""
    events = []

    def _walk(obj, depth=0):
        if depth > 10:
            return
        if isinstance(obj, dict):
            # Look for event-like objects
            if "name" in obj and ("startDate" in obj or "date" in obj):
                event = _parse_jsonld(obj)
                if event:
                    events.append(event)
            for v in obj.values():
                _walk(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item, depth + 1)

    _walk(data)
    return events
