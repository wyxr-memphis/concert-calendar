#!/usr/bin/env python3
"""Memphis Concert Calendar — Main Runner

Fetches events from all configured sources, deduplicates, and generates
a static HTML page for GitHub Pages.

Usage:
    python -m src.main              # Normal run
    python -m src.main --dry-run    # Print results without writing files
"""

import sys
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import Event, SourceResult
from src.normalize import deduplicate
from src.generate_html import generate_html
from src.config import START_DATE, END_DATE

from src.sources import (
    ticketmaster,
    dice,
    memphis_flyer,
    google_sheet,
    venue_scrapers,
    artifacts,
)

# Output paths
DOCS_DIR = Path(__file__).parent.parent / "docs"
INDEX_PATH = DOCS_DIR / "index.html"
LOG_PATH = DOCS_DIR / "log.json"


def run(dry_run: bool = False) -> None:
    """Main execution: fetch → deduplicate → generate → save."""
    run_timestamp = datetime.now()
    print(f"\n{'='*60}")
    print(f"MEMPHIS CONCERT CALENDAR — {run_timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"{'='*60}\n")

    # ---- STEP 1: Fetch from all sources ----
    all_source_results: List[SourceResult] = []
    all_events: List[Event] = []

    sources = [
        ("Ticketmaster", ticketmaster.fetch),
        ("DICE", dice.fetch),
        ("Memphis Flyer", memphis_flyer.fetch),
        ("Google Sheet", google_sheet.fetch),
        ("Artifacts", artifacts.fetch),
    ]

    for source_name, fetch_fn in sources:
        print(f"  Fetching: {source_name}...", end=" ", flush=True)
        try:
            result = fetch_fn()
            all_source_results.append(result)
            all_events.extend(result.events)
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
            all_events.extend(vr.events)
            print(f"    {vr.status_line}")
    except Exception as e:
        error_result = SourceResult(
            source_name="Venue Websites",
            success=False,
            error_message=f"Unhandled exception: {str(e)[:100]}",
        )
        all_source_results.append(error_result)
        print(f"    {error_result.status_line}")

    # ---- STEP 2: Deduplicate ----
    print(f"\n  Raw events collected: {len(all_events)}")
    deduped = deduplicate(all_events)
    print(f"  After deduplication: {len(deduped)}")

    # ---- STEP 3: Generate HTML ----
    html = generate_html(deduped, all_source_results, run_timestamp)

    if dry_run:
        print(f"\n{'='*60}")
        print("DRY RUN — Not writing files")
        print(f"{'='*60}\n")
        _print_summary(deduped)
        return

    # ---- STEP 4: Write output files ----
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  ✅ Wrote {INDEX_PATH}")

    # Write log
    log_data = {
        "run_timestamp": run_timestamp.isoformat(),
        "date_range": {"start": START_DATE.isoformat(), "end": END_DATE.isoformat()},
        "total_raw_events": len(all_events),
        "total_deduped_events": len(deduped),
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
            for e in deduped
        ],
    }

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2)
    print(f"  ✅ Wrote {LOG_PATH}")

    # Summary
    _print_summary(deduped)

    # ---- STEP 5: Check for failures ----
    failures = [sr for sr in all_source_results if not sr.success]
    if failures:
        print(f"\n  ⚠️  {len(failures)} source(s) had errors — check log.json for details")
        for f in failures:
            print(f"     - {f.source_name}: {f.error_message}")


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
        print(f"\n━━━ {day_name} ━━━")
        for e in by_date[d]:
            print(f"  {e.display_line}")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
