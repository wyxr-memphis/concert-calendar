#!/usr/bin/env python3
"""Regression tests for the MoSH (Museum of Science & History) scraper.

Offline — no database, no network. ``_parse_mosh`` reads a synthetic copy of
the homepage's server-rendered event cards (the markup moshmemphis.com served
on 2026-10-30); the shared ``include_patterns`` filter is also driven through
``_fetch_tribe_events`` with ``get_with_retry`` stubbed.

What these protect:
  * the homepage card parser — room, title, "Oct 30, 2026 | 7PM - 8PM" date
    and time, absolute event link, featured/today duplicates collapsed;
  * ``include_patterns`` keeps laser concerts and music films, and drops
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

from bs4 import BeautifulSoup  # noqa: E402
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

def card(room, title, when, eid="1"):
    return (f'<a class="upcoming-events__feature carousel-slide" '
            f'href="/mosh-calendar-page/event/{eid}" title="{title}">'
            f'<div class="upcoming-events__feature-content">'
            f'<h5 class="preheader">{room}</h5>'
            f'<h3 class="excerpt-title">{title}</h3>'
            f'<h6 class="excerpt-date">{when}</h6></div></a>')


mosh = VENUES["mosh"]

print("MoSH homepage cards — the live strip as of 2026-10-30")
LIVE = [
    ("Planetarium", "Laser Rock: Fright Lights", "Oct 30, 2026 | 7PM - 8PM", "6426718"),
    ("Lichterman Nature Center", "Trick or Treat Trail", "Oct 31, 2026 | 10:30AM - 4PM", "6536703"),
    ("Planetarium", "Laser Live: Unapologetic.", "Nov 6, 2026 | 6PM - 8PM", "6454597"),
    ("Giant Screen Theater", "Slowdown Cinema Club: Small Soldiers", "Nov 10, 2026 | 5:30PM - 9:30PM", "6545136"),
    ("Planetarium", "Laser Rock: Genesis", "Nov 13, 2026 | 7PM - 8PM", "6560474"),
    ("Giant Screen Theater", "Superhuman Body: World of Medical Marvels", "Oct 30, 2026 | 1PM - 2PM", "5691226"),
    ("Planetarium", "Firefall", "Oct 30, 2026 | 1PM - 1:30PM", "5868756"),
    ("Giant Screen Theater", "Call Of The Dolphins", "Oct 30, 2026 | 2PM - 3PM", "5868762"),
    ("Planetarium", "Mars: The Ultimate Voyage", "Oct 30, 2026 | 2PM - 2:30PM", "6090045"),
    ("Giant Screen Theater", "Walking with Dinosaurs: Prehistoric Planet", "Oct 30, 2026 | 3PM - 4PM", "6452265"),
    # Shown again in the today list — must not double up.
    ("Planetarium", "Laser Rock: Fright Lights", "Oct 30, 2026 | 7PM - 8PM", "6426718"),
]
soup = BeautifulSoup("<main>" + "".join(card(*c) for c in LIVE) + "</main>", "html.parser")
events, non_music = vs._parse_mosh(soup, mosh)
by_title = {e.artist: e for e in events}
check("keeps the three laser shows",
      sorted(by_title) == ["Laser Live: Unapologetic.", "Laser Rock: Fright Lights",
                           "Laser Rock: Genesis"], sorted(by_title))
check("drops the seven others", non_music == 7, f"non_music={non_music}")
e = by_title.get("Laser Rock: Fright Lights")
check("date", e and e.date.isoformat() == "2026-10-30")
check("time", e and e.time == "7 PM", e and e.time)
check("absolute link", e and e.url == "https://moshmemphis.com/mosh-calendar-page/event/6426718")
check("venue name", all(ev.venue == mosh["name"] for ev in events))
soup = BeautifulSoup(card("Planetarium", "Laser Floyd", "Dec 4, 2026 | 7:30PM - 8:30PM"),
                     "html.parser")
events, _ = vs._parse_mosh(soup, mosh)
check("minutes in time", events and events[0].time == "7:30 PM", events and events[0].time)
events, non_music = vs._parse_mosh(BeautifulSoup("<main></main>", "html.parser"), mosh)
check("no cards -> nothing, so the dispatcher reports a broken page",
      events == [] and non_music == 0)

print("include_patterns filter (via the tribe_events reader)")
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
