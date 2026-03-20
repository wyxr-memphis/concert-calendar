"""Configuration for Memphis concert calendar."""

import os
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Date range: today through 7 days out (8 days total)
# ---------------------------------------------------------------------------
TODAY = date.today()
START_DATE = TODAY
END_DATE = TODAY + timedelta(days=7)

# Extended range for venue scrapers — 6 months for the interactive calendar
SCRAPER_END_DATE = TODAY + timedelta(days=180)

# ---------------------------------------------------------------------------
# API Keys — set as environment variables or GitHub Secrets
# ---------------------------------------------------------------------------
TICKETMASTER_API_KEY = os.environ.get("TICKETMASTER_API_KEY", "")

# ---------------------------------------------------------------------------
# Memphis location parameters
# ---------------------------------------------------------------------------
MEMPHIS_LAT = "35.1495"
MEMPHIS_LON = "-90.0490"
MEMPHIS_DMA_ID = "225"  # Ticketmaster DMA ID for Memphis
MEMPHIS_RADIUS = "30"  # miles — covers Southaven, West Memphis, etc.

# ---------------------------------------------------------------------------
# Google Sheet for manual event entries
# Publish your Google Sheet as CSV: File → Share → Publish to web → CSV
# Sheet should have columns: date, artist, venue, time, source_note
# ---------------------------------------------------------------------------
GOOGLE_SHEET_CSV_URL = os.environ.get("GOOGLE_SHEET_CSV_URL", "")

# ---------------------------------------------------------------------------
# Venue configuration
# Each venue has: name (canonical), aliases (for dedup), url (calendar page)
# Add new venues here as you discover them
# ---------------------------------------------------------------------------
NEIGHBORHOODS = [
    "Midtown",
    "Overton Square/Cooper-Young",
    "Crosstown/Broad Avenue",
    "Downtown/Beale Street",
    "South Main Arts District",
    "South Memphis (Graceland/Stax)",
    "Germantown",
]

VENUES = {
    "hi-tone": {
        "name": "Hi Tone",
        "aliases": ["hi tone", "hi-tone", "hi tone café", "hi tone cafe", "the hi-tone"],
        "neighborhood": "Midtown",
        "calendar_url": "https://hitonecafe.com/events/",
        "scraper": "hi_tone",
    },
    "minglewood-hall": {
        "name": "Minglewood Hall",
        "aliases": ["minglewood", "minglewood hall", "1555 madison"],
        "neighborhood": "Midtown",
        "calendar_url": "https://minglewoodhallmemphis.com/events/",
        "scraper": "minglewood",
    },
    "growlers": {
        "name": "Growlers",
        "aliases": ["growlers", "growlers memphis", "901 growlers"],
        "neighborhood": "Overton Square/Cooper-Young",
        "calendar_url": "https://901growlers.com/",
        "scraper": "growlers",
    },
    "hernandos-hideaway": {
        "name": "Hernando's Hideaway",
        "aliases": ["hernandos", "hernando's", "hernandos hideaway", "hernando's hideaway"],
        "neighborhood": "Midtown",
        "calendar_url": "https://hernandoshideawaymemphis.com/calendar/",
        "scraper": "hernandos",
    },
    "crosstown-arts": {
        "name": "Crosstown Arts",
        "aliases": [
            "crosstown arts", "the green room", "green room crosstown", "crosstown concourse",
            "crosstown arts green room", "crosstown arts, the green room",
            "crosstown arts the green room", "crosstown arts galleries",
            "crosstown theater", "crosstown arts theater",
        ],
        "neighborhood": "Crosstown/Broad Avenue",
        "calendar_url": "https://crosstownarts.org/calendar/",
        "scraper": "crosstown_arts",
    },
    "lafayettes": {
        "name": "Lafayette's Music Room",
        "aliases": ["lafayettes", "lafayette's", "lafayettes music room", "lafayette's music room"],
        "neighborhood": "Overton Square/Cooper-Young",
        "calendar_url": "https://lafayettes.com/event-calendar-memphis/",
        "scraper": "elfsight",
        "elfsight_widget_id": "a23b899c-e0ff-4165-a785-230565d757bd",
    },
    "overton-park-shell": {
        "name": "Overton Park Shell",
        "aliases": ["levitt shell", "overton park shell", "the shell"],
        "neighborhood": "Midtown",
        "calendar_url": "https://overtonparkshell.org/eventpage?view=list",
        "scraper": "overton_shell",
    },
    "bb-kings": {
        "name": "B.B. King's Blues Club",
        "aliases": ["bb kings", "b.b. kings", "b.b. king's", "bb king's blues club"],
        "neighborhood": "Downtown/Beale Street",
        "calendar_url": None,
        "scraper": "manual_only",
    },
    "graceland-soundstage": {
        "name": "Graceland Soundstage",
        "aliases": ["graceland soundstage", "graceland live", "guest house theater"],
        "neighborhood": "South Memphis (Graceland/Stax)",
        "calendar_url": "https://www.gracelandlive.com/shows",
        "scraper": "graceland",
    },
    "fedexforum": {
        "name": "FedExForum",
        "aliases": ["fedexforum", "fedex forum"],
        "neighborhood": "Downtown/Beale Street",
        "calendar_url": "https://www.fedexforum.com/events",
        "scraper": "ticketmaster_venue",
        "ticketmaster_venue_id": "KovZpZAE6vlA",
    },
    "germantown-pac": {
        "name": "Germantown Performing Arts Center",
        "aliases": ["germantown performing arts", "germantown performing arts center", "gpac"],
        "neighborhood": "Germantown",
        "calendar_url": "https://www.gpacweb.com/event-list",
        "scraper": "generic",
    },
    "orpheum": {
        "name": "Orpheum Theatre",
        "aliases": ["orpheum", "orpheum theatre", "halloran centre", "halloran center"],
        "neighborhood": "Downtown/Beale Street",
        "calendar_url": "https://www.orpheum-memphis.com/events?genres%5B0%5D=8229&view=",
        "scraper": "orpheum",
    },
    "bar-dkdc": {
        "name": "Bar DKDC",
        "aliases": ["bar dkdc", "dkdc"],
        "neighborhood": "Crosstown/Broad Avenue",
        "calendar_url": None,  # Instagram only — manual source
        "scraper": "manual_only",
    },
    "bside": {
        "name": "B-Side Memphis",
        "aliases": ["b-side", "bside", "b side", "b-side memphis"],
        "neighborhood": "South Main Arts District",
        "calendar_url": None,  # Instagram / socials — manual source
        "scraper": "manual_only",
    },
    "nashoba": {
        "name": "Nashoba",
        "aliases": ["nashoba", "nashoba live", "nashoba memphis"],
        "neighborhood": "Germantown",
        "calendar_url": "https://nashoba.live/event-calendar/",
        "scraper": "elfsight",
        "elfsight_widget_id": "cec78113-2599-4130-ba51-5401b108a2b2",
    },
    "south-main-sounds": {
        "name": "South Main Sounds",
        "aliases": ["south main sounds", "south main sounds memphis"],
        "neighborhood": "South Main Arts District",
        "calendar_url": "https://southmainsounds.com/shows",
        "scraper": "south_main_sounds",
    },
    "landers-center": {
        "name": "Landers Center",
        "aliases": ["landers center", "landers centre", "the landers center", "landers"],
        "neighborhood": "Germantown",  # Southaven, MS but close to Memphis
        "calendar_url": "https://www.landerscenter.com/events",
        "scraper": "landers",
    },
    "flyway-brewing": {
        "name": "Flyway Brewing",
        "aliases": ["flyway brewing", "flyway brewing memphis", "flyway"],
        "neighborhood": None,  # East Memphis — not in current neighborhood list; shows as "Other"
        "calendar_url": "https://www.flywaybrewingmemphis.com/events",
        "scraper": "flyway",
    },
}

# ---------------------------------------------------------------------------
# Keywords for filtering non-music events
# ---------------------------------------------------------------------------
EXCLUDE_KEYWORDS = [
    "comedy", "stand-up", "standup", "stand up", "comedian", "open mic comedy",
    "theatre", "theater", "play", "musical theater", "broadway",
    "art opening", "art show", "gallery opening", "exhibition",
    "lecture", "lecture series",
    "poetry reading", "spoken word", "book signing", "book reading",
    "trivia", "trivia night", "bingo", "game night",
    "drag brunch",  # keep drag shows with music, but brunch is usually not a concert
    "networking", "mixer", "business",
    "yoga", "fitness", "wellness", "meditation",
    "film screening", "movie night",
    "paint and sip", "paint night", "craft night",
    "food truck", "farmers market",
]

# Keywords that CONFIRM an event is music (used when source is ambiguous)
MUSIC_KEYWORDS = [
    "concert", "live music", "live band", "band", "dj", "dj night",
    "dance night", "electronic", "edm", "hip hop", "hip-hop",
    "r&b", "soul", "blues", "jazz", "rock", "punk", "metal",
    "country", "folk", "indie", "reggae", "gospel", "funk",
    "singer", "songwriter", "rapper", "mc ", "feat.", "featuring",
    "tour", "album release", "record release",
    "beats", "bass", "house music", "techno", "disco",
    "open mic",  # Usually music-focused in Memphis
    "jam session", "jam night",
    "karaoke",  # Borderline but keep it — DJs run these
]

# ---------------------------------------------------------------------------
# Venue name normalization map
# Maps variations found in API results to canonical names
# This gets populated from VENUES aliases above at import time
# ---------------------------------------------------------------------------
VENUE_ALIAS_MAP = {}
for _venue_key, _venue_info in VENUES.items():
    canonical = _venue_info["name"]
    for alias in _venue_info.get("aliases", []):
        VENUE_ALIAS_MAP[alias.lower()] = canonical


def normalize_venue_name(name: str) -> str:
    """Try to match a venue name to our canonical list."""
    lower = name.lower().strip()
    if lower in VENUE_ALIAS_MAP:
        return VENUE_ALIAS_MAP[lower]
    # Partial match — check if any alias is contained in the name
    for alias, canonical in VENUE_ALIAS_MAP.items():
        if alias in lower or lower in alias:
            return canonical
    # No match found — return original with title case cleanup
    return name.strip()


def is_music_event(title: str, category: str = "", description: str = "") -> bool:
    """Determine if an event is likely a music/DJ event."""
    text = f"{title} {category} {description}".lower()

    # Check exclusions first
    for keyword in EXCLUDE_KEYWORDS:
        if keyword in text:
            # But if it ALSO has strong music indicators, keep it
            has_music_signal = any(mk in text for mk in MUSIC_KEYWORDS)
            if not has_music_signal:
                return False

    # If category explicitly says music/concert, include it
    music_categories = ["music", "concert", "festivals", "nightlife", "dj"]
    if any(cat in category.lower() for cat in music_categories):
        return True

    # Check for music keywords in title
    if any(mk in text for mk in MUSIC_KEYWORDS):
        return True

    # If it's at a known music venue, lean toward including it
    for alias in VENUE_ALIAS_MAP:
        if alias in text:
            return True

    # Default: if we can't tell, exclude to avoid noise
    return False
