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
from datetime import date, datetime
from pathlib import Path
from typing import List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import Event, SourceResult
from src.normalize import deduplicate
from src.generate_html import generate_html
from src.config import START_DATE, END_DATE, VENUES

from src.sources import (
    ticketmaster,
    google_sheet,
    venue_scrapers,
    artifacts,
)

# Output paths
DOCS_DIR = Path(__file__).parent.parent / "docs"
INDEX_PATH = DOCS_DIR / "index.html"
LOG_PATH = DOCS_DIR / "log.json"
CACHE_PATH = DOCS_DIR / "source_cache.json"

# Sources that should always be fetched fresh (never cached)
ALWAYS_FRESH = {"Manual (Google Sheet)", "Manual (local CSV)"}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    """Load the source cache file. Returns empty structure on any error."""
    try:
        if CACHE_PATH.exists():
            with open(CACHE_PATH, "r") as f:
                data = json.load(f)
            if isinstance(data, dict) and "sources" in data:
                return data
    except (json.JSONDecodeError, KeyError, TypeError, OSError) as e:
        print(f"  Warning: Cache file corrupt or unreadable ({e}), starting fresh")
    return {"cache_date": None, "sources": {}, "artifact_hashes": {}, "artifact_events": {}}


def _save_cache(cache: dict) -> None:
    """Write source cache to docs/source_cache.json."""
    cache["cache_date"] = date.today().isoformat()
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    print(f"  Wrote {CACHE_PATH}")


def _is_cached_today(cache: dict, source_name: str) -> bool:
    """Check if source was successfully fetched today."""
    entry = cache.get("sources", {}).get(source_name)
    if not entry:
        return False
    if not entry.get("success", False):
        return False
    return entry.get("fetched_date") == date.today().isoformat()


def _events_from_cache(cache: dict, source_name: str) -> SourceResult:
    """Reconstruct a SourceResult from cached data."""
    entry = cache["sources"][source_name]
    events = []
    for e in entry.get("events", []):
        try:
            event_date = date.fromisoformat(e["date"])
            # Re-filter against current date range
            if not (START_DATE <= event_date <= END_DATE):
                continue
            events.append(Event(
                artist=e["artist"],
                venue=e["venue"],
                date=event_date,
                time=e.get("time"),
                source=e.get("source", source_name),
                url=e.get("url"),
            ))
        except (KeyError, ValueError):
            continue
    return SourceResult(
        source_name=source_name,
        events=events,
        success=True,
        events_found=entry.get("events_found", len(events)),
        events_filtered=entry.get("events_filtered", 0),
    )


def _cache_source_result(cache: dict, source_name: str, result: SourceResult) -> None:
    """Store a source result in the cache dict (in memory, not written to disk yet)."""
    cache["sources"][source_name] = {
        "fetched_date": date.today().isoformat(),
        "success": result.success,
        "events_found": result.events_found,
        "events_filtered": result.events_filtered,
        "error_message": result.error_message,
        "events": [
            {
                "artist": e.artist,
                "venue": e.venue,
                "date": e.date.isoformat(),
                "time": e.time,
                "source": e.source,
                "url": e.url,
            }
            for e in result.events
        ],
    }


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> None:
    """Main execution: fetch → deduplicate → generate → save."""
    run_timestamp = datetime.now()
    print(f"\n{'='*60}")
    print(f"MEMPHIS CONCERT CALENDAR — {run_timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"{'='*60}\n")

    # ---- Load cache ----
    cache = _load_cache()

    # ---- STEP 1: Fetch from all sources ----
    all_source_results: List[SourceResult] = []
    all_events: List[Event] = []

    # Ticketmaster — cacheable
    print(f"  Fetching: Ticketmaster...", end=" ", flush=True)
    if _is_cached_today(cache, "Ticketmaster"):
        result = _events_from_cache(cache, "Ticketmaster")
        print(f"(cached) {result.status_line}")
    else:
        try:
            result = ticketmaster.fetch()
            _cache_source_result(cache, result.source_name, result)
            print(result.status_line)
        except Exception as e:
            result = SourceResult(
                source_name="Ticketmaster",
                success=False,
                error_message=f"Unhandled exception: {str(e)[:100]}",
            )
            print(result.status_line)
    all_source_results.append(result)
    all_events.extend(result.events)

    # Google Sheet — always fresh
    print(f"  Fetching: Google Sheet...", end=" ", flush=True)
    try:
        result = google_sheet.fetch()
        print(result.status_line)
    except Exception as e:
        result = SourceResult(
            source_name="Google Sheet",
            success=False,
            error_message=f"Unhandled exception: {str(e)[:100]}",
        )
        print(result.status_line)
    all_source_results.append(result)
    all_events.extend(result.events)

    # Artifacts — hash-based caching (per file)
    print(f"  Fetching: Artifacts...", end=" ", flush=True)
    try:
        result = artifacts.fetch(cache)
        print(result.status_line)
    except Exception as e:
        result = SourceResult(
            source_name="Artifacts (Vision-Extracted)",
            success=False,
            error_message=f"Unhandled exception: {str(e)[:100]}",
        )
        print(result.status_line)
    all_source_results.append(result)
    all_events.extend(result.events)

    # Venue scrapers — cached per venue
    print(f"\n  Fetching: Venue Websites...")
    try:
        for venue_key, venue_info in VENUES.items():
            url = venue_info.get("calendar_url")
            scraper_type = venue_info.get("scraper", "generic")
            if not url or scraper_type == "manual_only":
                continue

            source_key = f"Venue: {venue_info['name']}"

            if _is_cached_today(cache, source_key):
                vr = _events_from_cache(cache, source_key)
                print(f"    (cached) {vr.status_line}")
            else:
                vr = venue_scrapers.scrape_venue(venue_key, venue_info)
                _cache_source_result(cache, source_key, vr)
                print(f"    {vr.status_line}")
            all_source_results.append(vr)
            all_events.extend(vr.events)
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
    print(f"\n  Wrote {INDEX_PATH}")

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
    print(f"  Wrote {LOG_PATH}")

    # Write build timestamp for upload page footer
    build_time_path = DOCS_DIR / "build_time.txt"
    with open(build_time_path, "w", encoding="utf-8") as f:
        f.write(run_timestamp.strftime("%B %-d, %Y at %-I:%M %p CT"))
    print(f"  Wrote {build_time_path}")

    # Save source cache
    _save_cache(cache)

    # Summary
    _print_summary(deduped)

    # ---- STEP 5: Check for failures ----
    failures = [sr for sr in all_source_results if not sr.success]
    if failures:
        print(f"\n  {len(failures)} source(s) had errors — check log.json for details")
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
