#!/usr/bin/env python3
"""Cleanup duplicate events in the database.

Finds events with the same normalized title, venue, and date, then keeps
the best one (most detail, manual source preferred) and removes the rest.

Usage:
    python scripts/cleanup_duplicates.py              # Dry run (show what would be deleted)
    python scripts/cleanup_duplicates.py --confirm    # Actually delete duplicates
"""

import os
import sys
from pathlib import Path
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import normalize_text

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set")
    sys.exit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip3 install psycopg2-binary")
    sys.exit(1)


def normalized_key(title: str, venue: str, date: str) -> str:
    """Compute normalized key for matching."""
    return f"{normalize_text(title)}|{normalize_text(venue)}|{date}"


def detail_score(event: dict) -> int:
    """Score how much detail an event has."""
    score = 0

    # Manual/admin sources are preferred
    if event.get("source") in ("admin", "manual"):
        score += 100

    # More detail = higher score
    if event.get("start_time"):
        score += 10
    if event.get("ticket_url"):
        score += 5
    if event.get("image_url"):
        score += 3
    if event.get("description"):
        score += 2
    if event.get("is_featured"):
        score += 20

    # Prefer certain sources
    if "Ticketmaster" in (event.get("source") or ""):
        score += 5
    elif "Venue:" in (event.get("source") or ""):
        score += 3

    return score


def main():
    dry_run = "--confirm" not in sys.argv

    print("🔍 Finding duplicate events in database...")
    if dry_run:
        print("   (DRY RUN - use --confirm to actually delete)")
    print()

    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Load all active events
    cur.execute("""
        SELECT id, title, venue, date, start_time, ticket_url, image_url,
               description, source, is_featured, is_active
        FROM events
        WHERE is_active = true
        ORDER BY date, venue, title
    """)
    events = cur.fetchall()

    print(f"📊 Total active events: {len(events)}")

    # Group by normalized key
    groups = defaultdict(list)
    for event in events:
        key = normalized_key(
            event["title"] or "",
            event["venue"] or "",
            str(event["date"])
        )
        groups[key].append(dict(event))

    # Find duplicates
    duplicates = {k: v for k, v in groups.items() if len(v) > 1}

    if not duplicates:
        print("✅ No duplicates found!")
        conn.close()
        return

    print(f"⚠️  Found {len(duplicates)} sets of duplicates:")
    print()

    to_delete = []
    kept_count = 0

    for key, dup_events in duplicates.items():
        # Sort by detail score (highest first)
        dup_events.sort(key=detail_score, reverse=True)

        keep = dup_events[0]
        delete = dup_events[1:]

        print(f"📅 {keep['date']} — {keep['title']} @ {keep['venue']}")
        print(f"   Found {len(dup_events)} copies:")
        print(f"   ✅ KEEP: {keep['id']} (source: {keep['source']}, score: {detail_score(keep)})")

        for dup in delete:
            print(f"   ❌ DELETE: {dup['id']} (source: {dup['source']}, score: {detail_score(dup)})")
            to_delete.append(str(dup['id']))

        print()
        kept_count += 1

    print(f"📊 Summary:")
    print(f"   Events to keep: {kept_count}")
    print(f"   Events to delete: {len(to_delete)}")
    print()

    if dry_run:
        print("🔒 DRY RUN complete. Run with --confirm to actually delete these duplicates.")
        conn.close()
        return

    # Delete duplicates
    if to_delete:
        print("🗑️  Deleting duplicates...")
        placeholders = ", ".join(["%s"] * len(to_delete))
        cur.execute(f"DELETE FROM events WHERE id IN ({placeholders})", to_delete)
        deleted = cur.rowcount
        conn.commit()
        print(f"✅ Deleted {deleted} duplicate events")

    conn.close()
    print()
    print("✨ Cleanup complete!")


if __name__ == "__main__":
    main()
