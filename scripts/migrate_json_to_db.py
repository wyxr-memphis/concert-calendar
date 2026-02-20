#!/usr/bin/env python3
"""One-time migration: import events from data/events.json into PostgreSQL.

Usage:
    DATABASE_URL=... python scripts/migrate_json_to_db.py

Features:
    - Idempotent: uses UPSERT to avoid duplicates on re-run
    - Maps existing event fields to the PostgreSQL schema
    - Prints a summary of imported events
"""

import json
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).parent.parent
EVENTS_JSON_PATH = ROOT / "data" / "events.json"
DATABASE_URL = os.environ.get("DATABASE_URL", "")


def main():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable is required")
        sys.exit(1)

    # Load events.json
    if not EVENTS_JSON_PATH.exists():
        print(f"ERROR: {EVENTS_JSON_PATH} not found")
        sys.exit(1)

    with open(EVENTS_JSON_PATH, "r") as f:
        data = json.load(f)

    events = data.get("events", [])
    print(f"Found {len(events)} events in {EVENTS_JSON_PATH}")

    if not events:
        print("Nothing to migrate.")
        return

    # Connect to database
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Ensure table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          title TEXT NOT NULL,
          venue TEXT,
          date DATE NOT NULL,
          start_time TEXT,
          doors_time TEXT,
          ticket_url TEXT,
          ticket_price TEXT,
          image_url TEXT,
          description TEXT,
          genre TEXT,
          source TEXT DEFAULT 'manual',
          is_featured BOOLEAN DEFAULT false,
          is_active BOOLEAN DEFAULT true,
          created_at TIMESTAMPTZ DEFAULT NOW(),
          updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    conn.commit()

    imported = 0
    skipped = 0
    errors = 0

    for evt in events:
        title = (evt.get("title") or "").strip()
        date_str = evt.get("date", "")

        if not title or not date_str:
            skipped += 1
            continue

        try:
            # Use title + venue + date as the dedup key
            # Check if a matching event already exists
            cur.execute(
                """SELECT id FROM events
                   WHERE LOWER(title) = LOWER(%s)
                     AND LOWER(COALESCE(venue, '')) = LOWER(COALESCE(%s, ''))
                     AND date = %s::date""",
                (title, evt.get("venue", ""), date_str),
            )
            existing = cur.fetchone()

            if existing:
                # Update existing event
                cur.execute(
                    """UPDATE events SET
                        start_time = COALESCE(%s, start_time),
                        doors_time = COALESCE(%s, doors_time),
                        ticket_url = COALESCE(%s, ticket_url),
                        ticket_price = COALESCE(%s, ticket_price),
                        image_url = COALESCE(%s, image_url),
                        description = COALESCE(%s, description),
                        genre = COALESCE(%s, genre),
                        source = COALESCE(%s, source),
                        is_featured = %s,
                        is_active = %s,
                        updated_at = NOW()
                    WHERE id = %s""",
                    (
                        evt.get("start_time"),
                        evt.get("doors_time"),
                        evt.get("ticket_url"),
                        evt.get("ticket_price"),
                        evt.get("image_url"),
                        evt.get("description"),
                        evt.get("genre"),
                        evt.get("source"),
                        evt.get("is_featured", False),
                        evt.get("is_active", True),
                        existing["id"],
                    ),
                )
                skipped += 1
            else:
                # Insert new event
                cur.execute(
                    """INSERT INTO events
                        (title, venue, date, start_time, doors_time,
                         ticket_url, ticket_price, image_url, description,
                         genre, source, is_featured, is_active,
                         created_at, updated_at)
                    VALUES (%s, %s, %s::date, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            COALESCE(%s::timestamptz, NOW()),
                            COALESCE(%s::timestamptz, NOW()))""",
                    (
                        title,
                        evt.get("venue"),
                        date_str,
                        evt.get("start_time"),
                        evt.get("doors_time"),
                        evt.get("ticket_url"),
                        evt.get("ticket_price"),
                        evt.get("image_url"),
                        evt.get("description"),
                        evt.get("genre"),
                        evt.get("source", "import"),
                        evt.get("is_featured", False),
                        evt.get("is_active", True),
                        evt.get("created_at"),
                        evt.get("updated_at"),
                    ),
                )
                imported += 1

        except Exception as e:
            print(f"  Error importing '{title}' on {date_str}: {e}")
            conn.rollback()
            errors += 1
            continue

    conn.commit()

    # Summary
    cur.execute("SELECT MIN(date) AS min_date, MAX(date) AS max_date, COUNT(*) AS total FROM events")
    summary = cur.fetchone()

    print(f"\nMigration complete:")
    print(f"  Imported: {imported}")
    print(f"  Skipped (already existed or missing data): {skipped}")
    print(f"  Errors: {errors}")
    if summary:
        print(f"  Total events in DB: {summary['total']}")
        print(f"  Date range: {summary['min_date']} to {summary['max_date']}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
