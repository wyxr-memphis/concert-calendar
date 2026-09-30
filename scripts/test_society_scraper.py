#!/usr/bin/env python3
"""Regression tests for the Society Memphis scraper (``_parse_society``).

Offline — no database, no network. A synthetic Wix Events page stands in for
societymemphis.com/event-list, carrying the warmup-data blob the real page
server-renders.

What these protect:
  * the music-only filter, against every title on Society's live calendar as
    of 2026-09-30 — skate sessions, comedy, gaming, cosplay and RC drifting
    out; artist-only show titles ("Encircled Throne") in;
  * whole-word "skate" — a show at the skatepark is not a skate session;
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

print("Society music filter — the live calendar as of 2026-09-30")
# (title, expected keep). Every title below is a real Society listing.
LIVE = [
    ("Comedy Delicious", False),
    ("Girls Skate Session", False),
    ("Girls Skate Night", False),
    ("Saturday Skate School", False),
    ("Cookout and Skate", False),
    ("Licensed to Cosplay", False),
    ("Street Dancers RC Drifting", False),
    ("Match Gaming Fighting Tournaments", False),
    ("Match Gaming Avatar and Tokon Fight Nighy", False),
    ("Blend Fingerboard Jam", False),
    ("Society Sunday Market", False),
    ("Scott Street Market @ Society Memphis", False),
    ("Checkmate Chess Night", False),
    ("Thursdays Are Rad", False),
    ("Tiger Pro Wrestling", False),
    ("Jazz Nite", True),
    ("Jookin Muzik Friday", True),
    ("H.E.C.K. Melting Pot Music Show", True),
    ("We're loud Africa", True),
    ("The Only Name Left", True),
    ("Zynical Presents", True),
    ("Phases Psych Fest", True),
    # Artist-only title, no description — the shape that the first version's
    # "require a music word" rule wrongly dropped.
    ("Encircled Throne", True),
    # A show *at* the skatepark is not a skate session.
    ("Xavier Wulf Skatepark Popout", True),
    ("Bruised Peach Presents: Ladies Takeover Jam", True),
]
events = [ev(t, "2026-10-10T00:00:00Z", slug=f"s{i}") for i, (t, _) in enumerate(LIVE)]
parsed = {e.artist for e in vs._parse_society(wix_page(events), VENUE)}
for title, keep in LIVE:
    check(f"{'keep' if keep else 'drop'}: {title}", (title in parsed) == keep)

print("Society parsing")
one = vs._parse_society(wix_page([
    ev("Encircled Throne", "2026-10-04T00:30:00Z", slug="encircled-throne"),
]), VENUE)
et = one[0] if one else None
check("7:30 PM show stays on its Central date",
      et is not None and str(et.date) == "2026-10-03" and et.time == "7:30 PM",
      f"got {et and (et.date, et.time)}")
check("event URL uses /event-details/<slug>",
      et is not None and et.url == "https://www.societymemphis.com/event-details/encircled-throne")
check("venue name matches the existing DB row", et is not None and et.venue == VENUE)
check("a Wix category is checked too",
      not vs._society_is_music("Saturday Night", ["Skate"]))
check("comedy with a music keyword in the title is kept",
      vs._society_is_music("Comedy & Live Band Night", []))

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
