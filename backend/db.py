"""Database connection and query helpers for PostgreSQL on Render."""

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Register UUID adapter
psycopg2.extras.register_uuid()

# Connection pool — initialized lazily on first use
_pool = None


def _get_pool():
    """Get or create the connection pool."""
    global _pool
    if _pool is None or _pool.closed:
        _pool = ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=DATABASE_URL,
            connect_timeout=5,
        )
    return _pool


def get_connection():
    """Get a connection from the pool."""
    return _get_pool().getconn()


def _put_connection(conn):
    """Return a connection to the pool."""
    try:
        _get_pool().putconn(conn)
    except Exception:
        # Pool closed or connection bad — just close it
        try:
            conn.close()
        except Exception:
            pass


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
        _put_connection(conn)


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

    # Step 2b: dedup_key column + partial unique index (structural guard against
    # duplicate active events). Index creation is wrapped so an existing
    # duplicate collision can't crash boot — the one-time
    # scripts/backfill_dedup_key.py cleans + backfills + creates the index on
    # prod; this is just insurance for fresh installs.
    with get_cursor() as cur:
        cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS dedup_key TEXT")
    try:
        with get_cursor() as cur:
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedup_key "
                "ON events (dedup_key) WHERE is_active"
            )
    except Exception as e:
        print(f"[init_db] Skipped dedup_key unique index (resolve duplicates first): {e}")

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

    # Step 8: Create calendar_sponsor table
    with get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS calendar_sponsor (
              id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              name        TEXT NOT NULL,
              image_url   TEXT NOT NULL,
              link_url    TEXT,
              copy_line   TEXT,
              start_date  DATE NOT NULL,
              end_date    DATE NOT NULL,
              is_active   BOOLEAN DEFAULT true,
              created_at  TIMESTAMPTZ DEFAULT NOW(),
              updated_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_cal_sponsor_dates
              ON calendar_sponsor (start_date, end_date) WHERE is_active = true;
        """)

    # Step 9: Create api_keys table
    with get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
              id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              key         TEXT UNIQUE NOT NULL,
              name        TEXT NOT NULL,
              email       TEXT,
              notes       TEXT,
              is_active   BOOLEAN DEFAULT TRUE,
              created_at  TIMESTAMPTZ DEFAULT NOW(),
              last_used_at TIMESTAMPTZ
            )
        """)

    # Step 10: Create api_request_logs table
    with get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_request_logs (
              id          BIGSERIAL PRIMARY KEY,
              api_key_id  UUID REFERENCES api_keys(id),
              key_prefix  TEXT,
              endpoint    TEXT,
              query_params TEXT,
              ip          TEXT,
              status_code INTEGER,
              duration_ms INTEGER,
              created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_request_logs_key ON api_request_logs(api_key_id);
            CREATE INDEX IF NOT EXISTS idx_request_logs_created ON api_request_logs(created_at);
        """)

    # Step 12: Create api_key_requests table (public access requests, pending admin approval)
    with get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_key_requests (
              id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              name         TEXT NOT NULL,
              email        TEXT NOT NULL,
              company      TEXT,
              use_case     TEXT,
              status       TEXT DEFAULT 'pending',
              submitted_at TIMESTAMPTZ DEFAULT NOW(),
              reviewed_at  TIMESTAMPTZ,
              api_key_id   UUID REFERENCES api_keys(id)
            );
            CREATE INDEX IF NOT EXISTS idx_api_key_requests_status ON api_key_requests(status);
        """)

    # Step 13: Backfill source column to standardized values
    # manual, scraper:{name}, artifact — idempotent migration
    with get_cursor() as cur:
        # Admin/manual sources stay as "manual"
        cur.execute("""UPDATE events SET source = 'manual'
                       WHERE source = 'admin'""")
        # Submission-created events are manual
        cur.execute("""UPDATE events SET source = 'manual'
                       WHERE source = 'submission'""")
        # Ticketmaster
        cur.execute("""UPDATE events SET source = 'scraper:ticketmaster'
                       WHERE source = 'Ticketmaster'""")
        # Venue scrapers: "Venue: Hi Tone" -> "scraper:hi_tone"
        cur.execute("""UPDATE events SET source = 'scraper:' || TRIM(BOTH '_' FROM
                         LOWER(REGEXP_REPLACE(
                           REGEXP_REPLACE(source, '^Venue: ', ''),
                           '[^a-z0-9]+', '_', 'gi')))
                       WHERE source LIKE 'Venue: %'""")
        # Artifacts
        cur.execute("""UPDATE events SET source = 'artifact'
                       WHERE source LIKE 'Artifacts (%' OR source LIKE 'Slack Image%'""")
        # Imports (HTML file imports) -> treat as artifact
        cur.execute("""UPDATE events SET source = 'artifact'
                       WHERE source LIKE 'import (%' OR source = 'import'""")
        # Catch-all: anything that doesn't match known patterns -> scraper:unknown
        cur.execute("""UPDATE events SET source = 'scraper:unknown'
                       WHERE source NOT IN ('manual', 'artifact')
                         AND source NOT LIKE 'scraper:%'""")

    # Step 11: Seed venues if table is empty
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


def _event_dedup_key(title, venue, date_str):
    """Canonical dedup key for an event, canonicalizing the venue via the DB
    venues table first.

    Mirrors the build's key (src/main.py) so the persisted events.dedup_key
    column stays consistent across the API and the daily build.
    """
    from src.models import compute_dedup_key
    canon = normalize_venue_from_db(venue)
    canonical_venue = canon[0] if canon else venue
    return compute_dedup_key(title or "", canonical_venue or "", str(date_str or ""))


def create_event(data):
    """Insert a new event. Returns the created event.

    Sets dedup_key and relies on the partial unique index as a backstop. If an
    active event with the same key already exists, returns that existing row
    instead of creating a duplicate.
    """
    fields = [
        "title", "venue", "date", "start_time", "doors_time",
        "ticket_url", "ticket_price", "image_url", "description",
        "genre", "source", "neighborhood", "is_featured", "is_wyxr_presents", "is_active",
    ]
    present = {k: data[k] for k in fields if k in data}
    present["dedup_key"] = _event_dedup_key(
        data.get("title"), data.get("venue"), data.get("date")
    )
    columns = ", ".join(present.keys())
    placeholders = ", ".join(["%s"] * len(present))

    query = f"""
        INSERT INTO events ({columns})
        VALUES ({placeholders})
        ON CONFLICT (dedup_key) WHERE is_active DO NOTHING
        RETURNING *
    """
    with get_cursor() as cur:
        cur.execute(query, list(present.values()))
        row = cur.fetchone()
        if row:
            return row
        # Conflict backstop fired — return the existing active row.
        cur.execute(
            "SELECT * FROM events WHERE dedup_key = %s AND is_active = TRUE LIMIT 1",
            (present["dedup_key"],),
        )
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

    # If any identity field changed, recompute dedup_key so it stays consistent
    # with the unique index.
    if any(k in updates for k in ("title", "venue", "date")):
        current = get_event_by_id(event_id)
        if current:
            updates["dedup_key"] = _event_dedup_key(
                updates.get("title", current["title"]),
                updates.get("venue", current["venue"]),
                updates.get("date", current["date"]),
            )

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
            present["dedup_key"] = _event_dedup_key(
                data.get("title"), data.get("venue"), data.get("date")
            )
            columns = ", ".join(present.keys())
            placeholders = ", ".join(["%s"] * len(present))
            query = (
                f"INSERT INTO events ({columns}) VALUES ({placeholders}) "
                "ON CONFLICT (dedup_key) WHERE is_active DO NOTHING RETURNING *"
            )
            cur.execute(query, list(present.values()))
            row = cur.fetchone()
            if row:
                results.append(row)

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
        ("Satellite Music Hall", "Midtown", ["satellite music hall", "satellite music hall memphis"]),
        ("Radians Amphitheater", "East Memphis", ["radians amphitheater", "radians amphitheatre", "live at the garden", "memphis botanic garden"]),
        ("Cannon Center for the Performing Arts", "Downtown/Beale Street", ["cannon center", "cannon center for the performing arts", "cannon center for performing arts"]),
        ("Grind City Amphitheater", None, ["grind city amphitheater", "grind city amphitheatre", "grind city"]),
        ("Horseshoe Casino's Bluesville", "North Mississippi", ["horseshoe casino's bluesville", "horseshoe casino bluesville", "bluesville", "horseshoe bluesville"]),
        ("BankPlus Amphitheater at Snowden Grove", "North Mississippi", ["bankplus amphitheater at snowden grove", "bankplus amphitheater", "bankplus amphitheatre", "snowden grove amphitheater", "snowden grove"]),
        ("Germantown Performing Arts Center", "Germantown", ["germantown performing arts", "germantown performing arts center", "gpac"]),
        ("Orpheum Theatre", "Downtown/Beale Street", ["orpheum", "orpheum theatre", "halloran centre", "halloran center"]),
        ("Bar DKDC", "Crosstown/Broad Avenue", ["bar dkdc", "dkdc"]),
        ("B-Side Memphis", "South Main Arts District", ["b-side", "bside", "b side", "b-side memphis"]),
        ("Nashoba", "Germantown", ["nashoba", "nashoba live", "nashoba memphis"]),
        ("Landers Center", "Germantown", ["landers center", "landers centre", "the landers center", "landers"]),
        ("South Main Sounds", "South Main Arts District", ["south main sounds", "south main sounds memphis"]),
        ("Flyway Brewing", None, ["flyway brewing", "flyway brewing memphis", "flyway"]),
        ("Huey's", None, ["hueys", "huey's", "huey's burgers"]),
        ("Crosstown Brewing Co.", "Crosstown/Broad Avenue", ["crosstown beer", "crosstown brewing", "crosstown brewing co", "crosstown brewing co."]),
        ("Blues City Cafe", "Downtown/Beale Street", ["blues city cafe", "blues city café", "blues city cafe band box"]),
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

    Uses CTEs to pre-compute known names and dismissed names for efficient filtering.
    """
    with get_cursor(commit=False) as cur:
        cur.execute("""
            WITH known_names AS (
                SELECT LOWER(name) AS lname FROM venues
                UNION
                SELECT LOWER(unnest(aliases)) FROM venues
            ),
            dismissed AS (
                SELECT LOWER(name) AS lname, dismissed_at
                FROM dismissed_venue_names
            )
            SELECT e.venue AS name,
                   COUNT(*) AS event_count,
                   MAX(e.date) AS latest_date
            FROM events e
            WHERE e.venue IS NOT NULL
              AND e.venue != ''
              AND e.is_active = true
              AND LOWER(e.venue) NOT IN (SELECT lname FROM known_names)
            GROUP BY e.venue
            HAVING NOT EXISTS (
                SELECT 1 FROM dismissed d
                WHERE d.lname = LOWER(e.venue)
                  AND d.dismissed_at >= MAX(e.created_at)
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


# ---------------------------------------------------------------------------
# Calendar sponsor queries
# ---------------------------------------------------------------------------

def get_active_calendar_sponsor(today=None):
    """Get the single active calendar sponsor for today, or None."""
    if today is None:
        from datetime import date as _date
        today = _date.today()
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT * FROM calendar_sponsor
               WHERE is_active = true
                 AND start_date <= %s
                 AND end_date >= %s
               ORDER BY start_date DESC
               LIMIT 1""",
            (today, today),
        )
        return cur.fetchone()


def get_all_calendar_sponsors():
    """Get all calendar sponsors for admin view."""
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM calendar_sponsor ORDER BY start_date DESC, created_at DESC")
        return cur.fetchall()


def get_calendar_sponsor_by_id(sponsor_id):
    """Get a single calendar sponsor by ID."""
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM calendar_sponsor WHERE id = %s", (sponsor_id,))
        return cur.fetchone()


def create_calendar_sponsor(data):
    """Insert a new calendar sponsor. Returns the created row."""
    fields = ["name", "image_url", "link_url", "copy_line", "start_date", "end_date", "is_active"]
    present = {k: data[k] for k in fields if k in data}
    columns = ", ".join(present.keys())
    placeholders = ", ".join(["%s"] * len(present))
    query = f"INSERT INTO calendar_sponsor ({columns}) VALUES ({placeholders}) RETURNING *"
    with get_cursor() as cur:
        cur.execute(query, list(present.values()))
        return cur.fetchone()


def update_calendar_sponsor(sponsor_id, data):
    """Update a calendar sponsor. Returns the updated row."""
    allowed = ["name", "image_url", "link_url", "copy_line", "start_date", "end_date", "is_active"]
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        return get_calendar_sponsor_by_id(sponsor_id)

    set_clauses = [f"{k} = %s" for k in updates]
    set_clauses.append("updated_at = NOW()")
    params = list(updates.values()) + [sponsor_id]

    query = f"UPDATE calendar_sponsor SET {', '.join(set_clauses)} WHERE id = %s RETURNING *"
    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def delete_calendar_sponsor(sponsor_id):
    """Hard-delete a calendar sponsor."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM calendar_sponsor WHERE id = %s RETURNING *", (sponsor_id,))
        return cur.fetchone()


# ---------------------------------------------------------------------------
# API Key queries
# ---------------------------------------------------------------------------

def get_api_key(key: str):
    """Look up an API key by its key string. Returns row or None."""
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM api_keys WHERE key = %s", (key,))
        return cur.fetchone()


def create_api_key(name, email=None, notes=None) -> dict:
    """Generate a new API key and insert it. Returns the created row."""
    import secrets as _secrets
    key = "wyxr_" + _secrets.token_urlsafe(32)
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO api_keys (key, name, email, notes)
               VALUES (%s, %s, %s, %s) RETURNING *""",
            (key, name, email, notes),
        )
        return cur.fetchone()


def list_api_keys() -> list:
    """Get all API keys ordered by creation date."""
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM api_keys ORDER BY created_at DESC")
        return cur.fetchall()


def update_api_key(key_id, **fields) -> dict:
    """Update name/email/notes/is_active on an API key."""
    allowed = ["name", "email", "notes", "is_active"]
    updates = {k: fields[k] for k in allowed if k in fields}
    if not updates:
        with get_cursor(commit=False) as cur:
            cur.execute("SELECT * FROM api_keys WHERE id = %s", (key_id,))
            return cur.fetchone()
    set_clauses = [f"{k} = %s" for k in updates]
    params = list(updates.values()) + [key_id]
    query = f"UPDATE api_keys SET {', '.join(set_clauses)} WHERE id = %s RETURNING *"
    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def log_api_request(key_id, key_prefix, endpoint, query_params, ip, status_code, duration_ms):
    """Insert a request log entry and update last_used_at. Fails silently."""
    try:
        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO api_request_logs
                   (api_key_id, key_prefix, endpoint, query_params, ip, status_code, duration_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (key_id, key_prefix, endpoint, query_params, ip, status_code, duration_ms),
            )
        if key_id:
            with get_cursor() as cur:
                cur.execute(
                    "UPDATE api_keys SET last_used_at = NOW() WHERE id = %s",
                    (key_id,),
                )
    except Exception as e:
        print(f"[api_log] Error logging request: {e}", flush=True)


def get_api_key_usage(key_id, days=30) -> list:
    """Daily request counts for a key over the last N days."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT DATE(created_at) AS day, COUNT(*) AS requests
               FROM api_request_logs
               WHERE api_key_id = %s
                 AND created_at >= NOW() - (%s * INTERVAL '1 day')
               GROUP BY DATE(created_at)
               ORDER BY day""",
            (key_id, days),
        )
        return cur.fetchall()


def create_api_key_request(name, email, company=None, use_case=None) -> dict:
    """Insert a new API key request (pending approval)."""
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO api_key_requests (name, email, company, use_case)
               VALUES (%s, %s, %s, %s) RETURNING *""",
            (name, email, company, use_case),
        )
        return cur.fetchone()


def list_api_key_requests(status=None) -> list:
    """Get API key requests, optionally filtered by status."""
    query = "SELECT * FROM api_key_requests"
    params = []
    if status:
        query += " WHERE status = %s"
        params.append(status)
    query += " ORDER BY submitted_at DESC"
    with get_cursor(commit=False) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def update_api_key_request(request_id, status, api_key_id=None) -> dict:
    """Update a request's status (approved/rejected) and optionally link an api_key."""
    with get_cursor() as cur:
        cur.execute(
            """UPDATE api_key_requests
               SET status = %s, reviewed_at = NOW(), api_key_id = %s
               WHERE id = %s RETURNING *""",
            (status, api_key_id, request_id),
        )
        return cur.fetchone()


def get_v1_events(start_date=None, end_date=None, featured_only=False,
                   neighborhood=None, venue=None, limit=100):
    """Get active events for the v1 public API with extended filters."""
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
    if neighborhood:
        query += " AND neighborhood = %s"
        params.append(neighborhood)
    if venue:
        query += " AND LOWER(venue) = LOWER(%s)"
        params.append(venue)

    query += " ORDER BY date ASC, is_wyxr_presents DESC, is_featured DESC, start_time ASC"

    limit = min(int(limit), 500)
    query += " LIMIT %s"
    params.append(limit)

    with get_cursor(commit=False) as cur:
        cur.execute(query, params)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Health-check aggregations
# ---------------------------------------------------------------------------

def health_events_14d():
    """Aggregate events for the 14-day window starting at today (America/Chicago).

    Shape matches the /api/admin/health-check events_14d block.
    """
    from datetime import datetime as _dt, timedelta as _td
    from zoneinfo import ZoneInfo as _ZI

    today = _dt.now(_ZI("America/Chicago")).date()
    end = today + _td(days=14)  # exclusive

    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT date, source, ticket_url, start_time, venue
               FROM events
               WHERE is_active = true
                 AND date >= %s
                 AND date < %s""",
            (today, end),
        )
        rows = cur.fetchall()

    # by_day — always 14 entries, zero-filled
    day_counts = {}
    for row in rows:
        d = row["date"]
        day_counts[d] = day_counts.get(d, 0) + 1
    by_day = [
        {"date": (today + _td(days=i)).isoformat(), "count": day_counts.get(today + _td(days=i), 0)}
        for i in range(14)
    ]

    def _is_empty(v):
        return v is None or (isinstance(v, str) and v.strip() == "")

    missing_ticket_url = 0
    missing_start_time = 0
    missing_venue = 0
    incomplete_total = 0
    by_source = {}  # source -> {"incomplete_count", "total_count"}

    for row in rows:
        src = row["source"] if row["source"] else "unknown"
        bucket = by_source.setdefault(src, {"incomplete_count": 0, "total_count": 0})
        bucket["total_count"] += 1

        row_incomplete = False
        if _is_empty(row["ticket_url"]):
            missing_ticket_url += 1
            row_incomplete = True
        if _is_empty(row["start_time"]):
            missing_start_time += 1
            row_incomplete = True
        if _is_empty(row["venue"]):
            missing_venue += 1
            row_incomplete = True

        if row_incomplete:
            incomplete_total += 1
            bucket["incomplete_count"] += 1

    by_source_list = sorted(
        ({"source": s, **counts} for s, counts in by_source.items()),
        key=lambda x: (-x["incomplete_count"], -x["total_count"], x["source"]),
    )

    return {
        "total": len(rows),
        "by_day": by_day,
        "incomplete": {
            "total": incomplete_total,
            "missing_ticket_url": missing_ticket_url,
            "missing_start_time": missing_start_time,
            "missing_venue": missing_venue,
            "by_source": by_source_list,
        },
    }


def health_recent_build_logs(limit=30):
    """Recent 'calendar-build' scrape_logs rows, newest first.

    Caller parses the details JSONB to extract per-source run history —
    scrape_logs stores one row per entire build, not one per source.
    """
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT started_at, finished_at, status, details
               FROM scrape_logs
               WHERE scraper_name = 'calendar-build'
               ORDER BY started_at DESC
               LIMIT %s""",
            (limit,),
        )
        return cur.fetchall()


def health_submissions():
    """Pending community submission stats.

    Returns: pending_count, oldest_pending_at, oldest_pending_age_hours.
    submitted_at is TIMESTAMP (no tz), so we let Postgres do the math.
    """
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT COUNT(*) AS pending_count,
                      MIN(submitted_at) AS oldest_pending_at,
                      ROUND((EXTRACT(EPOCH FROM (NOW() - MIN(submitted_at))) / 3600.0)::numeric, 1)
                        AS oldest_pending_age_hours
               FROM submissions
               WHERE status = 'pending'"""
        )
        row = cur.fetchone() or {}

    oldest = row.get("oldest_pending_at")
    age = row.get("oldest_pending_age_hours")
    return {
        "pending_count": row.get("pending_count") or 0,
        "oldest_pending_at": oldest.isoformat() + "Z" if oldest else None,
        "oldest_pending_age_hours": float(age) if age is not None else None,
    }


def health_ticketmaster():
    """Ticketmaster error + last-success summary from scrape_logs.details.

    Walks details.sources[] entries with name='scraper:ticketmaster'
    (the value emitted by src/sources/ticketmaster.py on success) since
    per-source status lives in JSONB, not in the top-level row.
    """
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT COUNT(*) AS errors_24h
               FROM scrape_logs sl,
                    LATERAL jsonb_array_elements(
                        COALESCE(sl.details -> 'sources', '[]'::jsonb)
                    ) AS src
               WHERE sl.scraper_name = 'calendar-build'
                 AND sl.started_at >= NOW() - INTERVAL '24 hours'
                 AND src ->> 'name' = 'scraper:ticketmaster'
                 AND COALESCE((src ->> 'success')::boolean, false) = false"""
        )
        errors_row = cur.fetchone() or {}

    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT MAX(sl.started_at) AS last_success
               FROM scrape_logs sl,
                    LATERAL jsonb_array_elements(
                        COALESCE(sl.details -> 'sources', '[]'::jsonb)
                    ) AS src
               WHERE sl.scraper_name = 'calendar-build'
                 AND src ->> 'name' = 'scraper:ticketmaster'
                 AND (src ->> 'success')::boolean = true"""
        )
        success_row = cur.fetchone() or {}

    last_success = success_row.get("last_success")
    return {
        "errors_24h": errors_row.get("errors_24h") or 0,
        "last_successful_run_at": (
            last_success.isoformat(timespec="seconds").replace("+00:00", "Z")
            if last_success else None
        ),
    }
