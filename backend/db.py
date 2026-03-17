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

    # Step 4: Create submissions table
    with get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
              id SERIAL PRIMARY KEY,
              artist_name VARCHAR(200) NOT NULL,
              venue VARCHAR(200) NOT NULL,
              event_date DATE NOT NULL,
              event_time TIME,
              description TEXT,
              submitter_name VARCHAR(100) NOT NULL,
              submitter_email VARCHAR(254) NOT NULL,
              status VARCHAR(20) DEFAULT 'pending',
              submitted_at TIMESTAMP DEFAULT NOW(),
              reviewed_at TIMESTAMP,
              reviewed_by VARCHAR(100),
              created_event_id VARCHAR(255),
              honeypot VARCHAR(255)
            );
            CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
            CREATE INDEX IF NOT EXISTS idx_submissions_date ON submissions(submitted_at DESC);
        """)

    # Step 5: Add is_wyxr_presents column
    with get_cursor() as cur:
        cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS is_wyxr_presents BOOLEAN DEFAULT false")

    # Step 6: Create dismissed_venue_names table (added with Dismiss button feature)
    with get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS dismissed_venue_names (
                name TEXT PRIMARY KEY,
                dismissed_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

    # Step 7: Create sponsors table
    with get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sponsors (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              name TEXT NOT NULL,
              image_url TEXT NOT NULL,
              link_url TEXT,
              display_after_date DATE NOT NULL,
              start_date DATE NOT NULL,
              end_date DATE NOT NULL,
              is_active BOOLEAN DEFAULT true,
              created_at TIMESTAMPTZ DEFAULT NOW(),
              updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_sponsors_dates ON sponsors (start_date, end_date)
              WHERE is_active = true;
        """)

    # Step 8: Seed venues if table is empty
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

    query += " ORDER BY date ASC, is_wyxr_presents DESC, is_featured DESC, start_time ASC"

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
        "genre", "source", "neighborhood", "is_featured", "is_wyxr_presents", "is_active",
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
        "genre", "source", "neighborhood", "is_featured", "is_wyxr_presents", "is_active",
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


def toggle_wyxr_presents(event_id, is_wyxr_presents):
    """Toggle WYXR Presents status."""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE events SET is_wyxr_presents = %s, updated_at = NOW() WHERE id = %s RETURNING *",
            (is_wyxr_presents, event_id),
        )
        return cur.fetchone()


def bulk_action(action, ids):
    """Bulk operations on events."""
    if not ids:
        return 0

    action_map = {
        "feature": "UPDATE events SET is_featured = true, updated_at = NOW()",
        "unfeature": "UPDATE events SET is_featured = false, updated_at = NOW()",
        "presents": "UPDATE events SET is_wyxr_presents = true, updated_at = NOW()",
        "unpresents": "UPDATE events SET is_wyxr_presents = false, updated_at = NOW()",
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


def is_fuzzy_duplicate(title, venue, date_str, threshold=0.8):
    """Return True if an event with similar title+venue already exists on this date.

    Uses SequenceMatcher similarity so OCR/handwriting variations don't create dupes.
    Both title and venue must meet the threshold (default 80%).
    """
    from difflib import SequenceMatcher

    def _norm(s):
        # Inline normalize: lowercase, strip punctuation, collapse whitespace
        import re
        s = s.lower().strip()
        s = re.sub(r'^the\s+', '', s)
        s = re.sub(r'[^\w\s]', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    def _sim(a, b):
        return SequenceMatcher(None, a, b).ratio()

    norm_title = _norm(title)
    norm_venue = _norm(venue)

    with get_cursor() as cur:
        cur.execute(
            "SELECT title, venue FROM events WHERE date = %s AND is_active = TRUE",
            (date_str,),
        )
        existing = cur.fetchall()

    return any(
        _sim(_norm(row["title"]), norm_title) >= threshold and
        _sim(_norm(row["venue"]), norm_venue) >= threshold
        for row in existing
    )


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
                "genre", "source", "neighborhood", "is_featured", "is_wyxr_presents", "is_active",
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
        ("Hernando's Hideaway", "Midtown", ["hernandos", "hernando's", "hernandos hideaway", "hernando's hideaway", "hernando's hide-a-way", "hernandos hide-a-way"]),
        ("Crosstown Arts", "Crosstown/Broad Avenue", ["crosstown arts", "the green room", "green room crosstown", "crosstown concourse"]),
        ("Lafayette's Music Room", "Overton Square/Cooper-Young", ["lafayettes", "lafayette's", "lafayettes music room", "lafayette's music room"]),
        ("Overton Park Shell", "Midtown", ["levitt shell", "overton park shell", "the shell"]),
        ("B.B. King's Blues Club", "Downtown/Beale Street", ["bb kings", "b.b. kings", "b.b. king's", "bb king's blues club"]),
        ("Graceland Soundstage", "South Memphis (Graceland/Stax)", ["graceland soundstage", "graceland live", "guest house theater"]),
        ("FedExForum", "Downtown/Beale Street", ["fedexforum", "fedex forum"]),
        ("Germantown Performing Arts Center", "Germantown", ["germantown performing arts", "germantown performing arts center", "gpac"]),
        ("Orpheum Theatre", "Downtown/Beale Street", ["orpheum", "orpheum theatre", "halloran centre", "halloran center"]),
        ("Bar DKDC", "Crosstown/Broad Avenue", ["bar dkdc", "dkdc"]),
        ("B-Side Memphis", "South Main Arts District", ["b-side", "bside", "b side", "b-side memphis"]),
        ("Nashoba", "Germantown", ["nashoba", "nashoba live", "nashoba memphis"]),
        ("Landers Center", "Germantown", ["landers center", "landers centre", "the landers center", "landers"]),
        ("South Main Sounds", "South Main Arts District", ["south main sounds", "south main sounds memphis"]),
    ]

    with get_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS count FROM venues")
        row = cur.fetchone()
        venue_count = row["count"] if row else 0

    if venue_count > 0:
        # Ensure new venues are added even if table already has data.
        # Skip if the venue already exists by name OR as an alias of another venue
        # (prevents re-creating venues that were merged away).
        for name, neighborhood, aliases in _SEED_VENUES:
            try:
                with get_cursor(commit=False) as cur:
                    cur.execute(
                        """SELECT 1 FROM venues
                           WHERE LOWER(name) = LOWER(%s)
                              OR LOWER(%s) = ANY(SELECT LOWER(unnest(aliases)))""",
                        (name, name),
                    )
                    if cur.fetchone():
                        continue  # Already exists by name or as alias — skip
                with get_cursor() as cur:
                    cur.execute(
                        """INSERT INTO venues (name, neighborhood, aliases)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (name) DO NOTHING""",
                        (name, neighborhood, aliases),
                    )
            except Exception:
                pass  # Skip individual venue errors
        return

    for name, neighborhood, aliases in _SEED_VENUES:
        with get_cursor() as cur:
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


def get_unmapped_venues():
    """Find venue names in events that don't match any venue in the venues table.

    Dismissed venue names are hidden unless a new event was imported after the dismissal date,
    in which case they re-appear automatically.
    """
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT e.venue AS name,
                   COUNT(*) AS event_count,
                   MAX(e.date) AS latest_date
            FROM events e
            WHERE e.venue IS NOT NULL
              AND e.venue != ''
              AND e.is_active = true
              AND NOT EXISTS (
                  SELECT 1 FROM venues v
                  WHERE LOWER(v.name) = LOWER(e.venue)
                     OR LOWER(e.venue) = ANY(SELECT LOWER(unnest(v.aliases)))
              )
            GROUP BY e.venue
            HAVING NOT EXISTS (
                SELECT 1 FROM dismissed_venue_names d
                WHERE LOWER(d.name) = LOWER(e.venue)
                  AND d.dismissed_at >= (
                      SELECT MAX(e2.created_at) FROM events e2
                      WHERE LOWER(e2.venue) = LOWER(e.venue) AND e2.is_active = true
                  )
            )
            ORDER BY COUNT(*) DESC, e.venue
        """)
        return cur.fetchall()


def dismiss_venue_name(name):
    """Mark an unmapped venue name as dismissed (not a real venue).

    The name will re-appear in unmapped venues if new events are imported after this dismissal.
    """
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO dismissed_venue_names (name, dismissed_at)
               VALUES (%s, NOW())
               ON CONFLICT (name) DO UPDATE SET dismissed_at = NOW()""",
            (name,),
        )


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
    """Get a dashboard summary with per-source details from recent builds."""
    import json as _json
    with get_cursor(commit=False) as cur:
        # Get recent build logs (last 10)
        cur.execute("""
            SELECT id, scraper_name, started_at, finished_at, status,
                   events_found, events_added, events_updated, events_skipped,
                   error_message, details
            FROM scrape_logs
            ORDER BY started_at DESC
            LIMIT 10
        """)
        recent_logs = cur.fetchall()

        # Total scraped events count
        cur.execute("SELECT COUNT(*) AS count FROM events WHERE source != 'manual' AND source != 'admin'")
        total_row = cur.fetchone()
        total_scraped = total_row["count"] if total_row else 0

        # Events by source
        cur.execute("""
            SELECT source, COUNT(*) AS count,
                   MIN(date) AS min_date, MAX(date) AS max_date
            FROM events
            WHERE date >= CURRENT_DATE
            GROUP BY source
            ORDER BY count DESC
        """)
        source_counts = cur.fetchall()

    # Extract per-source status from the latest build log's details
    per_source = {}
    for log in recent_logs:
        details = log.get("details")
        if not details:
            continue
        if isinstance(details, str):
            try:
                details = _json.loads(details)
            except Exception:
                continue
        sources_list = details.get("sources", [])
        for src in sources_list:
            name = src.get("name", "")
            if not name or name in per_source:
                continue
            per_source[name] = {
                "name": name,
                "success": src.get("success", False),
                "events": src.get("events", 0),
                "events_found": src.get("events_found", 0),
                "events_filtered": src.get("events_filtered", 0),
                "error": src.get("error"),
                "last_run": log["started_at"].isoformat() if log.get("started_at") else None,
                "build_status": log["status"],
            }

    # Build history: per-source results from last 5 builds
    source_history = {}
    for log in recent_logs[:5]:
        details = log.get("details")
        if not details:
            continue
        if isinstance(details, str):
            try:
                details = _json.loads(details)
            except Exception:
                continue
        for src in details.get("sources", []):
            name = src.get("name", "")
            if not name:
                continue
            if name not in source_history:
                source_history[name] = []
            source_history[name].append({
                "success": src.get("success", False),
                "events": src.get("events", 0),
                "events_found": src.get("events_found", 0),
                "error": src.get("error"),
                "run_time": log["started_at"].isoformat() if log.get("started_at") else None,
            })

    # Build overview
    builds = []
    for log in recent_logs:
        builds.append({
            "id": str(log["id"]),
            "started_at": log["started_at"].isoformat() if log.get("started_at") else None,
            "finished_at": log["finished_at"].isoformat() if log.get("finished_at") else None,
            "status": log["status"],
            "events_found": log.get("events_found", 0),
            "events_added": log.get("events_added", 0),
            "events_updated": log.get("events_updated", 0),
            "error_message": log.get("error_message"),
        })

    return {
        "sources": list(per_source.values()),
        "source_history": source_history,
        "builds": builds,
        "source_event_counts": [
            {
                "source": row["source"],
                "count": row["count"],
                "min_date": row["min_date"].isoformat() if row.get("min_date") else None,
                "max_date": row["max_date"].isoformat() if row.get("max_date") else None,
            }
            for row in source_counts
        ],
        "total_scraped_events": total_scraped,
        # Keep backward compat
        "scrapers": [
            {
                "name": s["name"],
                "last_run": s["last_run"],
                "last_status": "success" if s["success"] else "failed",
                "events_added_last_run": s["events"],
            }
            for s in per_source.values()
        ],
    }


# ---------------------------------------------------------------------------
# Submission queries
# ---------------------------------------------------------------------------

def create_submission(data):
    """Insert a new community event submission."""
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO submissions
               (artist_name, venue, event_date, event_time, description,
                submitter_name, submitter_email, honeypot)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING *""",
            (
                data["artist_name"],
                data["venue"],
                data["event_date"],
                data.get("event_time"),
                data.get("description"),
                data["submitter_name"],
                data["submitter_email"],
                data.get("honeypot"),
            ),
        )
        return cur.fetchone()


def get_submissions(status=None):
    """Get submissions, optionally filtered by status."""
    query = "SELECT * FROM submissions"
    params = []
    if status:
        query += " WHERE status = %s"
        params.append(status)
    query += " ORDER BY submitted_at DESC"
    with get_cursor(commit=False) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def get_submission_by_id(submission_id):
    """Get a single submission by ID."""
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM submissions WHERE id = %s", (submission_id,))
        return cur.fetchone()


def update_submission_status(submission_id, status, reviewed_by="admin", created_event_id=None):
    """Update a submission's status (pending -> approved/rejected)."""
    with get_cursor() as cur:
        cur.execute(
            """UPDATE submissions
               SET status = %s, reviewed_at = NOW(), reviewed_by = %s,
                   created_event_id = %s
               WHERE id = %s
               RETURNING *""",
            (status, reviewed_by, created_event_id, submission_id),
        )
        return cur.fetchone()


def delete_submission(submission_id):
    """Hard-delete a submission."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM submissions WHERE id = %s RETURNING *", (submission_id,))
        return cur.fetchone()


def get_pending_submission_count():
    """Get count of pending submissions."""
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS count FROM submissions WHERE status = 'pending'")
        row = cur.fetchone()
        return row["count"] if row else 0


# ---------------------------------------------------------------------------
# Sponsor queries
# ---------------------------------------------------------------------------

def get_active_sponsors(today=None):
    """Get active sponsors whose date range includes today (or the given date)."""
    if today is None:
        from datetime import date as _date
        today = _date.today()
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT * FROM sponsors
               WHERE is_active = true
                 AND start_date <= %s
                 AND end_date >= %s
               ORDER BY display_after_date, start_date""",
            (today, today),
        )
        return cur.fetchall()


def get_sponsors_for_rss(today=None, days=60):
    """Get active sponsors whose range overlaps the next N days."""
    from datetime import date as _date, timedelta
    if today is None:
        today = _date.today()
    end = today + timedelta(days=days)
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT * FROM sponsors
               WHERE is_active = true
                 AND start_date <= %s
                 AND end_date >= %s
               ORDER BY start_date""",
            (end, today),
        )
        return cur.fetchall()


def get_all_sponsors():
    """Get all sponsors for admin view, sorted by start_date desc."""
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM sponsors ORDER BY start_date DESC, created_at DESC")
        return cur.fetchall()


def get_sponsor_by_id(sponsor_id):
    """Get a single sponsor by ID."""
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM sponsors WHERE id = %s", (sponsor_id,))
        return cur.fetchone()


def create_sponsor(data):
    """Insert a new sponsor. Returns the created sponsor."""
    fields = ["name", "image_url", "link_url", "display_after_date", "start_date", "end_date", "is_active"]
    present = {k: data[k] for k in fields if k in data}
    columns = ", ".join(present.keys())
    placeholders = ", ".join(["%s"] * len(present))
    query = f"INSERT INTO sponsors ({columns}) VALUES ({placeholders}) RETURNING *"
    with get_cursor() as cur:
        cur.execute(query, list(present.values()))
        return cur.fetchone()


def update_sponsor(sponsor_id, data):
    """Update a sponsor. Returns updated sponsor."""
    allowed = ["name", "image_url", "link_url", "display_after_date", "start_date", "end_date", "is_active"]
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        return get_sponsor_by_id(sponsor_id)

    set_clauses = [f"{k} = %s" for k in updates]
    set_clauses.append("updated_at = NOW()")
    params = list(updates.values()) + [sponsor_id]

    query = f"UPDATE sponsors SET {', '.join(set_clauses)} WHERE id = %s RETURNING *"
    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def delete_sponsor(sponsor_id):
    """Hard-delete a sponsor."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM sponsors WHERE id = %s RETURNING *", (sponsor_id,))
        return cur.fetchone()
