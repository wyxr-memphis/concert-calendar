#!/usr/bin/env python3
"""One-time script to merge duplicate venue records.

Merges non-canonical duplicates into the seeded canonical names so that
the seed data's ON CONFLICT check prevents re-creation on backend restarts.

Usage:
    python scripts/merge_venue_duplicates.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db import get_all_venues, merge_venues

# (canonical_name, duplicate_name) — keep canonical, merge duplicate into it
MERGES = [
    ("Hernando's Hideaway", "Hernando's Hide-A-Way"),
    ("B-Side Memphis", "B-Side Bar"),
    ("Growlers", "Growler's"),
]


def main():
    venues = get_all_venues()
    venue_by_name = {v["name"].lower(): v for v in venues}

    any_done = False
    for canonical, duplicate in MERGES:
        keep = venue_by_name.get(canonical.lower())
        merge = venue_by_name.get(duplicate.lower())

        if not keep:
            print(f"  SKIP: canonical '{canonical}' not found in DB")
            continue
        if not merge:
            print(f"  SKIP: duplicate '{duplicate}' not found in DB (already merged?)")
            continue

        print(f"Merging '{duplicate}' ({merge['event_count']} events) → '{canonical}' ({keep['event_count']} events)")
        result = merge_venues(keep["id"], merge["id"])
        if result:
            print(f"  Done: {result['events_updated']} events updated, aliases: {result['aliases']}")
            any_done = True
        else:
            print(f"  ERROR: merge_venues returned None")

    if not any_done:
        print("Nothing to merge.")


if __name__ == "__main__":
    main()
