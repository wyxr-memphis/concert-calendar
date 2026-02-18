#!/usr/bin/env python3
"""Memphis Concert Calendar — Main Runner

Fetches events from automated sources, merges into data/events.json
(preserving admin edits), and generates a static HTML page.

Usage:
    python -m src.main              # Normal run
    python -m src.main --dry-run    # Print results without writing files
"""

import html
import json
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import Event, SourceResult, normalize_text
from src.normalize import deduplicate
from src.generate_html import generate_html
from src.config import START_DATE, END_DATE
from src.sources.events_json import (
    EVENTS_JSON_PATH,
    load_events_json,
    save_events_json,
)

from src.sources import (
    ticketmaster,
    venue_scrapers,
    artifacts,
)

# Output paths
DOCS_DIR = Path(__file__).parent.parent / "docs"
INDEX_PATH = DOCS_DIR / "index.html"
LOG_PATH = DOCS_DIR / "log.json"


def run(dry_run: bool = False) -> None:
    """Main execution: fetch → merge into events.json → generate HTML."""
    run_timestamp = datetime.now(ZoneInfo("UTC"))
    print(f"\n{'='*60}")
    print(f"MEMPHIS CONCERT CALENDAR — {run_timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"{'='*60}\n")

    # ---- STEP 1: Fetch from automated sources ----
    all_source_results: List[SourceResult] = []
    automated_events: List[Event] = []

    sources = [
        ("Ticketmaster", ticketmaster.fetch),
        ("Artifacts", artifacts.fetch),
    ]

    for source_name, fetch_fn in sources:
        print(f"  Fetching: {source_name}...", end=" ", flush=True)
        try:
            result = fetch_fn()
            all_source_results.append(result)
            automated_events.extend(result.events)
            print(result.status_line)
        except Exception as e:
            error_result = SourceResult(
                source_name=source_name,
                success=False,
                error_message=f"Unhandled exception: {str(e)[:100]}",
            )
            all_source_results.append(error_result)
            print(error_result.status_line)

    # Venue scrapers — run individually for better logging
    print(f"\n  Fetching: Venue Websites...")
    try:
        venue_results = venue_scrapers.fetch_individual()
        for vr in venue_results:
            all_source_results.append(vr)
            automated_events.extend(vr.events)
            print(f"    {vr.status_line}")
    except Exception as e:
        error_result = SourceResult(
            source_name="Venue Websites",
            success=False,
            error_message=f"Unhandled exception: {str(e)[:100]}",
        )
        all_source_results.append(error_result)
        print(f"    {error_result.status_line}")

    # Clean HTML entities
    for event in automated_events:
        event.artist = html.unescape(event.artist)
        event.venue = html.unescape(event.venue)

    # Deduplicate automated events among themselves
    print(f"\n  Raw automated events: {len(automated_events)}")
    automated_events = deduplicate(automated_events)
    print(f"  After dedup: {len(automated_events)}")

    # ---- STEP 2: Load current events.json ----
    try:
        events_data = load_events_json()
    except (FileNotFoundError, json.JSONDecodeError):
        events_data = {"version": 1, "updated_at": "", "events": []}

    existing_events = events_data.get("events", [])
    print(f"  Existing events.json entries: {len(existing_events)}")

    # ---- STEP 3: Merge automated events into events.json ----
    merged = _merge_events(existing_events, automated_events, run_timestamp)
    print(f"  After merge: {len(merged)}")

    # ---- STEP 4: Prune past events ----
    today_str = date.today().isoformat()
    before_prune = len(merged)
    merged = [e for e in merged if e.get("date", "") >= today_str]
    pruned = before_prune - len(merged)
    if pruned:
        print(f"  Pruned {pruned} past events (before {today_str})")

    # ---- STEP 5: Write updated events.json ----
    events_data["events"] = merged
    events_data["updated_at"] = run_timestamp.isoformat()

    if not dry_run:
        save_events_json(events_data)
        print(f"  Wrote {len(merged)} events to {EVENTS_JSON_PATH}")

    # ---- STEP 6: Generate HTML from events.json (active events in date range) ----
    active_events = []
    for entry in merged:
        if not entry.get("is_active", True):
            continue
        event = _entry_to_event(entry)
        if event and START_DATE <= event.date <= END_DATE:
            active_events.append(event)

    active_events.sort(key=lambda e: e.sort_key)

    # Add events.json as a "source" for reporting
    ej_result = SourceResult(
        source_name="Events JSON",
        events=active_events,
        events_found=len(active_events),
    )
    all_source_results.append(ej_result)

    html_output = generate_html(active_events, all_source_results, run_timestamp)

    if dry_run:
        print(f"\n{'='*60}")
        print("DRY RUN — Not writing files")
        print(f"{'='*60}\n")
        _print_summary(active_events)
        return

    # ---- STEP 7: Write output files ----
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html_output)
    print(f"\n  Wrote {INDEX_PATH}")

    # Write log
    log_data = {
        "run_timestamp": run_timestamp.isoformat(),
        "date_range": {"start": START_DATE.isoformat(), "end": END_DATE.isoformat()},
        "total_events_json": len(merged),
        "total_active_display": len(active_events),
        "sources": [
            {
                "name": sr.source_name,
                "success": sr.success,
                "events_found": sr.events_found,
                "events_after_filter": len(sr.events),
                "events_filtered": sr.events_filtered,
                "error": sr.error_message,
            }
            for sr in all_source_results
        ],
        "events": [
            {
                "artist": e.artist,
                "venue": e.venue,
                "date": e.date.isoformat(),
                "time": e.time,
                "source": e.source,
            }
            for e in active_events
        ],
    }

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2)
    print(f"  Wrote {LOG_PATH}")

    # Write build timestamp for upload page footer
    build_time_path = DOCS_DIR / "build_time.txt"
    with open(build_time_path, "w", encoding="utf-8") as f:
        f.write(run_timestamp.strftime("%B %-d, %Y at %-I:%M %p CT"))
    print(f"  Wrote {build_time_path}")

    _print_summary(active_events)

    # Check for failures
    failures = [sr for sr in all_source_results if not sr.success]
    if failures:
        print(f"\n  {len(failures)} source(s) had errors — check log.json for details")
        for f in failures:
            print(f"     - {f.source_name}: {f.error_message}")


def _merge_events(
    existing: List[dict],
    automated: List[Event],
    run_timestamp: datetime,
) -> List[dict]:
    """Merge automated events into the existing events.json entries.

    - Admin/manual entries (source: "admin") are never touched
    - Matching automated events update time/url/source but preserve admin fields
    - New automated events are appended
    """
    timestamp = run_timestamp.isoformat()

    # Build lookup of existing entries by normalized key
    existing_by_key: Dict[str, int] = {}
    for i, entry in enumerate(existing):
        key = _normalized_key(entry.get("title", ""), entry.get("venue", ""), entry.get("date", ""))
        existing_by_key[key] = i

    merged = list(existing)  # Start with all existing entries

    for event in automated:
        key = _normalized_key(event.artist, event.venue, event.date.isoformat())

        if key in existing_by_key:
            idx = existing_by_key[key]
            entry = merged[idx]
            # Don't touch admin entries
            if entry.get("source") == "admin":
                continue
            # Update automated fields, preserve admin-editable fields
            entry["start_time"] = event.time or entry.get("start_time")
            entry["ticket_url"] = event.url or entry.get("ticket_url")
            entry["source"] = event.source or entry.get("source")
            entry["updated_at"] = timestamp
        else:
            # New event — add it
            event_id = f"evt_{int(time.time() * 1000)}_{len(merged)}"
            new_entry = {
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
            merged.append(new_entry)
            existing_by_key[key] = len(merged) - 1
            time.sleep(0.001)  # Ensure unique IDs

    return merged


def _normalized_key(title: str, venue: str, date_str: str) -> str:
    """Compute a normalized key for matching: artist|venue|date."""
    return f"{normalize_text(title)}|{normalize_text(venue)}|{date_str}"


def _entry_to_event(entry: dict) -> Event | None:
    """Convert a JSON entry to an Event dataclass."""
    try:
        event_date = date.fromisoformat(entry["date"])
    except (KeyError, ValueError):
        return None

    title = entry.get("title", "").strip()
    venue = entry.get("venue", "").strip()
    if not title or not venue:
        return None

    return Event(
        artist=title,
        venue=venue,
        date=event_date,
        time=entry.get("start_time"),
        source=entry.get("source", "Events JSON"),
        url=entry.get("ticket_url"),
        is_featured=entry.get("is_featured", False),
        event_id=entry.get("id"),
    )


def _print_summary(events: List[Event]) -> None:
    """Print a text summary of events."""
    by_date = defaultdict(list)
    for e in events:
        by_date[e.date].append(e)

    print(f"\n{'='*60}")
    print("EVENT SUMMARY")
    print(f"{'='*60}")

    for d in sorted(by_date.keys()):
        day_name = d.strftime("%A, %B %-d").upper()
        print(f"\n  {day_name}")
        for e in by_date[d]:
            featured = " [FEATURED]" if e.is_featured else ""
            print(f"    {e.display_line}{featured}")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
