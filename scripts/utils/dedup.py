"""
Event deduplication.

The same event will often appear on Bandsintown, Ticketmaster, the venue's website,
and the Memphis Flyer. We need to collapse these into one entry.

Strategy: normalize artist name + venue + date → create a dedup key.
When duplicates are found, prefer the version with the most detail (time, URL).
"""

from typing import Dict, List
import re
import logging
from scripts.sources import Event

logger = logging.getLogger("concert-calendar.dedup")

# Source priority: prefer venue calendars > manual > APIs > scraped listings
SOURCE_PRIORITY = {
    "Google Sheets": 10,
    "Manual CSV": 10,
    "Venue:": 9,       # prefix match
    "Memphis Flyer": 7,
    "DICE": 6,
    "Bandsintown": 5,
    "Ticketmaster": 5,
    "Eventbrite": 4,
}


def deduplicate_events(events: List[Event]) -> List[Event]:
    """Remove duplicate events, keeping the version with the most detail."""
    seen: Dict[str, Event] = {}

    for event in events:
        key = _make_dedup_key(event)

        if key in seen:
            existing = seen[key]
            # Keep the one with better data
            if _score_event(event) > _score_event(existing):
                seen[key] = event
        else:
            seen[key] = event

    result = list(seen.values())
    result.sort(key=lambda e: (e.date, e.artist.lower()))
    return result


def _make_dedup_key(event: Event) -> str:
    """Create a normalized key for deduplication."""
    artist = _normalize_for_dedup(event.artist)
    venue = _normalize_for_dedup(event.venue)
    date = event.date.strftime("%Y-%m-%d")
    return f"{date}|{artist}|{venue}"


def _normalize_for_dedup(text: str) -> str:
    """Normalize a string for comparison: lowercase, strip articles/punctuation."""
    if not text:
        return ""

    s = text.lower().strip()

    # Remove common prefixes
    for prefix in ["the ", "a ", "an ", "dj "]:
        if s.startswith(prefix):
            s = s[len(prefix):]

    # Remove punctuation and extra whitespace
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()

    # Remove common suffixes
    for suffix in [" band", " trio", " quartet", " quintet", " ensemble", " orchestra"]:
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()

    return s


def _score_event(event: Event) -> int:
    """Score an event by how much useful detail it has. Higher = better."""
    score = 0

    # Source priority
    for prefix, priority in SOURCE_PRIORITY.items():
        if event.source.startswith(prefix):
            score += priority
            break

    # Has time info
    if event.time:
        score += 3

    # Has URL
    if event.url:
        score += 2

    # Has a real venue name (not "See listing")
    if event.venue and "see " not in event.venue.lower():
        score += 2

    return score
