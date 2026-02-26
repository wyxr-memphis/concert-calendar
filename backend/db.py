"""Database connection and query helpers for PostgreSQL on Render."""

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Register UUID adapter
psycopg2.extras.register_uuid()


def get_connection():
    """Get a new database connection."""
    return psycopg2.connect(DATABASE_URL, connect_timeout=5)


@contextmanager
def get_cursor(commit=True):
    """Context manager that yields a cursor and handles commit/rollback."""
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Run schema creation (idempotent).

    Migrations run in order:
    1. Core tables (events, scrape_logs) — original schema
    2. Add neighborhood column to events (migration)
    3. Create venues table (new)
    4. Create indexes that depend on new columns
    5. Seed venue data
    """
    # Step 1: Core tables (these already exist on production)
    core_sql = """
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
    CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
    CREATE INDEX IF NOT EXISTS idx_events_featured ON events(is_featured) WHERE is_featured = true;

    CREATE TABLE IF NOT EXISTS scrape_logs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      scraper_name TEXT NOT NULL,
      started_at TIMESTAMPTZ NOT NULL,
      finished_at TIMESTAMPTZ,
      status TEXT NOT NULL DEFAULT 'running',
      events_found INTEGER DEFAULT 0,
      events_added INTEGER DEFAULT 0,
      events_updated INTEGER DEFAULT 0,
      events_skipped INTEGER DEFAULT 0,
      error_message TEXT,
      details JSONB
    );
    CREATE INDEX IF NOT EXISTS idx_scrape_logs_started ON scrape_logs(started_at DESC);
    """
    with get_cursor() as cur:
        cur.execute(core_sql)

    # Step 2: Add neighborhood column to events (safe migration)
    with get_cursor() as cur:
        cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS neighborhood TEXT")

    # Step 3: Create venues table
    with get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS venues (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              name TEXT NOT NULL UNIQUE,
              neighborhood TEXT,
              aliases TEXT[] DEFAULT '{}',
              created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_venues_name ON venues(name);
            CREATE INDEX IF NOT EXISTS idx_events_neighborhood ON events(neighborhood);
        """)

    # Step 4: Seed venues if table is empty
    try:
        _seed_venues_if_empty()
    except Exception as e:
        print(f"[init_db] Warning: venue seeding failed: {e}", flush=True)


# ---------------------------------------------------------------------------
# Event queries
# ---------------------------------------------------------------------------

def get_active_events(start_date=None, end_date=None, featured_only=False):
    """Get active events for the public calendar."""
    query = "SELECT * FROM events WHERE is_active = true"
    params = []

    if start_date:
        query += " AND date >= %s"
        params.append(start_date)
    if end_date:
        query += " AND date <= %s"
        params.append(end_date)
    if featured_only:
        query += " AND is_featured = true"

    query += " ORDER BY date ASC, is_featured DESC, start_time ASC"

    with get_cursor(commit=False) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def get_event_by_id(event_id):
    """Get a single event by ID."""
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
        return cur.fetchone()


def get_all_events(start_date=None, end_date=None, include_inactive=True):
    """Get all events for admin view."""
    query = "SELECT * FROM events"
    params = []
    conditions = []

    if not include_inactive:
        conditions.append("is_active = true")
    if start_date:
        conditions.append("date >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("date <= %s")
        params.append(end_date)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY date DESC, start_time ASC"

    with get_cursor(commit=False) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def create_event(data):
    """Insert a new event. Returns the created event."""
    fields = [
        "title", "venue", "date", "start_time", "doors_time",
        "ticket_url", "ticket_price", "image_url", "description",
        "genre", "source", "neighborhood", "is_featured", "is_active",
    ]
    present = {k: data[k] for k in fields if k in data}
    columns = ", ".join(present.keys())
    placeholders = ", ".join(["%s"] * len(present))

    query = f"""
        INSERT INTO events ({columns})
        VALUES ({placeholders})
        RETURNING *
    """
    with get_cursor() as cur:
        cur.execute(query, list(present.values()))
        return cur.fetchone()


def update_event(event_id, data):
    """Update an event. Returns updated event."""
    allowed = [
        "title", "venue", "date", "start_time", "doors_time",
        "ticket_url", "ticket_price", "image_url", "description",
        "genre", "source", "neighborhood", "is_featured", "is_active",
    ]
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        return get_event_by_id(event_id)

    updates["updated_at"] = "NOW()"
    set_clauses = []
    params = []
    for k, v in updates.items():
        if v == "NOW()":
            set_clauses.append(f"{k} = NOW()")
        else:
            set_clauses.append(f"{k} = %s")
            params.append(v)

    params.append(event_id)
    query = f"""
        UPDATE events SET {', '.join(set_clauses)}
        WHERE id = %s
        RETURNING *
    """
    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def soft_delete_event(event_id):
    """Soft-delete: set is_active = false."""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE events SET is_active = false, updated_at = NOW() WHERE id = %s RETURNING *",
            (event_id,),
        )
        return cur.fetchone()


def toggle_featured(event_id, is_featured):
    """Toggle featured status."""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE events SET is_featured = %s, updated_at = NOW() WHERE id = %s RETURNING *",
            (is_featured, event_id),
        )
        return cur.fetchone()


def bulk_action(action, ids):
    """Bulk operations on events."""
    if not ids:
        return 0

    action_map = {
        "feature": "UPDATE events SET is_featured = true, updated_at = NOW()",
        "unfeature": "UPDATE events SET is_featured = false, updated_at = NOW()",
        "deactivate": "UPDATE events SET is_active = false, updated_at = NOW()",
    }
    base_query = action_map.get(action)
    if not base_query:
        raise ValueError(f"Unknown action: {action}")

    query = base_query + " WHERE id = ANY(%s)"
    with get_cursor() as cur:
        cur.execute(query, (ids,))
        return cur.rowcount


def delete_events_before(before_date):
    """Hard-delete events with date before the given date. Returns count deleted."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM events WHERE date < %s", (before_date,))
        return cur.rowcount


def bulk_insert_events(events_list):
    """Insert multiple events at once. Returns list of created events."""
    if not events_list:
        return []

    results = []
    with get_cursor() as cur:
        for data in events_list:
            fields = [
                "title", "venue", "date", "start_time", "doors_time",
                "ticket_url", "ticket_price", "image_url", "description",
                "genre", "source", "neighborhood", "is_featured", "is_active",
            ]
            present = {k: data[k] for k in fields if k in data}
            columns = ", ".join(present.keys())
            placeholders = ", ".join(["%s"] * len(present))
            query = f"INSERT INTO events ({columns}) VALUES ({placeholders}) RETURNING *"
            cur.execute(query, list(present.values()))
            results.append(cur.fetchone())

    return results


# ---------------------------------------------------------------------------
# Scrape log queries
# ---------------------------------------------------------------------------

def create_scrape_log(scraper_name, started_at):
    """Create a new scrape log entry with status='running'."""
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO scrape_logs (scraper_name, started_at, status)
               VALUES (%s, %s, 'running') RETURNING *""",
            (scraper_name, started_at),
        )
        return cur.fetchone()


def update_scrape_log(log_id, data):
    """Update a scrape log entry."""
    allowed = [
        "finished_at", "status", "events_found", "events_added",
        "events_updated", "events_skipped", "error_message", "details",
    ]
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        return None

    set_clauses = []
    params = []
    for k, v in updates.items():
        set_clauses.append(f"{k} = %s")
        params.append(v)

    params.append(log_id)
    query = f"UPDATE scrape_logs SET {', '.join(set_clauses)} WHERE id = %s RETURNING *"

    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def get_scrape_logs(limit=20, scraper_name=None):
    """Get recent scrape logs."""
    query = "SELECT * FROM scrape_logs"
    params = []

    if scraper_name:
        query += " WHERE scraper_name = %s"
        params.append(scraper_name)

    query += " ORDER BY started_at DESC LIMIT %s"
    params.append(limit)

    with get_cursor(commit=False) as cur:
        cur.execute(query, params)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Venue queries
# ---------------------------------------------------------------------------

def _seed_venues_if_empty():
    """Seed the venues table with known Memphis venues if empty."""
    _SEED_VENUES = [
        ("Hi Tone", "Midtown", ["hi tone", "hi-tone", "hi tone café", "hi tone cafe", "the hi-tone"]),
        ("Minglewood Hall", "Midtown", ["minglewood", "minglewood hall", "1555 madison"]),
        ("Growlers", "Overton Square/Cooper-Young", ["growlers", "growlers memphis", "901 growlers"]),
        ("Hernando's Hideaway", "Midtown", ["hernandos", "hernando's", "hernandos hideaway", "hernando's hideaway"]),
        ("Crosstown Arts", "Crosstown/Broad Avenue", ["crosstown arts", "the green room", "green room crosstown", "crosstown concourse"]),
        ("Lafayette's Music Room", "Overton Square/Cooper-Young", ["lafayettes", "lafayette's", "lafayettes music room", "lafayette's music room"]),
        ("Overton Park Shell", "Midtown", ["levitt shell", "overton park shell", "the shell"]),
        ("B.B. King's Blues Club", "Downtown/Beale Street", ["bb kings", "b.b. kings", "b.b. king's", "bb king's blues club"]),
        ("Graceland Soundstage", "South Memphis (Graceland/Stax)", ["graceland soundstage", "graceland live", "guest house theater"]),
        ("FedExForum", "Downtown/Beale Street", ["fedexforum", "fedex forum"]),
        ("Germantown Performing Arts Center", "Germantown", ["germantown performing arts", "germantown performing arts center", "gpac"]),
        ("Orpheum Theatre", "Downtown/Beale Street", ["orpheum", "orpheum theatre", "halloran centre"]),
        ("Bar DKDC", "Crosstown/Broad Avenue", ["bar dkdc", "dkdc"]),
        ("B-Side Memphis", "South Main Arts District", ["b-side", "bside", "b side", "b-side memphis"]),
    ]

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS count FROM venues")
        row = cur.fetchone()
        if row and row["count"] > 0:
            return

        for name, neighborhood, aliases in _SEED_VENUES:
            cur.execute(
                """INSERT INTO venues (name, neighborhood, aliases)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (name) DO NOTHING""",
                (name, neighborhood, aliases),
            )


def get_all_venues():
    """Get all venues with event counts."""
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT v.*,
                   COUNT(e.id) FILTER (WHERE e.is_active = true) AS event_count
            FROM venues v
            LEFT JOIN events e ON LOWER(e.venue) = LOWER(v.name)
            GROUP BY v.id
            ORDER BY v.name
        """)
        return cur.fetchall()


def get_venue_by_id(venue_id):
    """Get a single venue by ID."""
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM venues WHERE id = %s", (venue_id,))
        return cur.fetchone()


def create_venue(data):
    """Create a new venue. Returns the created venue."""
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO venues (name, neighborhood, aliases)
               VALUES (%s, %s, %s)
               RETURNING *""",
            (
                data["name"],
                data.get("neighborhood"),
                data.get("aliases", []),
            ),
        )
        return cur.fetchone()


def update_venue(venue_id, data):
    """Update a venue. Returns updated venue."""
    set_clauses = []
    params = []

    if "name" in data:
        set_clauses.append("name = %s")
        params.append(data["name"])
    if "neighborhood" in data:
        set_clauses.append("neighborhood = %s")
        params.append(data["neighborhood"])
    if "aliases" in data:
        set_clauses.append("aliases = %s")
        params.append(data["aliases"])

    if not set_clauses:
        return get_venue_by_id(venue_id)

    params.append(venue_id)
    query = f"UPDATE venues SET {', '.join(set_clauses)} WHERE id = %s RETURNING *"

    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def delete_venue(venue_id):
    """Delete a venue by ID."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM venues WHERE id = %s RETURNING *", (venue_id,))
        return cur.fetchone()


def merge_venues(keep_id, merge_id):
    """Merge merge_venue into keep_venue.

    1. Copy aliases from merge venue + merge venue's name into keep venue's aliases
    2. Update all events with merge venue name → keep venue name + neighborhood
    3. Delete the merge venue
    """
    with get_cursor() as cur:
        # Get both venues
        cur.execute("SELECT * FROM venues WHERE id = %s", (keep_id,))
        keep_venue = cur.fetchone()
        cur.execute("SELECT * FROM venues WHERE id = %s", (merge_id,))
        merge_venue = cur.fetchone()

        if not keep_venue or not merge_venue:
            return None

        # Combine aliases: keep's aliases + merge's aliases + merge's name
        combined_aliases = list(keep_venue.get("aliases") or [])
        combined_aliases.extend(merge_venue.get("aliases") or [])
        if merge_venue["name"] not in combined_aliases:
            combined_aliases.append(merge_venue["name"])
        # Deduplicate
        combined_aliases = list(dict.fromkeys(combined_aliases))

        # Update keep venue's aliases
        cur.execute(
            "UPDATE venues SET aliases = %s WHERE id = %s",
            (combined_aliases, keep_id),
        )

        # Update events: change venue name and set neighborhood
        cur.execute(
            """UPDATE events
               SET venue = %s, neighborhood = %s, updated_at = NOW()
               WHERE LOWER(venue) = LOWER(%s)""",
            (keep_venue["name"], keep_venue.get("neighborhood"), merge_venue["name"]),
        )
        events_updated = cur.rowcount

        # Also update events matching any of merge venue's aliases
        for alias in (merge_venue.get("aliases") or []):
            cur.execute(
                """UPDATE events
                   SET venue = %s, neighborhood = %s, updated_at = NOW()
                   WHERE LOWER(venue) = LOWER(%s)""",
                (keep_venue["name"], keep_venue.get("neighborhood"), alias),
            )
            events_updated += cur.rowcount

        # Delete merge venue
        cur.execute("DELETE FROM venues WHERE id = %s", (merge_id,))

        return {
            "keep_venue": keep_venue["name"],
            "merged_venue": merge_venue["name"],
            "events_updated": events_updated,
            "aliases": combined_aliases,
        }


def normalize_venue_from_db(venue_name):
    """Look up canonical venue name + neighborhood from DB.

    Checks name match first, then alias match.
    Returns (canonical_name, neighborhood) or None.
    """
    if not venue_name:
        return None
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT name, neighborhood FROM venues
               WHERE LOWER(name) = LOWER(%s)
               OR LOWER(%s) = ANY(SELECT LOWER(unnest(aliases)))
               LIMIT 1""",
            (venue_name, venue_name),
        )
        row = cur.fetchone()
        if row:
            return (row["name"], row.get("neighborhood"))
        return None


def get_neighborhoods_with_counts():
    """Get distinct neighborhoods with active event counts."""
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT neighborhood, COUNT(*) AS event_count
            FROM events
            WHERE is_active = true
              AND neighborhood IS NOT NULL
              AND neighborhood != ''
              AND date >= CURRENT_DATE
            GROUP BY neighborhood
            ORDER BY event_count DESC
        """)
        return cur.fetchall()


def backfill_neighborhoods():
    """One-time backfill: assign neighborhoods to existing events based on venue match."""
    with get_cursor() as cur:
        cur.execute("""
            UPDATE events e
            SET neighborhood = v.neighborhood
            FROM venues v
            WHERE LOWER(e.venue) = LOWER(v.name)
              AND e.neighborhood IS NULL
              AND v.neighborhood IS NOT NULL
        """)
        direct = cur.rowcount

        # Also match via aliases
        cur.execute("""
            UPDATE events e
            SET neighborhood = v.neighborhood
            FROM venues v, LATERAL unnest(v.aliases) AS alias
            WHERE LOWER(e.venue) = LOWER(alias)
              AND e.neighborhood IS NULL
              AND v.neighborhood IS NOT NULL
        """)
        alias_match = cur.rowcount

        return {"direct_matches": direct, "alias_matches": alias_match}


def get_scraper_status_summary():
    """Get a dashboard summary of all scrapers."""
    with get_cursor(commit=False) as cur:
        # Get latest run per scraper
        cur.execute("""
            SELECT DISTINCT ON (scraper_name)
                scraper_name, started_at, finished_at, status,
                events_found, events_added, events_updated, events_skipped,
                error_message
            FROM scrape_logs
            ORDER BY scraper_name, started_at DESC
        """)
        latest_runs = cur.fetchall()

        # Get recent errors (last 7 days)
        cur.execute("""
            SELECT scraper_name, started_at, error_message
            FROM scrape_logs
            WHERE status IN ('failed', 'partial')
              AND started_at > NOW() - INTERVAL '7 days'
            ORDER BY started_at DESC
            LIMIT 10
        """)
        recent_errors = cur.fetchall()

        # Total scraped events count
        cur.execute("SELECT COUNT(*) AS count FROM events WHERE source != 'manual' AND source != 'admin'")
        total_row = cur.fetchone()
        total_scraped = total_row["count"] if total_row else 0

    scrapers = []
    for run in latest_runs:
        last_run = run["started_at"]
        # Estimate next run as ~12 hours from last
        next_run = None
        if last_run:
            from datetime import timedelta
            next_run = last_run + timedelta(hours=12)

        scrapers.append({
            "name": run["scraper_name"],
            "last_run": last_run.isoformat() if last_run else None,
            "last_status": run["status"],
            "next_run": next_run.isoformat() if next_run else None,
            "events_added_last_run": run["events_added"],
            "events_updated_last_run": run["events_updated"],
        })

    return {
        "scrapers": scrapers,
        "recent_errors": [
            {
                "scraper": e["scraper_name"],
                "time": e["started_at"].isoformat() if e["started_at"] else None,
                "error": e["error_message"],
            }
            for e in recent_errors
        ],
        "total_scraped_events": total_scraped,
    }
