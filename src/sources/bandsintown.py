"""Bandsintown source.

The public Bandsintown API is artist-based, not city/venue-based in a useful way.
We scrape the Memphis city page instead: https://www.bandsintown.com/c/memphis-tn
Uses Playwright for JavaScript rendering since the page requires JS.
"""

from typing import List, Optional
from datetime import datetime, date
from bs4 import BeautifulSoup
from .browser import get_page_with_js
from ..models import Event, SourceResult
from ..config import (
    START_DATE, END_DATE,
    normalize_venue_name, is_music_event,
)

SOURCE_NAME = "Bandsintown"
CITY_URL = "https://www.bandsintown.com/c/memphis-tn"


def fetch() -> SourceResult:
    """Fetch events from Bandsintown Memphis page using Playwright."""
    result = SourceResult(source_name=SOURCE_NAME)

    try:
        # Use Playwright to render JavaScript
        soup = get_page_with_js(CITY_URL, timeout=45000)

        if not soup:
            result.success = False
            result.error_message = "Failed to load page with JavaScript rendering"
            return result
        events = _parse_page(soup)

        result.events_found = len(events)
        for event in events:
            if is_music_event(event.artist, "music"):
                result.events.append(event)
            else:
                result.events_filtered += 1

        # If we got 0 events, the page likely requires JS rendering
        if result.events_found == 0:
            result.error_message = (
                "Page may require JS rendering — 0 events parsed. "
                "Consider adding Bandsintown app_id for API access."
            )

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Request failed: {str(e)[:100]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:100]}"

    return result


def _parse_page(soup: BeautifulSoup) -> List[Event]:
    """Attempt to parse Bandsintown Memphis page.
    
    Note: Bandsintown's DOM changes frequently. This parser may need
    updates. Check the error log if events_found drops to 0.
    """
    events = []

    # Look for event cards — BIT uses various class patterns
    # Try common selectors; update as needed when site changes
    event_cards = soup.select("[data-testid='event-card']")
    if not event_cards:
        event_cards = soup.select(".event-card, .eventCard, [class*='EventCard']")
    if not event_cards:
        # Fallback: look for any links with date-like patterns
        event_cards = soup.find_all("a", href=lambda h: h and "/e/" in str(h))

    for card in event_cards:
        try:
            # Extract artist name
            artist_el = card.select_one(
                "[class*='artist'], [class*='Artist'], [data-testid='event-name'], h3, h4"
            )
            artist = artist_el.get_text(strip=True) if artist_el else ""

            # Extract venue
            venue_el = card.select_one(
                "[class*='venue'], [class*='Venue'], [class*='location']"
            )
            venue = venue_el.get_text(strip=True) if venue_el else ""

            # Extract date
            date_el = card.select_one(
                "[class*='date'], [class*='Date'], time"
            )
            date_text = date_el.get_text(strip=True) if date_el else ""

            if not artist or not date_text:
                continue

            # Try to parse date from text
            event_date = _parse_date_text(date_text)
            if not event_date:
                continue
            if event_date < START_DATE or event_date > END_DATE:
                continue

            # Get link
            url = None
            link = card.get("href") or (card.find("a") or {}).get("href")
            if link and not link.startswith("http"):
                link = f"https://www.bandsintown.com{link}"
            url = link

            events.append(Event(
                artist=artist,
                venue=normalize_venue_name(venue) if venue else "Venue TBA",
                date=event_date,
                source=SOURCE_NAME,
                url=url,
            ))
        except Exception:
            continue

    return events


def _parse_date_text(text: str) -> Optional[date]:
    """Try to parse a date string from Bandsintown's various formats."""
    import re
    from datetime import date

    # Try common formats
    formats = [
        "%b %d, %Y",  # "Feb 12, 2026"
        "%B %d, %Y",  # "February 12, 2026"
        "%b %d",       # "Feb 12" (assume current year)
        "%m/%d/%Y",
        "%Y-%m-%d",
    ]

    text = text.strip()
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.year < 2000:  # No year in format — use current year
                dt = dt.replace(year=START_DATE.year)
            return dt.date()
        except ValueError:
            continue

    # Try extracting date from text like "Wed Feb 12"
    match = re.search(r'(\w{3,9})\s+(\d{1,2})(?:,?\s+(\d{4}))?', text)
    if match:
        month_str, day_str, year_str = match.groups()
        year = int(year_str) if year_str else START_DATE.year
        try:
            return datetime.strptime(f"{month_str} {day_str} {year}", "%b %d %Y").date()
        except ValueError:
            try:
                return datetime.strptime(f"{month_str} {day_str} {year}", "%B %d %Y").date()
            except ValueError:
                pass

    return None
