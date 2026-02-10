"""
Shared configuration and data structures for the concert calendar.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    """Normalized event data from any source."""
    artist: str
    venue: str
    date: datetime  # Date of the event (timezone-aware, Central)
    time: Optional[str] = None  # Display time string, e.g. "Doors 7 / Show 8"
    source: str = ""  # Which source this came from
    url: Optional[str] = None  # Link to event page
    raw_title: Optional[str] = None  # Original title from source (helps with dedup)

    def display_line(self) -> str:
        """Format as a single on-air ready line: ARTIST — VENUE (Time)"""
        line = f"{self.artist} — {self.venue}"
        if self.time:
            line += f" ({self.time})"
        return line


# --- Memphis Venue Registry ---
# Canonical venue names for normalization. Keys are lowercase variants.
VENUE_ALIASES = {
    "hi tone": "Hi Tone",
    "hi-tone": "Hi Tone",
    "hi tone cafe": "Hi Tone",
    "hi-tone cafe": "Hi Tone",
    "hi-tone café": "Hi Tone",
    "minglewood hall": "Minglewood Hall",
    "minglewood": "Minglewood Hall",
    "growlers": "Growlers",
    "growlers bar": "Growlers",
    "hernando's hideaway": "Hernando's Hideaway",
    "hernandos hideaway": "Hernando's Hideaway",
    "hernando's hide-a-way": "Hernando's Hideaway",
    "crosstown arts": "Crosstown Arts",
    "the green room": "Crosstown Arts Green Room",
    "crosstown arts green room": "Crosstown Arts Green Room",
    "green room at crosstown": "Crosstown Arts Green Room",
    "lafayette's": "Lafayette's Music Room",
    "lafayette's music room": "Lafayette's Music Room",
    "lafayettes": "Lafayette's Music Room",
    "lafayettes music room": "Lafayette's Music Room",
    "overton park shell": "Overton Park Shell",
    "the shell": "Overton Park Shell",
    "levitt shell": "Overton Park Shell",
    "bb king's": "B.B. King's Blues Club",
    "b.b. king's": "B.B. King's Blues Club",
    "bb kings": "B.B. King's Blues Club",
    "b.b. king's blues club": "B.B. King's Blues Club",
    "graceland soundstage": "Graceland Soundstage",
    "graceland live": "Graceland Soundstage",
    "fedexforum": "FedExForum",
    "fedex forum": "FedExForum",
    "bar dkdc": "Bar DKDC",
    "dkdc": "Bar DKDC",
    "b-side": "B-Side Memphis",
    "b-side memphis": "B-Side Memphis",
    "the orpheum": "Orpheum Theatre",
    "orpheum": "Orpheum Theatre",
    "orpheum theatre": "Orpheum Theatre",
    "railgarten": "Railgarten",
    "rail garten": "Railgarten",
    "young avenue deli": "Young Avenue Deli",
    "young ave deli": "Young Avenue Deli",
    "the warehouse": "The Warehouse",
    "liberty bowl": "Liberty Bowl Memorial Stadium",
    "liberty bowl memorial stadium": "Liberty Bowl Memorial Stadium",
    "midtown crossing grill": "Midtown Crossing Grill",
    "tin roof": "Tin Roof Memphis",
    "tin roof memphis": "Tin Roof Memphis",
}


def normalize_venue(name: str) -> str:
    """Return canonical venue name if known, otherwise title-case the input."""
    if not name:
        return "Unknown Venue"
    lookup = name.strip().lower()
    return VENUE_ALIASES.get(lookup, name.strip())


# --- Venue Calendar URLs ---
# Used by the venue scraper module
VENUE_CALENDARS = {
    "Hi Tone": "https://www.hitonememphis.com/events",
    "Minglewood Hall": "https://www.minglewoodhall.com/events",
    "Growlers": "https://www.growlersmemphis.com/events",
    "Hernando's Hideaway": "https://www.hernandoshideaway.com/events",
    "Crosstown Arts": "https://crosstownarts.org/events/",
    "Lafayette's Music Room": "https://www.lafayettes.com/music",
    "Overton Park Shell": "https://www.overtonparkshell.org/events",
    "Graceland Soundstage": "https://www.graceland.com/event-calendar",
    "FedExForum": "https://www.fedexforum.com/events",
    "Railgarten": "https://www.railgarten.com/events",
    "Young Avenue Deli": "https://www.youngavenuedeli.com/calendar",
}

# --- Keywords for music event filtering ---
MUSIC_KEYWORDS = [
    "concert", "live music", "band", "dj", "dance night", "electronic",
    "hip hop", "hip-hop", "rap", "r&b", "soul", "blues", "jazz", "rock",
    "metal", "punk", "folk", "country", "gospel", "singer", "songwriter",
    "songwriter", "open mic", "karaoke", "acoustic", "tribute",
    "album release", "record release", "listening party", "music festival",
    "rave", "house music", "techno", "funk", "reggae", "ska",
    "orchestra", "symphony", "opera", "chamber", "classical",
    "tour", "world tour", "residency", "vinyl", "beat", "producer",
    "mc ", "emcee", "feat.", "ft.", "w/", "with special guest",
]

NON_MUSIC_KEYWORDS = [
    "comedy", "stand-up", "standup", "stand up", "comedian",
    "play", "theatre", "theater", "musical theatre", "broadway",
    "art opening", "art show", "gallery", "exhibition", "exhibit",
    "poetry reading", "book signing", "book reading", "author",
    "trivia", "bingo", "game night", "pub quiz",
    "brunch", "food", "tasting", "wine tasting", "beer tasting",
    "yoga", "fitness", "run club", "5k", "marathon",
    "workshop", "class", "seminar", "lecture", "conference",
    "fundraiser gala", "auction", "networking",
    "drag brunch", "drag show",  # keep these — they're performance but not music-focused
    "movie", "film screening", "documentary",
]
