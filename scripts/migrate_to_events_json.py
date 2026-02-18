#!/usr/bin/env python3
"""One-time migration: collect events from all sources and write to data/events.json.

Usage:
    python scripts/migrate_to_events_json.py
"""

import html
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.models import Event, SourceResult
from src.normalize import deduplicate
from src.config import START_DATE, END_DATE

from src.sources import ticketmaster, google_sheet, venue_scrapers, artifacts

EVENTS_JSON_PATH = ROOT / "data" / "events.json"


def event_to_json(event: Event, index: int, timestamp: str) -> dict:
    """Map an Event to the events.json schema."""
    event_id = f"evt_{int(time.time() * 1000)}_{index}"
    return {
        "id": event_id,
        "title": event.artist,
        "venue": event.venue,
        "date": event.date.isoformat(),
        "start_time": event.time,
        "doors_time": None,
        "ticket_url": event.url,
        "ticket_price": None,
        "image_url": None,
        "description": None,
        "genre": None,
        "source": event.source,
        "is_featured": False,
        "is_active": True,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def main():
    timestamp = datetime.now(ZoneInfo("UTC")).isoformat()
    print(f"Migrating events to {EVENTS_JSON_PATH}")
    print(f"Date range: {START_DATE} to {END_DATE}\n")

    all_events = []

    sources = [
        ("Ticketmaster", ticketmaster.fetch),
        ("Google Sheet", google_sheet.fetch),
        ("Artifacts", artifacts.fetch),
    ]

    for name, fetch_fn in sources:
        print(f"  Fetching: {name}...", end=" ", flush=True)
        try:
            result = fetch_fn()
            all_events.extend(result.events)
            print(f"{len(result.events)} events")
        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\n  Fetching: Venue Websites...")
    try:
        venue_results = venue_scrapers.fetch_individual()
        for vr in venue_results:
            all_events.extend(vr.events)
            print(f"    {vr.source_name}: {len(vr.events)} events")
    except Exception as e:
        print(f"    ERROR: {e}")

    # Clean HTML entities
    for event in all_events:
        event.artist = html.unescape(event.artist)
        event.venue = html.unescape(event.venue)

    # Deduplicate
    print(f"\n  Raw events: {len(all_events)}")
    deduped = deduplicate(all_events)
    print(f"  After dedup: {len(deduped)}")

    # Convert to JSON entries
    json_events = []
    for i, event in enumerate(deduped):
        json_events.append(event_to_json(event, i, timestamp))
        time.sleep(0.001)  # Ensure unique IDs

    # Write
    data = {
        "version": 1,
        "updated_at": timestamp,
        "events": json_events,
    }

    EVENTS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"\n  Wrote {len(json_events)} events to {EVENTS_JSON_PATH}")

    if json_events:
        dates = sorted(set(e["date"] for e in json_events))
        print(f"  Date range: {dates[0]} to {dates[-1]}")


if __name__ == "__main__":
    main()
