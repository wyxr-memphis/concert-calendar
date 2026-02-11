"""Venue website scrapers.

Each venue with a web calendar gets a scraper function.
When a venue changes their site, you only fix that one function.
"""

from typing import List, Optional
import requests
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup
from ..models import Event, SourceResult
from ..config import (
    VENUES, START_DATE, END_DATE,
    normalize_venue_name, is_music_event,
)
from ..date_utils import parse_date_text

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch() -> SourceResult:
    """Fetch events from all configured venue websites."""
    result = SourceResult(source_name="Venue Websites")
    sub_results = []

    for venue_key, venue_info in VENUES.items():
        url = venue_info.get("calendar_url")
        scraper_type = venue_info.get("scraper", "generic")

        # Skip venues without web calendars (manual-only)
        if not url or scraper_type == "manual_only":
            continue

        venue_result = _scrape_venue(venue_key, venue_info)
        sub_results.append(venue_result)

        result.events_found += venue_result.events_found
        result.events.extend(venue_result.events)
        result.events_filtered += venue_result.events_filtered

    # Compile status from sub-results
    failures = [r for r in sub_results if not r.success]
    successes = [r for r in sub_results if r.success]

    if failures:
        fail_names = ", ".join(r.source_name for r in failures)
        result.error_message = f"Some venues failed: {fail_names}"

    # Overall success if at least some venues worked
    result.success = len(successes) > 0 or len(failures) == 0

    return result


def fetch_individual() -> List[SourceResult]:
    """Fetch events from each venue separately (for detailed logging)."""
    results = []

    for venue_key, venue_info in VENUES.items():
        url = venue_info.get("calendar_url")
        scraper_type = venue_info.get("scraper", "generic")

        if not url or scraper_type == "manual_only":
            continue

        venue_result = _scrape_venue(venue_key, venue_info)
        results.append(venue_result)

    return results


def _scrape_venue(venue_key: str, venue_info: dict) -> SourceResult:
    """Scrape a single venue's calendar page."""
    name = venue_info["name"]
    url = venue_info["calendar_url"]
    result = SourceResult(source_name=f"Venue: {name}")

    try:
        response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        scraper_type = venue_info.get("scraper", "generic")

        # Custom scrapers for specific venues
        if scraper_type == "hi_tone":
            events = _parse_hi_tone(soup, name)
        else:
            # Try JSON-LD first (many event sites embed structured data)
            events = _try_jsonld(soup, name)

            # If no JSON-LD, try generic DOM parsing
            if not events:
                events = _try_generic_parse(soup, name)

        result.events_found = len(events)
        for event in events:
            if START_DATE <= event.date <= END_DATE:
                result.events.append(event)
            else:
                result.events_filtered += 1

        if result.events_found == 0:
            result.error_message = f"0 events parsed — page structure may have changed"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Request failed: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"

    return result


def _try_jsonld(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Extract events from JSON-LD structured data (Schema.org Event)."""
    events = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]

            for item in items:
                if item.get("@type") in ("Event", "MusicEvent"):
                    event = _jsonld_to_event(item, venue_name)
                    if event:
                        events.append(event)
                # Handle @graph arrays
                elif "@graph" in item:
                    for graph_item in item["@graph"]:
                        if graph_item.get("@type") in ("Event", "MusicEvent"):
                            event = _jsonld_to_event(graph_item, venue_name)
                            if event:
                                events.append(event)
        except (json.JSONDecodeError, Exception):
            continue

    return events


def _jsonld_to_event(data: dict, default_venue: str) -> Optional[Event]:
    """Convert a JSON-LD Event to our Event model."""
    name = data.get("name", "").strip()
    if not name:
        return None

    # Date
    start_date = data.get("startDate", "")
    if not start_date:
        return None
    try:
        if "T" in start_date:
            dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(start_date, "%Y-%m-%d")
        event_date = dt.date()
        time_str = dt.strftime("%-I:%M %p").replace(":00 ", " ") if "T" in start_date else None
    except ValueError:
        return None

    # Venue — prefer embedded, fall back to the venue we're scraping
    venue = default_venue
    location = data.get("location", {})
    if isinstance(location, dict):
        loc_name = location.get("name", "")
        if loc_name:
            venue = normalize_venue_name(loc_name)

    url = data.get("url")

    return Event(
        artist=name,
        venue=venue,
        date=event_date,
        time=time_str,
        source=f"Venue: {default_venue}",
        url=url,
    )


def _try_generic_parse(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Generic DOM parser — tries common event listing patterns.
    
    Many venue sites use WordPress with events plugins (The Events Calendar,
    EventOn, etc.) or Squarespace event collections. This tries to handle
    the most common patterns.
    """
    events = []

    # Common selectors for event listings across CMS platforms
    selectors = [
        # WordPress: The Events Calendar plugin
        ".tribe-events-list .tribe-events-list-event",
        ".type-tribe_events",
        # WordPress: EventOn
        ".eventon_list_event a",
        # Squarespace
        ".eventlist-event",
        ".summary-item",
        # Generic patterns
        ".event-item", ".event-listing", ".event-card",
        "[class*='event-item']", "[class*='eventItem']",
        "article[class*='event']",
        # Table-based calendars
        "table.events tr",
    ]

    listings = []
    for selector in selectors:
        listings = soup.select(selector)
        if listings:
            break

    for listing in listings:
        try:
            # Title
            title_el = listing.select_one(
                "h2 a, h3 a, h2, h3, .tribe-events-list-event-title a, "
                ".eventlist-title a, .summary-title a, "
                "[class*='title'] a, [class*='title']"
            )
            title = title_el.get_text(strip=True) if title_el else ""

            # Date
            date_el = listing.select_one(
                "time[datetime], .tribe-event-schedule-details abbr, "
                ".eventlist-meta-date, [class*='date'], "
                ".summary-metadata-item--date"
            )

            event_date = None
            if date_el:
                # Try datetime attribute first
                dt_attr = date_el.get("datetime")
                if dt_attr:
                    try:
                        event_date = datetime.fromisoformat(
                            dt_attr.replace("Z", "+00:00")
                        ).date()
                    except ValueError:
                        pass
                # Fall back to text parsing
                if not event_date:
                    event_date = parse_date_text(date_el.get_text(strip=True))

            # Time
            time_el = listing.select_one(
                ".tribe-event-time, .eventlist-meta-time, [class*='time']"
            )
            time_str = time_el.get_text(strip=True) if time_el else None

            if not title or not event_date:
                continue

            # URL
            url = None
            if title_el and title_el.name == "a":
                url = title_el.get("href")
            if url and not url.startswith("http"):
                # Try to build absolute URL
                url = None  # Skip relative URLs for now

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=f"Venue: {venue_name}",
                url=url,
            ))
        except Exception:
            continue

    return events


def _parse_hi_tone(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Hi Tone events from hitonecafe.com .eventWrapper cards."""
    events = []

    for card in soup.select(".eventWrapper"):
        try:
            date_el = card.select_one("[class*='eventMonth']")
            title_el = card.select_one("h2, h3")
            link_el = card.select_one("a[href*='/event/']")

            if not date_el or not title_el:
                continue

            title = title_el.get_text(strip=True)
            date_text = date_el.get_text(strip=True)

            event_date = parse_date_text(date_text)
            if not event_date:
                continue

            url = link_el["href"] if link_el else None

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                source=f"Venue: {venue_name}",
                url=url,
            ))
        except Exception:
            continue

    return events
