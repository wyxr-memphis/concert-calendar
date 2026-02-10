#!/usr/bin/env python3
"""
WYXR Memphis Concert Calendar — Daily Aggregator
Fetches live music events from multiple sources, deduplicates, and generates
a static HTML page for on-air DJ reference.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sources.bandsintown import fetch_bandsintown
from scripts.sources.ticketmaster import fetch_ticketmaster
from scripts.sources.eventbrite import fetch_eventbrite
from scripts.sources.dice import fetch_dice
from scripts.sources.memphis_flyer import fetch_memphis_flyer
from scripts.sources.venues import fetch_all_venues
from scripts.sources.google_sheets import fetch_manual_events
from scripts.utils.filter import filter_music_events
from scripts.utils.dedup import deduplicate_events
from scripts.utils.formatter import format_events_by_date
from scripts.generate_page import generate_html

# --- Configuration ---
MEMPHIS_TZ = ZoneInfo("America/Chicago")
DAYS_AHEAD = 7  # Rolling 7-day window
OUTPUT_DIR = PROJECT_ROOT / "docs"
LOG_DIR = PROJECT_ROOT / "logs"

# --- Logging Setup ---
LOG_DIR.mkdir(exist_ok=True)
log_date = datetime.now(MEMPHIS_TZ).strftime("%Y-%m-%d")
log_file = LOG_DIR / f"{log_date}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("concert-calendar")


def get_date_range():
    """Return (start, end) dates: tomorrow through +DAYS_AHEAD."""
    now = datetime.now(MEMPHIS_TZ)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = tomorrow + timedelta(days=DAYS_AHEAD)
    return tomorrow, end


def run():
    """Main pipeline: fetch → filter → dedup → format → publish."""
    logger.info("=" * 60)
    logger.info("WYXR Concert Calendar — Starting daily run")
    logger.info("=" * 60)

    tomorrow, end_date = get_date_range()
    logger.info(f"Date range: {tomorrow.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")

    all_events = []
    source_status = {}

    # --- Fetch from each source ---
    sources = [
        ("Bandsintown", fetch_bandsintown),
        ("Ticketmaster", fetch_ticketmaster),
        ("Eventbrite", fetch_eventbrite),
        ("DICE", fetch_dice),
        ("Memphis Flyer", fetch_memphis_flyer),
        ("Venue Calendars", fetch_all_venues),
        ("Manual (Google Sheets)", fetch_manual_events),
    ]

    for name, fetch_fn in sources:
        logger.info(f"--- Fetching: {name} ---")
        try:
            events = fetch_fn(tomorrow, end_date)
            count = len(events)
            all_events.extend(events)
            source_status[name] = {"status": "ok", "count": count}
            logger.info(f"  ✅ {name}: {count} events found")
        except Exception as e:
            source_status[name] = {"status": "error", "message": str(e)}
            logger.error(f"  ❌ {name}: {e}")

    logger.info(f"\nTotal raw events: {len(all_events)}")

    # --- Filter non-music events ---
    music_events = filter_music_events(all_events)
    filtered_count = len(all_events) - len(music_events)
    logger.info(f"Filtered out {filtered_count} non-music events. Remaining: {len(music_events)}")

    # --- Deduplicate ---
    unique_events = deduplicate_events(music_events)
    dedup_count = len(music_events) - len(unique_events)
    logger.info(f"Removed {dedup_count} duplicates. Final count: {len(unique_events)}")

    # --- Format by date ---
    events_by_date = format_events_by_date(unique_events, tomorrow, end_date)

    # --- Generate HTML ---
    OUTPUT_DIR.mkdir(exist_ok=True)
    now = datetime.now(MEMPHIS_TZ)
    html = generate_html(events_by_date, source_status, now)

    output_path = OUTPUT_DIR / "index.html"
    output_path.write_text(html, encoding="utf-8")
    logger.info(f"Published to {output_path}")

    # --- Save source status as JSON (for debugging) ---
    status_path = OUTPUT_DIR / "status.json"
    status_data = {
        "last_run": now.isoformat(),
        "date_range": {
            "start": tomorrow.strftime("%Y-%m-%d"),
            "end": end_date.strftime("%Y-%m-%d"),
        },
        "total_raw": len(all_events),
        "total_filtered": len(music_events),
        "total_final": len(unique_events),
        "sources": source_status,
    }
    status_path.write_text(json.dumps(status_data, indent=2), encoding="utf-8")

    logger.info("Done! ✅")
    return 0


if __name__ == "__main__":
    sys.exit(run())
