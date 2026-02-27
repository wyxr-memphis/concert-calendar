#!/usr/bin/env python3
"""Clean duplicate events from the database.

Identifies duplicates by normalized (title, venue, date) and keeps the one
with the most detail (preferring entries with ticket URLs, times, featured status).
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import normalize_text

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set")
    sys.exit(1)


def normalize_key(title, venue, date):
    """Generate normalized key for deduplication."""
    return f"{normalize_text(title or '')}|{normalize_text(venue or '')}|{date}"


def get_detail_score(event):
    """Score how much detail an event has (higher = better)."""
    score = 0
    if event.get("start_time"):
        score += 2
    if event.get("ticket_url"):
        score += 2
    if event.get("is_featured"):
        score += 1
    if event.get("image_url"):
        score += 1
    if event.get("description"):
        score += 1
    # Prefer certain sources
    source = event.get("source", "")
    if "ticketmaster" in source.lower():
        score += 2
    elif "venue:" in source.lower():
        score += 1
    return score


def clean_duplicates(dry_run=True):
    """Find and remove duplicate events, keeping the best version."""
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Load all events
    cur.execute("SELECT * FROM events ORDER BY date, venue, title")
    all_events = cur.fetchall()

    print(f"Loaded {len(all_events)} total events from database")

    # Group by normalized key
    groups = {}
    for event in all_events:
        key = normalize_key(event["title"], event["venue"], str(event["date"]))
        if key not in groups:
            groups[key] = []
        groups[key].append(dict(event))

    # Find duplicates
    duplicates_found = 0
    events_to_delete = []

    for key, group in groups.items():
        if len(group) <= 1:
            continue

        duplicates_found += len(group) - 1

        # Sort by detail score (descending)
        group.sort(key=get_detail_score, reverse=True)

        keeper = group[0]
        to_delete = group[1:]

        print(f"\n{'='*60}")
        print(f"Duplicate group (normalized: {key[:80]}...)")
        print(f"  KEEPING: {keeper['title']} @ {keeper['venue']} on {keeper['date']}")
        print(f"           ID: {keeper['id']}, Source: {keeper['source']}, Score: {get_detail_score(keeper)}")
        print(f"  REMOVING:")
        for dup in to_delete:
            print(f"           {dup['title']} @ {dup['venue']} on {dup['date']}")
            print(f"           ID: {dup['id']}, Source: {dup['source']}, Score: {get_detail_score(dup)}")
            events_to_delete.append(dup['id'])

    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Total events: {len(all_events)}")
    print(f"  Duplicate events found: {duplicates_found}")
    print(f"  Events to delete: {len(events_to_delete)}")
    print(f"  Events after cleanup: {len(all_events) - len(events_to_delete)}")

    if dry_run:
        print("\n[DRY RUN] No changes made to database.")
        print("Run with --execute to actually delete duplicates.")
    else:
        if events_to_delete:
            print("\n[EXECUTING] Deleting duplicates...")
            # Delete in batches to avoid query too large
            batch_size = 100
            for i in range(0, len(events_to_delete), batch_size):
                batch = events_to_delete[i:i+batch_size]
                placeholders = ','.join(['%s'] * len(batch))
                cur.execute(f"DELETE FROM events WHERE id IN ({placeholders})", batch)
            conn.commit()
            print(f"✓ Deleted {len(events_to_delete)} duplicate events")
        else:
            print("\nNo duplicates to delete!")

    conn.close()


if __name__ == "__main__":
    dry_run = "--execute" not in sys.argv
    clean_duplicates(dry_run=dry_run)
