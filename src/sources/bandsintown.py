"""Bandsintown source.

The public Bandsintown API is artist-based, not city/venue-based in a useful way.
We scrape the Memphis city page instead: https://www.bandsintown.com/c/memphis-tn

Note: Bandsintown loads event data via JavaScript API calls, making reliable
scraping difficult. This source is currently disabled but kept for reference.
"""

from typing import List, Optional
import requests
from datetime import datetime, date
from bs4 import BeautifulSoup
from ..models import Event, SourceResult
from ..config import (
    START_DATE, END_DATE,
    normalize_venue_name, is_music_event,
)
from ..date_utils import parse_date_text

SOURCE_NAME = "Bandsintown"
CITY_URL = "https://www.bandsintown.com/c/memphis-tn"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch() -> SourceResult:
    """Fetch events from Bandsintown Memphis page."""
    result = SourceResult(source_name=SOURCE_NAME)

    try:
        response = requests.get(CITY_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
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

    Note: Bandsintown's event data is loaded via JavaScript API calls,
    making this scraper unreliable. This function is kept for reference.
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
            event_date = parse_date_text(date_text)
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



# _parse_date_text moved to src.date_utils.parse_date_text
