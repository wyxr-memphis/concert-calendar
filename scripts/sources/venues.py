"""
Individual venue calendar scrapers.
Each venue gets its own parser function so when one breaks, the others keep working.

This module will need ongoing maintenance as venues change their websites.
Check the error log regularly!
"""

import json
import logging
import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

from scripts.sources import Event, normalize_venue, VENUE_CALENDARS

logger = logging.getLogger("concert-calendar.venues")

MEMPHIS_TZ = ZoneInfo("America/Chicago")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}


def fetch_all_venues(start_date: datetime, end_date: datetime) -> list[Event]:
    """Fetch events from all configured venue calendars."""
    all_events = []

    for venue_name, url in VENUE_CALENDARS.items():
        try:
            events = _scrape_venue_generic(venue_name, url, start_date, end_date)
            logger.info(f"  {venue_name}: {len(events)} events")
            all_events.extend(events)
        except Exception as e:
            logger.warning(f"  {venue_name}: scrape failed — {e}")

    return all_events


def _scrape_venue_generic(venue_name: str, url: str, start_date: datetime, end_date: datetime) -> list[Event]:
    """
    Generic venue scraper that tries multiple strategies:
    1. JSON-LD structured data (best case)
    2. Common event card HTML patterns
    3. Any links that look like event detail pages

    Individual venues can get custom parsers as needed.
    """
    events = []

    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # --- Strategy 1: JSON-LD ---
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in ("Event", "MusicEvent"):
                    event = _parse_jsonld_event(item, venue_name, start_date, end_date)
                    if event:
                        events.append(event)
                # Sometimes events are nested under ItemList
                if item.get("@type") == "ItemList":
                    for list_item in item.get("itemListElement", []):
                        inner = list_item.get("item", list_item)
                        if inner.get("@type") in ("Event", "MusicEvent"):
                            event = _parse_jsonld_event(inner, venue_name, start_date, end_date)
                            if event:
                                events.append(event)
        except (json.JSONDecodeError, TypeError):
            continue

    if events:
        return events

    # --- Strategy 2: Common HTML patterns ---
    # Look for elements that commonly contain event info
    selectors = [
        ".event", ".event-item", ".event-card", ".event-listing",
        ".events-list-item", ".tribe-events-single",
        "article.event", "div.event", "li.event",
        "[class*='event-']", "[class*='Event']",
        ".shows .show", ".calendar-item", ".performance",
    ]

    for selector in selectors:
        entries = soup.select(selector)
        if entries:
            for entry in entries:
                event = _parse_html_event_card(entry, venue_name, url, start_date, end_date)
                if event:
                    events.append(event)
            if events:
                return events

    # --- Strategy 3: Look for date headers followed by event info ---
    # Some venues use a simple format like:
    # <h3>February 15</h3>
    # <p>Artist Name - 8pm</p>
    headers = soup.find_all(["h2", "h3", "h4"])
    for header in headers:
        header_text = header.get_text(strip=True)
        header_date = _try_parse_date(header_text, start_date)
        if header_date and start_date.date() <= header_date.date() < end_date.date():
            # Get siblings/next elements
            sibling = header.find_next_sibling()
            while sibling and sibling.name not in ["h2", "h3", "h4"]:
                text = sibling.get_text(strip=True)
                if text and len(text) > 3:
                    events.append(Event(
                        artist=text.strip(),
                        venue=normalize_venue(venue_name),
                        date=header_date,
                        source=f"Venue: {venue_name}",
                        raw_title=text,
                    ))
                sibling = sibling.find_next_sibling()

    return events


def _parse_jsonld_event(data: dict, venue_name: str, start_date: datetime, end_date: datetime) -> Event | None:
    """Parse a JSON-LD Event for a known venue."""
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

    # Use JSON-LD venue if available, fall back to our known venue name
    location = data.get("location", {})
    json_venue = location.get("name", "") if isinstance(location, dict) else ""
    final_venue = normalize_venue(json_venue) if json_venue else normalize_venue(venue_name)

    display_time = None
    if event_dt.hour != 0:
        display_time = event_dt.strftime("%-I:%M %p").lstrip("0")

    # Check for doors time in description
    description = data.get("description", "")
    doors_time = _extract_doors_show_time(description)
    if doors_time:
        display_time = doors_time

    return Event(
        artist=name.strip(),
        venue=final_venue,
        date=event_dt,
        time=display_time,
        source=f"Venue: {venue_name}",
        url=data.get("url"),
        raw_title=name,
    )


def _parse_html_event_card(el, venue_name: str, base_url: str, start_date: datetime, end_date: datetime) -> Event | None:
    """Parse a generic HTML event card."""
    # Try to find title
    title_el = el.select_one("h2, h3, h4, .title, .event-title, .event-name, a[href]")
    if not title_el:
        return None

    title = title_el.get_text(strip=True)
    if not title or len(title) < 3:
        return None

    # URL
    link_el = el.select_one("a[href]")
    event_url = link_el.get("href", "") if link_el else ""
    if event_url and not event_url.startswith("http"):
        event_url = f"{base_url.rstrip('/')}/{event_url.lstrip('/')}"

    # Date
    date_el = el.select_one(".date, .event-date, time, [datetime]")
    date_text = ""
    if date_el:
        date_text = date_el.get("datetime", "") or date_el.get_text(strip=True)

    event_dt = _try_parse_date(date_text, start_date) if date_text else None
    if not event_dt:
        # Try the whole card text for a date
        card_text = el.get_text()
        event_dt = _try_parse_date(card_text, start_date)

    if not event_dt:
        return None

    if event_dt.date() < start_date.date() or event_dt.date() >= end_date.date():
        return None

    # Time
    time_el = el.select_one(".time, .event-time, .doors")
    time_text = time_el.get_text(strip=True) if time_el else None

    return Event(
        artist=title.strip(),
        venue=normalize_venue(venue_name),
        date=event_dt,
        time=time_text,
        source=f"Venue: {venue_name}",
        url=event_url or None,
        raw_title=title,
    )


def _try_parse_date(text: str, fallback: datetime) -> datetime | None:
    """Attempt to parse a date from various formats."""
    if not text:
        return None

    # Clean
    clean = text.strip()[:100]  # Limit length

    # Try ISO format first
    try:
        dt = datetime.fromisoformat(clean.replace("Z", "+00:00"))
        return dt.astimezone(MEMPHIS_TZ)
    except (ValueError, TypeError):
        pass

    # Common date formats
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%A, %B %d, %Y",
        "%A, %B %d",
        "%B %d",
        "%b %d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(clean, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=fallback.year)
            return dt.replace(tzinfo=MEMPHIS_TZ)
        except ValueError:
            continue

    # Try to find a date pattern in the text
    patterns = [
        r"(\d{1,2}/\d{1,2}/\d{2,4})",
        r"(\w+ \d{1,2},?\s*\d{4})",
        r"(\w+day,?\s+\w+ \d{1,2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, clean)
        if match:
            return _try_parse_date(match.group(1), fallback)

    return None


def _extract_doors_show_time(text: str) -> str | None:
    """Look for 'Doors X / Show Y' style time strings."""
    if not text:
        return None

    patterns = [
        r"[Dd]oors?\s*:?\s*(\d{1,2}(?::\d{2})?\s*(?:pm|PM|am|AM)?)\s*/?\s*[Ss]how\s*:?\s*(\d{1,2}(?::\d{2})?\s*(?:pm|PM|am|AM)?)",
        r"[Dd]oors?\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:pm|PM)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                return f"Doors {groups[0]} / Show {groups[1]}"
            else:
                return f"Doors {groups[0]}"

    return None
