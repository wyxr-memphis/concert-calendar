#!/usr/bin/env python3
"""Move events from one venue string to another.

Written for the case where an import lands events under a placeholder venue
("Unknown Venue", "Venue TBA") because the flyer never printed the venue name.
Rewrites venue + neighborhood and recomputes dedup_key so the rows stay
consistent with the partial unique index.

    # preview
    python scripts/reassign_venue.py --from "Unknown Venue" --to "B-Side Memphis"

    # apply
    python scripts/reassign_venue.py --from "Unknown Venue" --to "B-Side Memphis" --confirm

Optional --since / --until (YYYY-MM-DD) narrow the rows touched.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import get_cursor, normalize_venue_from_db, update_event  # noqa: E402
from src.models import compute_dedup_key  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_venue", required=True, help="Current venue string (exact, case-insensitive)")
    ap.add_argument("--to", dest="to_venue", required=True, help="Target venue name (must exist in the venues table)")
    ap.add_argument("--since", help="Only events on/after this date (YYYY-MM-DD)")
    ap.add_argument("--until", help="Only events on/before this date (YYYY-MM-DD)")
    ap.add_argument("--confirm", action="store_true", help="Actually write the changes")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set")
        return 1

    # Resolve the target through the venues table so we pick up its canonical
    # casing and neighborhood instead of trusting what was typed.
    canon = normalize_venue_from_db(args.to_venue)
    if not canon or not canon[0]:
        print(f"'{args.to_venue}' is not a known venue (name or alias) in the venues table.")
        print("Add it in Admin → Venues first, or pass the exact canonical name.")
        return 1
    target_venue, target_neighborhood = canon[0], canon[1]

    where = ["LOWER(venue) = LOWER(%s)", "is_active = TRUE"]
    params = [args.from_venue]
    if args.since:
        where.append("date >= %s")
        params.append(args.since)
    if args.until:
        where.append("date <= %s")
        params.append(args.until)

    with get_cursor(commit=False) as cur:
        cur.execute(
            f"SELECT id, title, venue, date FROM events WHERE {' AND '.join(where)} ORDER BY date, title",
            params,
        )
        rows = cur.fetchall()

    if not rows:
        print(f"No active events found with venue '{args.from_venue}'.")
        return 0

    # A row whose new dedup_key already exists would violate the unique index,
    # so report those and leave them alone rather than failing mid-batch.
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT dedup_key FROM events WHERE is_active = TRUE AND dedup_key IS NOT NULL")
        existing_keys = {r["dedup_key"] for r in cur.fetchall()}

    movable, blocked = [], []
    for r in rows:
        new_key = compute_dedup_key(r["title"], target_venue, r["date"].isoformat())
        (blocked if new_key in existing_keys else movable).append((r, new_key))
        existing_keys.add(new_key)

    print(f"{len(rows)} event(s) at '{args.from_venue}' → '{target_venue}'")
    if target_neighborhood:
        print(f"  neighborhood → {target_neighborhood}")
    for r, _ in movable:
        print(f"  {r['date']}  {r['title']}")
    for r, key in blocked:
        print(f"  SKIP (duplicate of an existing {target_venue} event) {r['date']}  {r['title']}")

    if not args.confirm:
        print(f"\nDry run. Re-run with --confirm to update {len(movable)} event(s).")
        return 0

    updated = 0
    for r, _ in movable:
        data = {"venue": target_venue}
        if target_neighborhood:
            data["neighborhood"] = target_neighborhood
        if update_event(r["id"], data):
            updated += 1

    print(f"\nUpdated {updated} event(s).")
    if blocked:
        print(f"Skipped {len(blocked)} that would have duplicated an existing event.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
