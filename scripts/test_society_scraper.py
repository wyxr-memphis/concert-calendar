#!/usr/bin/env python3
"""Regression tests for the Society Memphis scraper (``_parse_society``).

Offline — no database, no network. A synthetic Wix Events page stands in for
societymemphis.com/event-list, carrying the warmup-data blob the real page
server-renders.

What these protect:
  * the music-only filter — Society is a skatepark + coffee shop whose calendar
    is mostly markets, chess night, skate nights and pro wrestling. Titles here
    are taken from its real listings;
  * artist-only titles ("Encircled Throne") — the usual shape of a Society show,
    kept only on a music/show word in the description;
  * whole-word matching — "dj" must not match "adjacent";
  * the UTC -> Central date conversion (a 7:30 PM show is 00:30 UTC next day);
  * Flyway, which now shares the Wix warmup reader, still parses.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://unused:unused@localhost/unused")

from bs4 import BeautifulSoup  # noqa: E402
from src.sources import venue_scrapers as vs  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILURES.append(name)


def wix_page(events):
    blob = {"appsWarmupData": {vs._WIX_EVENTS_APP_ID: {
        "widgetcomp-1": {"events": {"events": events}},
    }}}
    return BeautifulSoup(
        '<html><body><script type="application/json" id="wix-warmup-data">'
        + json.dumps(blob) + "</script></body></html>",
        "html.parser",
    )


def ev(title, start, slug="x", description="", about="", categories=None):
    return {
        "title": title, "slug": slug, "description": description, "about": about,
        "categories": categories or [],
        "scheduling": {"config": {"startDate": start}},
    }


VENUE = "Society Memphis Skatepark and Coffee"

print("Society music filter")
events = [
    # Non-music programming — must all be dropped.
    ev("Society Sunday Market", "2026-10-11T18:00:00Z", description="Local vendors, greens and treats. Live music on the patio!"),
    ev("Scott Street Market @ Society Memphis", "2026-10-17T16:00:00Z", description="Makers market with a DJ"),
    ev("Checkmate Chess Night", "2026-10-07T23:00:00Z", description="All ages, bring a board"),
    ev("Thursdays Are Rad", "2026-10-09T00:00:00Z", description="Skate night with DJ sets"),
    ev("Tiger Pro Wrestling", "2026-10-18T00:00:00Z", description="Live show! Doors at 6"),
    ev("Comedy Show", "2026-10-20T01:00:00Z", description="Stand-up night"),
    ev("Private Event - Park Closed", "2026-10-21T17:00:00Z"),
    ev("Beginner Skate Lesson", "2026-10-22T15:00:00Z"),
    ev("Coffee Tasting", "2026-10-23T15:00:00Z", description="Beans from the adjacent roaster"),
    # Music — must all be kept.
    ev("Jazz Night", "2026-10-10T00:00:00Z", slug="jazz-night"),
    ev("Bruised Peach Presents: Ladies Takeover Jam", "2026-10-12T00:00:00Z", slug="bruised-peach"),
    ev("Encircled Throne", "2026-10-04T00:30:00Z", slug="encircled-throne",
       about="<p>Doors 7pm. With Frostbitten and Human Shield. All ages.</p>"),
    ev("Frostbitten / Muzzleflash", "2026-10-24T01:00:00Z", description="Hardcore show, $10"),
    ev("LUCA (US)", "2026-10-25T00:00:00Z", categories=[{"name": "Music"}]),
]
parsed = vs._parse_society(wix_page(events), VENUE)
titles = {e.artist for e in parsed}
expected = {"Jazz Night", "Bruised Peach Presents: Ladies Takeover Jam",
            "Encircled Throne", "Frostbitten / Muzzleflash", "LUCA (US)"}
check("keeps exactly the music events", titles == expected, f"got {sorted(titles)}")

by_title = {e.artist: e for e in parsed}
et = by_title.get("Encircled Throne")
check("7:30 PM show stays on its Central date",
      et is not None and str(et.date) == "2026-10-03" and et.time == "7:30 PM",
      f"got {et and (et.date, et.time)}")
check("event URL uses /event-details/<slug>",
      et is not None and et.url == "https://www.societymemphis.com/event-details/encircled-throne")
check("venue name matches the existing DB row", et is not None and et.venue == VENUE)

print("Society unit cases")
check("artist-only title with no description is excluded",
      not vs._society_is_music("Frostbitten", "", []))
check("'dj' does not match inside 'adjacent'",
      not vs._society_is_music("Open House", "Right adjacent to the bowl", []))
check("band blurb saying 'play' is not dropped as theater",
      vs._society_is_music("Human Shield", "Three bands play, doors at 7", []))

print("Venue config")
from src.config import VENUES, normalize_venue_name  # noqa: E402
cfg = VENUES.get("society-memphis", {})
check("society-memphis is configured with the society scraper",
      cfg.get("scraper") == "society" and cfg.get("name") == VENUE)
check("'Society Memphis' normalizes to the canonical name",
      normalize_venue_name("Society Memphis") == VENUE,
      f"got {normalize_venue_name('Society Memphis')!r}")

print("Flyway (shared Wix reader)")
fly = vs._parse_flyway(wix_page([
    ev("The Band Plays", "2026-10-04T00:00:00Z", slug="band"),
    ev("Trivia Night", "2026-10-05T00:00:00Z"),
]), "Flyway Brewing")
check("Flyway still parses and filters",
      [e.artist for e in fly] == ["The Band Plays"]
      and fly[0].url == "https://www.flywaybrewingmemphis.com/events/band",
      f"got {[(e.artist, e.url) for e in fly]}")

print()
if FAILURES:
    print(f"{len(FAILURES)} failure(s)")
    sys.exit(1)
print("All Society scraper tests passed")
