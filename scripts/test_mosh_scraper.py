#!/usr/bin/env python3
"""Regression tests for the MoSH (Museum of Science & History) scraper.

Offline — no database, no network. ``get_with_retry`` is stubbed to return a
synthetic page from The Events Calendar's REST API, the shape
moshmemphis.com serves.

What these protect:
  * ``tribe_include_patterns`` keeps laser concerts and music films, and drops
    the museum's planetarium shows, camps and exhibits;
  * whole-word matching — "Rocket", "Museum Tour" and "Bandit" stay out, which
    is why this venue does not use is_music_event();
  * a category name alone ("Laser Shows") is enough to keep a listing;
  * venues without the option are unaffected.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://unused:unused@localhost/unused")

from src.config import VENUES, START_DATE  # noqa: E402
from src.sources import venue_scrapers as vs  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILURES.append(name)


DAY = (START_DATE + timedelta(days=3)).isoformat()


def item(title, categories=()):
    return {
        "title": title,
        "start_date": f"{DAY} 19:00:00",
        "all_day": False,
        "url": "https://moshmemphis.com/event/x/",
        "categories": [{"name": c} for c in categories],
    }


class FakeResp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def run(venue_info, items):
    real = vs.get_with_retry
    vs.get_with_retry = lambda *a, **k: FakeResp({"events": items, "total_pages": 1})
    try:
        return vs._fetch_tribe_events(venue_info)
    finally:
        vs.get_with_retry = real


KEEP = [
    "Laser Lab: Pink Floyd's The Dark Side of the Moon",
    "Laser Live Concert Series ft. Iron Mic Coalition",
    "Laser Beatles",
    "LASER ZEPPELIN",
    "Friday Night Lasers: Queen",
    "Stax to the Max: A Soul Music Documentary",
    "Elvis on the Giant Screen",
    "Jazz Under the Dome",
    "Rock 'n' Roll Through the Ages",
]
DROP = [
    "Rocket Science Saturday",
    "Museum Tour: Pink Palace Mansion",
    "Bandits of the Mississippi",
    "Dinosaurs of Antarctica",
    "Spring Break Science Camp",
    "Planetarium Show: Black Holes",
    "Member Morning",
    "Mosh Pit Physics",
]

print("MoSH music filter")
mosh = VENUES["mosh"]
res = run(mosh, [item(t) for t in KEEP + DROP])
kept = {e.artist for e in res.events}
for t in KEEP:
    check(f"keeps {t!r}", t in kept)
for t in DROP:
    check(f"drops {t!r}", t not in kept)
check("counts", res.events_found == len(KEEP) + len(DROP)
      and res.events_filtered == len(DROP),
      f"found={res.events_found} filtered={res.events_filtered}")
check("venue name", all(e.venue == mosh["name"] for e in res.events))
check("time formatted", all(e.time for e in res.events))

print("Category match")
res = run(mosh, [item("The Wall", ["Laser Shows"]), item("The Wall", ["Planetarium"])])
check("category 'Laser Shows' keeps a bare title", len(res.events) == 1)

print("Venues without the option are unaffected")
plain = {"name": "Memphis Listening Lab", "calendar_url": "https://example.org/events/"}
res = run(plain, [item(t) for t in DROP])
check("no include filter -> nothing dropped", len(res.events) == len(DROP))

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    sys.exit(1)
print("\nAll MoSH scraper checks passed")
