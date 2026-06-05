#!/usr/bin/env python3
"""One-time migration: backfill events.dedup_key and create the partial unique index.

dedup_key is the canonical identity of an event — normalized title + canonical
venue (resolved against the venues table) + date — computed by
src.models.compute_dedup_key. Once every active row has a unique dedup_key, a
partial unique index makes duplicate active events structurally impossible.

Run order (see docs/plan):
    1. python scripts/cleanup_duplicates.py --confirm   # remove existing dupes
    2. python scripts/backfill_dedup_key.py             # dry run: backfill + report
    3. python scripts/backfill_dedup_key.py --create-index   # backfill + build index

This script is idempotent. It will NOT create the index while active dedup_key
collisions remain — it lists them so you can re-run cleanup first.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import compute_dedup_key

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


def _venue_canonical_map(cur) -> dict:
    """{lowercased name-or-alias: canonical_name} from the venues table."""
    cur.execute("SELECT name, aliases FROM venues")
    m = {}
    for v in cur.fetchall():
        canonical = v["name"]
        m[canonical.lower()] = canonical
        for alias in (v.get("aliases") or []):
            m[alias.lower()] = canonical
    return m


def main():
    create_index = "--create-index" in sys.argv

    conn = psycopg2.connect(DATABASE_URL, connect_timeout=15)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Ensure the column exists.
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS dedup_key TEXT")
    conn.commit()

    canon_map = _venue_canonical_map(cur)

    cur.execute("SELECT id, title, venue, date, is_active FROM events")
    rows = cur.fetchall()
    print(f"📊 Total events: {len(rows)}", flush=True)

    # Compute dedup_key for every row using the canonical venue.
    payload = []  # (id, dedup_key)
    active_groups = defaultdict(list)
    for row in rows:
        venue = row["venue"] or ""
        canonical_venue = canon_map.get(venue.lower(), venue)
        key = compute_dedup_key(row["title"] or "", canonical_venue, str(row["date"]))
        payload.append((row["id"], key))
        if row["is_active"]:
            active_groups[key].append(row)

    # Batch-update in a single round-trip via UPDATE ... FROM (VALUES ...).
    psycopg2.extras.execute_values(
        cur,
        "UPDATE events SET dedup_key = data.k "
        "FROM (VALUES %s) AS data(id, k) WHERE events.id = data.id::uuid",
        [(str(i), k) for i, k in payload],
        page_size=500,
    )
    conn.commit()
    print(f"✅ Backfilled dedup_key on {len(payload)} rows", flush=True)

    # Report active collisions — these would block the unique index.
    collisions = {k: v for k, v in active_groups.items() if len(v) > 1}
    if collisions:
        print(f"\n⚠️  {len(collisions)} active dedup_key collisions remain "
              f"({sum(len(v) - 1 for v in collisions.values())} redundant rows):")
        for k, v in sorted(collisions.items(), key=lambda x: -len(x[1]))[:20]:
            sample = v[0]
            print(f"   {len(v):3d}  {sample['title']} @ {sample['venue']} ({sample['date']})")
        print("\n   Run: python scripts/cleanup_duplicates.py --confirm  then re-run this script.")
    else:
        print("✅ No active dedup_key collisions.")

    conn.close()

    if not create_index:
        print("\n🔒 Dry run (no index created). Re-run with --create-index when collisions are 0.")
        return

    if collisions:
        print("\n❌ Refusing to create unique index while collisions remain.")
        sys.exit(1)

    # CREATE INDEX CONCURRENTLY must run outside a transaction.
    conn2 = psycopg2.connect(DATABASE_URL, connect_timeout=15)
    conn2.autocommit = True
    cur2 = conn2.cursor()
    print("\n🔧 Creating partial unique index idx_events_dedup_key (CONCURRENTLY)...")
    cur2.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedup_key "
        "ON events (dedup_key) WHERE is_active"
    )
    conn2.close()
    print("✨ Index created. Duplicate active events are now structurally prevented.")


if __name__ == "__main__":
    main()
