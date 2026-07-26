"""Configuration for Memphis concert calendar."""

import os
import re
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
    "East Memphis",
    "Germantown",
    "Hickory Hill",
    "North Mississippi",
]

VENUES = {
    "hi-tone": {
        "name": "Hi Tone",
        "aliases": ["hi tone", "hi-tone", "hi tone café", "hi tone cafe", "the hi-tone"],
        "neighborhood": "Midtown",
        "calendar_url": "https://hitonecafe.com/events/",
        "scraper": "hi_tone",
        # _parse_hi_tone reads no show time from the .eventWrapper cards
        "provides": ["ticket_url"],
    },
    "minglewood-hall": {
        "name": "Minglewood Hall",
        "aliases": ["minglewood", "minglewood hall", "1555 madison"],
        "neighborhood": "Midtown",
        "calendar_url": "https://minglewoodhallmemphis.com/events/",
        "scraper": "minglewood",
        # _parse_minglewood reads no show time
        "provides": ["ticket_url"],
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
        "calendar_url": "https://bbkings.com/memphis/music",
        "scraper": "bbkings",
        # Webflow CMS cards carry no per-event link
        "provides": ["start_time"],
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
    "satellite-music-hall": {
        "name": "Satellite Music Hall",
        "aliases": ["satellite music hall", "satellite music hall memphis"],
        "neighborhood": "Midtown",
        "calendar_url": "https://www.livenation.com/venue/KovZ917ASsA/satellite-music-hall-events",
        "scraper": "ticketmaster_venue",
        "ticketmaster_venue_id": "KovZ917ASsA",
    },
    "radians-amphitheater": {
        "name": "Radians Amphitheater",
        "aliases": ["radians amphitheater", "radians amphitheatre", "live at the garden", "memphis botanic garden"],
        "neighborhood": "East Memphis",  # Memphis Botanic Garden
        "calendar_url": "https://www.liveatthegarden.com/",
        "scraper": "ticketmaster_venue",
        "ticketmaster_venue_id": "KovZpZAa1JvA",
    },
    "cannon-center": {
        "name": "Cannon Center for the Performing Arts",
        "aliases": ["cannon center", "cannon center for the performing arts", "cannon center for performing arts"],
        "neighborhood": "Downtown/Beale Street",
        "calendar_url": "https://www.thecannoncenter.com/events",
        "scraper": "ticketmaster_venue",
        "ticketmaster_venue_id": "KovZpa3EHe",
    },
    "grind-city-amphitheater": {
        "name": "Grind City Amphitheater",
        "aliases": ["grind city amphitheater", "grind city amphitheatre", "grind city"],
        "neighborhood": None,  # North Memphis riverfront — no matching chip
        "calendar_url": None,
        "scraper": "ticketmaster_venue",
        "ticketmaster_venue_id": "Z7r9jZaAY-",
    },
    "bluesville": {
        # Canonical display name matches the pre-existing DB venue "Bluesville at
        # Horseshoe" so scraped events dedupe against it directly.
        "name": "Bluesville at Horseshoe",
        "aliases": ["bluesville at horseshoe", "horseshoe casino's bluesville", "horseshoe casino bluesville", "bluesville", "horseshoe bluesville"],
        "neighborhood": "North Mississippi",  # Tunica/Robinsonville, MS
        "calendar_url": None,
        "scraper": "ticketmaster_venue",
        "ticketmaster_venue_id": "KovZpZAa11IA",
    },
    "snowden-grove": {
        "name": "BankPlus Amphitheater at Snowden Grove",
        "aliases": ["bankplus amphitheater at snowden grove", "bankplus amphitheater", "bankplus amphitheatre", "snowden grove amphitheater", "snowden grove"],
        "neighborhood": "North Mississippi",  # Southaven, MS
        "calendar_url": None,
        "scraper": "ticketmaster_venue",
        "ticketmaster_venue_id": "KovZpZAEvFkA",
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
    "crosstown-beer": {
        "name": "Crosstown Brewing Co.",
        "aliases": ["crosstown beer", "crosstown brewing", "crosstown brewing co", "crosstown brewing co."],
        "neighborhood": "Crosstown/Broad Avenue",
        "calendar_url": "https://crosstownbeer.com/events/",
        "scraper": "crosstown_beer",
    },
    "blues-city-cafe": {
        "name": "Blues City Cafe",
        "aliases": ["blues city cafe", "blues city café", "blues city cafe band box"],
        "neighborhood": "Downtown/Beale Street",
        "calendar_url": "https://bluescitycafe.com/music/",
        "scraper": "blues_city_cafe",
    },
    "hueys": {
        "name": "Huey's",
        "aliases": ["hueys", "huey's", "huey's burgers"],
        "neighborhood": None,  # Multiple locations — neighborhood comes from event data
        "calendar_url": "https://hueyburger.com/music-menu",
        "scraper": "sitewrench",
        # The SiteWrench feed carries no per-event link
        "provides": ["start_time"],
        "sitewrench_api_token": os.environ.get("SITEWRENCH_API_TOKEN", ""),
        "sitewrench_site_id": "3018",
        "sitewrench_page_part_id": "458501",
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


# ---------------------------------------------------------------------------
# Venue identity
#
# A venue's display name is the root of two derived identities: the
# `events.source` tag (via venue_source_tag) and the health check's scraper name
# ("Venue: <name>"). Renaming a venue therefore forks both — the old tag keeps
# its existing event rows and lingers in build logs. resolve_venue_name() maps a
# historical name back onto the current one so a rename doesn't read as an
# outage; scripts/merge_venue_duplicates.py handles the venue rows themselves.
# ---------------------------------------------------------------------------

# Every current and historical name we can attribute to a venue.
VENUE_IDENTITY_MAP = {}
for _venue_info in VENUES.values():
    _canonical = _venue_info["name"]
    VENUE_IDENTITY_MAP[_canonical.lower()] = _canonical
    for _alias in _venue_info.get("aliases", []):
        VENUE_IDENTITY_MAP.setdefault(_alias.lower(), _canonical)


def venue_source_tag(venue_name: str) -> str:
    """Convert a venue name to a scraper source tag, e.g. 'Hi Tone' -> 'scraper:hi_tone'."""
    slug = re.sub(r'[^a-z0-9]+', '_', venue_name.lower()).strip('_')
    return f"scraper:{slug}"


def resolve_venue_name(name: str):
    """Exact-match a current or historical venue name to its canonical name.

    Returns None when the name belongs to no venue we still configure. Unlike
    normalize_venue_name() this does no substring matching — it's used to tell a
    renamed venue apart from a genuinely removed one, and a loose match there
    would mask a scraper that really did disappear.
    """
    return VENUE_IDENTITY_MAP.get((name or "").lower().strip())


# ---------------------------------------------------------------------------
# Scraper completeness expectations
#
# The health check calls an event "incomplete" when a field it expects is empty.
# Some venues simply never publish one of these, so flagging them produces a
# permanent warning that can never be cleared. A venue may narrow the set with
# a "provides" key; absent that key it's expected to supply all of them.
#
# This declares current *parser* capability, not a claim about the website — if
# a parser learns to extract the field, drop the entry.
# ---------------------------------------------------------------------------
COMPLETENESS_FIELDS = ("start_time", "ticket_url")


def venue_provides(venue_info: dict) -> tuple:
    """Completeness fields this venue's scraper is expected to populate."""
    declared = venue_info.get("provides")
    if declared is None:
        return COMPLETENESS_FIELDS
    return tuple(f for f in COMPLETENESS_FIELDS if f in declared)


# source tag -> fields expected from that source, e.g. 'scraper:hi_tone' -> ('ticket_url',)
SOURCE_PROVIDES = {
    venue_source_tag(_v["name"]): venue_provides(_v)
    for _v in VENUES.values()
}


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
