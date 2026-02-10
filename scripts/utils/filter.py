"""
Filter events to music-only.
Uses keyword matching and venue awareness to keep concerts/DJ nights
and remove comedy, theater, art shows, etc.
"""

import logging
from scripts.sources import Event, NON_MUSIC_KEYWORDS, MUSIC_KEYWORDS, VENUE_ALIASES

logger = logging.getLogger("concert-calendar.filter")

# Venues that ONLY host music — if an event is at one of these, keep it
MUSIC_ONLY_VENUES = {
    "Hi Tone", "Minglewood Hall", "Growlers", "Hernando's Hideaway",
    "Lafayette's Music Room", "B.B. King's Blues Club", "Bar DKDC",
    "B-Side Memphis", "Tin Roof Memphis", "Graceland Soundstage",
    "Young Avenue Deli",
}

# Venues that host mixed events — need keyword filtering
MIXED_VENUES = {
    "Crosstown Arts", "Crosstown Arts Green Room", "Overton Park Shell",
    "FedExForum", "Orpheum Theatre", "Railgarten",
}


def filter_music_events(events: list[Event]) -> list[Event]:
    """Filter a list of events to keep only music/DJ events."""
    kept = []
    for event in events:
        if _is_music_event(event):
            kept.append(event)
        else:
            logger.debug(f"  Filtered out: {event.artist} at {event.venue} ({event.source})")
    return kept


def _is_music_event(event: Event) -> bool:
    """Determine if an event is likely a music/DJ event."""
    title = (event.artist or "").lower()
    raw = (event.raw_title or "").lower()
    venue = (event.venue or "").lower()
    combined = f"{title} {raw}"

    # If it's from a manual source, trust it completely
    if event.source in ("Google Sheets", "Manual CSV"):
        return True

    # If it's from a venue scraper for a music-only venue, keep it
    if event.venue in MUSIC_ONLY_VENUES:
        return True

    # Check for strong non-music signals
    for keyword in NON_MUSIC_KEYWORDS:
        if keyword in combined:
            # But check if there's also a music keyword (e.g., "comedy and music night")
            has_music_kw = any(mk in combined for mk in MUSIC_KEYWORDS)
            if not has_music_kw:
                return False

    # If the source is music-specific (like Bandsintown), trust it
    if event.source in ("Bandsintown", "Ticketmaster"):
        return True

    # For other sources, look for positive music signals
    # Events from DICE are usually music
    if event.source == "DICE":
        return True

    # Check for music keywords
    if any(kw in combined for kw in MUSIC_KEYWORDS):
        return True

    # If it's at a known music venue (even mixed), lean toward keeping it
    canonical_venue = event.venue
    if canonical_venue in MUSIC_ONLY_VENUES or canonical_venue in MIXED_VENUES:
        return True

    # If none of the above matched, keep it but log it
    # (Erring on side of completeness per Robby's preference)
    logger.debug(f"  Keeping unclassified event: {event.artist} at {event.venue}")
    return True
