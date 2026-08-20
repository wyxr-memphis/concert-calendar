#!/usr/bin/env python3
"""Memphis Concert Calendar — Main Runner

Fetches events from automated sources, merges them into PostgreSQL
(the single source of truth), and generates a static HTML page.

PostgreSQL is the primary data store — shared by the build and admin UI.
events.json is exported as a snapshot only.

Usage:
    python -m src.main              # Normal run
    python -m src.main --dry-run    # Print results without writing files
"""

import html
import json
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import Event, SourceResult, normalize_text, compute_dedup_key
from src.normalize import deduplicate
from src.generate_html import generate_html
from src.generate_rss import generate_rss
from src.generate_ics import generate_ics
from src.generate_sitemap import generate_sitemap, ROBOTS_TXT
from src.config import START_DATE, END_DATE, normalize_venue_name
from src.time_format import strftime_nopad
from src.sources.events_json import (
    EVENTS_JSON_PATH,
    load_events_json,
    save_events_json,
)

from src.sources import (
    ticketmaster,
    venue_scrapers,
    artifacts,
)

# Output paths
DOCS_DIR = Path(__file__).parent.parent / "docs"
INDEX_PATH = DOCS_DIR / "thisweek.html"
LOG_PATH = DOCS_DIR / "log.json"

# Syndication windows. RSS stays at 60 days (what readers expect to scroll);
# the iCalendar feed and sitemap cover the full scraper lookahead, because a
# subscribed calendar should show everything we know about.
RSS_WINDOW_DAYS = 60
FEED_WINDOW_DAYS = 180

# PostgreSQL connection
DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _db_available() -> bool:
    """Check if PostgreSQL database is configured and reachable."""
    if not DATABASE_URL:
        return False
    try:
        import psycopg2
        return True
    except ImportError:
        return False


def _create_scrape_log(scraper_name: str, started_at: datetime) -> Optional[str]:
    """Create a scrape_logs entry. Returns the log ID or None."""
    if not _db_available():
        return None
    conn = None
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "INSERT INTO scrape_logs (scraper_name, started_at, status) VALUES (%s, %s, 'running') RETURNING id",
            (scraper_name, started_at),
        )
        row = cur.fetchone()
        conn.commit()
        return str(row["id"]) if row else None
    except Exception as e:
        print(f"  [scrape_log] Could not create log entry: {e}")
        return None
    finally:
        if conn:
            conn.close()


def _update_scrape_log(log_id: Optional[str], data: dict) -> None:
    """Update a scrape_logs entry."""
    if not log_id or not _db_available():
        return
    conn = None
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        cur = conn.cursor()

        allowed = ["finished_at", "status", "events_found", "events_added",
                    "events_updated", "events_skipped", "error_message", "details"]
        updates = {k: data[k] for k in allowed if k in data}
        if not updates:
            return

        set_clauses = []
        params = []
        for k, v in updates.items():
            set_clauses.append(f"{k} = %s")
            if k == "details" and not isinstance(v, str):
                params.append(json.dumps(v))
            else:
                params.append(v)

        params.append(log_id)
        cur.execute(f"UPDATE scrape_logs SET {', '.join(set_clauses)} WHERE id = %s::uuid", params)
        conn.commit()
    except Exception as e:
        print(f"  [scrape_log] Could not update log entry: {e}")
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# PostgreSQL event I/O (single source of truth)
# ---------------------------------------------------------------------------

def _load_events_from_db() -> List[dict]:
    """Load all events from PostgreSQL into dict format for merging."""
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM events ORDER BY date, start_time")
    rows = cur.fetchall()
    conn.close()

    events = []
    for row in rows:
        events.append({
            "id": str(row["id"]),
            "title": row["title"] or "",
            "venue": row["venue"] or "",
            "date": str(row["date"]),
            "start_time": row["start_time"],
            "doors_time": row["doors_time"],
            "ticket_url": row["ticket_url"],
            "ticket_price": row["ticket_price"],
            "image_url": row["image_url"],
            "description": row["description"],
            "genre": row["genre"],
            "source": row["source"] or "unknown",
            "is_featured": row["is_featured"],
            "is_wyxr_presents": row.get("is_wyxr_presents", False),
            "is_active": row["is_active"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        })
    return events


def _load_venue_canonical_map() -> dict:
    """Return {lowercased name-or-alias: (canonical_name, neighborhood)} from the
    venues table.

    The DB venues table is the single source of truth for venue
    canonicalization. Applying it before the dedup key is computed keeps the
    key consistent with what actually gets stored — otherwise alias variants
    (e.g. "Soundstage at Graceland" -> "Graceland Soundstage") produce a key
    that never matches the stored row and duplicates accumulate every run.
    """
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT name, neighborhood, aliases FROM venues")
        lookup = {}
        for vrow in cur.fetchall():
            canonical = vrow["name"]
            hood = vrow.get("neighborhood")
            lookup[canonical.lower()] = (canonical, hood)
            for alias in (vrow.get("aliases") or []):
                lookup[alias.lower()] = (canonical, hood)
        return lookup
    finally:
        conn.close()


def _source_priority(source: str) -> int:
    """Return priority level for a source. Higher = more authoritative.

    Priority hierarchy:
      3 = manual (admin-created/edited, never overwritten)
      2 = scraper:{name} (automated scraper data)
      1 = artifact (image/flyer extraction via Claude Vision)
      0 = unknown
    """
    if not source:
        return 0
    if source == "manual":
        return 3
    if source.startswith("scraper:"):
        return 2
    if source == "artifact":
        return 1
    return 0


def _save_events_to_db(merged: List[dict], run_timestamp: datetime) -> dict:
    """Upsert merged events to PostgreSQL. Returns stats dict.

    Source priority hierarchy (highest to lowest):
      1. manual — never overwritten by scrapers or artifacts
      2. scraper:{name} — can overwrite artifacts, can update other scrapers
      3. artifact — lowest confidence, overwritten by scrapers or manual

    - Events with a UUID id (from DB) are updated in place
    - Events with an evt_ id (new from scrapers) are inserted
    - Past events are retained (not pruned) for historical record
    """
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Pre-load all venues into memory for O(1) lookups instead of per-event
        # queries. Built BEFORE db_key_to_row so the dedup key is always
        # computed from the canonical venue name (the one that gets stored).
        cur.execute("SELECT name, neighborhood, aliases FROM venues")
        venue_lookup = {}  # lowercase name/alias -> (canonical_name, neighborhood)
        for vrow in cur.fetchall():
            canonical = vrow["name"]
            hood = vrow.get("neighborhood")
            venue_lookup[canonical.lower()] = (canonical, hood)
            for alias in (vrow.get("aliases") or []):
                venue_lookup[alias.lower()] = (canonical, hood)

        def canon_venue(v: str) -> str:
            match = venue_lookup.get((v or "").lower())
            return match[0] if match else v

        # Build lookup of existing DB events by normalized key. Keyed on the
        # CANONICAL venue so legacy rows stored under a non-canonical name still
        # match incoming events.
        cur.execute("SELECT id, title, venue, date, source FROM events")
        db_key_to_row = {}
        for row in cur.fetchall():
            key = _normalized_key(row["title"] or "", canon_venue(row["venue"] or ""), str(row["date"]))
            db_key_to_row[key] = row

        added = 0
        updated = 0
        skipped = 0
        errors = 0
        timestamp = run_timestamp.isoformat()

        for entry in merged:
            title = (entry.get("title") or "").strip()
            venue = (entry.get("venue") or "").strip()
            date_str = (entry.get("date") or "").strip()
            if not title or not date_str:
                continue

            incoming_source = entry.get("source", "scraper:unknown")

            # Normalize venue name and get neighborhood from in-memory lookup
            neighborhood = entry.get("neighborhood")
            venue_match = venue_lookup.get(venue.lower())
            if venue_match:
                venue = venue_match[0]
                if not neighborhood:
                    neighborhood = venue_match[1]

            # Compute the dedup key AFTER canonicalizing the venue so it matches
            # the key the row will be stored under.
            key = _normalized_key(title, venue, date_str)

            # Each row is written inside its own SAVEPOINT. Without this, a single
            # failing row — e.g. a dedup_key unique-violation surfaced when a
            # concurrent build races the ON CONFLICT arbiter — poisons the whole
            # transaction, and the finally-block rollback then discards EVERY
            # row in the batch (observed: builds silently persisting nothing).
            # The savepoint scopes any failure to just that row so the rest of
            # the batch still commits.
            cur.execute("SAVEPOINT row_sp")
            try:
                if key in db_key_to_row:
                    db_row = db_key_to_row[key]
                    existing_priority = _source_priority(db_row.get("source", ""))
                    incoming_priority = _source_priority(incoming_source)

                    # Skip if existing source has higher priority
                    if existing_priority > incoming_priority:
                        cur.execute("RELEASE SAVEPOINT row_sp")
                        skipped += 1
                        continue
                    # Same priority (both scrapers) or incoming is higher — update.
                    # Refresh dedup_key in case title/venue changed (e.g. canonical
                    # venue rename) so it stays consistent with the unique index.
                    cur.execute(
                        """UPDATE events SET
                            title = COALESCE(%s, title),
                            venue = COALESCE(%s, venue),
                            start_time = COALESCE(%s, start_time),
                            ticket_url = COALESCE(%s, ticket_url),
                            image_url = COALESCE(image_url, %s),
                            source = COALESCE(%s, source),
                            neighborhood = COALESCE(neighborhood, %s),
                            dedup_key = %s,
                            updated_at = NOW()
                        WHERE id = %s""",
                        (
                            title,
                            venue,
                            entry.get("start_time"),
                            entry.get("ticket_url"),
                            entry.get("image_url"),
                            incoming_source,
                            neighborhood,
                            key,
                            db_row["id"],
                        ),
                    )
                    if cur.rowcount > 0:
                        updated += 1
                else:
                    # New event — insert. ON CONFLICT on the partial unique index is
                    # a structural backstop: even if db_key_to_row missed a row,
                    # the DB refuses to create a duplicate active event.
                    cur.execute(
                        """INSERT INTO events (title, venue, date, start_time, ticket_url,
                           image_url, source, neighborhood, is_featured, is_active, dedup_key)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (dedup_key) WHERE is_active DO NOTHING
                        RETURNING id""",
                        (
                            title, venue, date_str,
                            entry.get("start_time"),
                            entry.get("ticket_url"),
                            entry.get("image_url"),
                            incoming_source,
                            neighborhood,
                            entry.get("is_featured", False),
                            entry.get("is_active", True),
                            key,
                        ),
                    )
                    new_row = cur.fetchone()
                    if new_row:
                        # Add to lookup to prevent duplicates within this batch
                        db_key_to_row[key] = {
                            "id": new_row["id"],
                            "title": title,
                            "venue": venue,
                            "date": date_str,
                            "source": incoming_source,
                        }
                        added += 1
                    else:
                        # Conflict backstop fired — an active row already exists.
                        skipped += 1
                cur.execute("RELEASE SAVEPOINT row_sp")
            except Exception as e:
                # Roll this one row back and keep processing the rest of the batch.
                cur.execute("ROLLBACK TO SAVEPOINT row_sp")
                cur.execute("RELEASE SAVEPOINT row_sp")
                errors += 1
                if errors <= 10:
                    print(f"  [save] skipped 1 row ({incoming_source} | {title[:40]} | {date_str}): {str(e)[:120]}")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if errors:
        print(f"  [save] {errors} row(s) failed and were skipped (rest of batch preserved)")
    return {"added": added, "updated": updated, "skipped": skipped, "errors": errors, "pruned": 0}


def _load_active_events_from_db(start_date, end_date) -> List[dict]:
    """Load active events from PostgreSQL within date range."""
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """SELECT * FROM events
        WHERE is_active = true AND date >= %s AND date <= %s
        ORDER BY date, is_wyxr_presents DESC, is_featured DESC, start_time""",
        (str(start_date), str(end_date)),
    )
    rows = cur.fetchall()
    conn.close()

    events = []
    for row in rows:
        events.append({
            "id": str(row["id"]),
            "title": row["title"] or "",
            "venue": row["venue"] or "",
            "date": str(row["date"]),
            "start_time": row["start_time"],
            "ticket_url": row["ticket_url"],
            "source": row["source"] or "unknown",
            "is_featured": row["is_featured"],
            "is_wyxr_presents": row.get("is_wyxr_presents", False),
            "is_active": row["is_active"],
        })
    return events


def _load_sponsors_for_rss(days: int = 60) -> List[dict]:
    """Load active sponsors whose date range overlaps the next N days."""
    import psycopg2
    import psycopg2.extras
    from datetime import timedelta
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    today = date.today()
    end = today + timedelta(days=days)
    cur.execute(
        """SELECT * FROM sponsors
        WHERE is_active = true AND start_date <= %s AND end_date >= %s
        ORDER BY start_date""",
        (str(end), str(today)),
    )
    rows = cur.fetchall()
    conn.close()

    sponsors = []
    for row in rows:
        sponsors.append({
            "id": str(row["id"]),
            "name": row["name"] or "",
            "image_url": row["image_url"] or "",
            "link_url": row["link_url"],
            "display_after_date": str(row["display_after_date"]),
            "start_date": str(row["start_date"]),
            "end_date": str(row["end_date"]),
        })
    return sponsors


def _load_events_for_rss(days: int = 60) -> List[dict]:
    """Load active events for the next N days with all fields (for RSS feed)."""
    import psycopg2
    import psycopg2.extras
    from datetime import timedelta
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    today = date.today()
    end = today + timedelta(days=days)
    cur.execute(
        """SELECT * FROM events
        WHERE is_active = true AND date >= %s AND date <= %s
        ORDER BY date, is_wyxr_presents DESC, is_featured DESC, start_time""",
        (str(today), str(end)),
    )
    rows = cur.fetchall()
    conn.close()

    events = []
    for row in rows:
        events.append({
            "id": str(row["id"]),
            "title": row["title"] or "",
            "venue": row["venue"] or "",
            "date": str(row["date"]),
            "start_time": row["start_time"],
            "doors_time": row["doors_time"],
            "ticket_url": row["ticket_url"],
            "ticket_price": row["ticket_price"],
            "image_url": row["image_url"],
            "description": row["description"],
            "genre": row["genre"],
            "source": row["source"] or "unknown",
            "neighborhood": row.get("neighborhood"),
            "updated_at": row.get("updated_at"),
            "is_featured": row["is_featured"],
            "is_wyxr_presents": row.get("is_wyxr_presents", False),
        })
    return events


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> None:
    """Main execution: fetch → merge into PostgreSQL → generate HTML."""
    run_timestamp = datetime.now(ZoneInfo("UTC"))
    use_db = _db_available()

    print(f"\n{'='*60}")
    print(f"MEMPHIS CONCERT CALENDAR — {run_timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"Data store: {'PostgreSQL' if use_db else 'events.json (fallback)'}")
    print(f"{'='*60}\n")

    # Create scrape log entry.
    #
    # Skipped entirely on a dry run. This used to be created unconditionally,
    # but the dry-run path returns before the log is finalized, so every
    # --dry-run left a permanent status='running' row behind — which the nightly
    # health check reads as a build that hung.
    scrape_log_id = None
    if dry_run:
        print("  [scrape_log] Skipped (dry run)")
    else:
        scrape_log_id = _create_scrape_log("calendar-build", run_timestamp)
        if scrape_log_id:
            print(f"  [scrape_log] Created log entry: {scrape_log_id}")

    # Free image bytes held by submissions nobody ever reviewed. Submitted
    # flyers sit in Postgres until approved (so they never touch Cloudinary);
    # approve/reject clear their own, this catches the abandoned ones.
    if use_db and not dry_run:
        try:
            from backend.db import purge_stale_submission_images
            cleared = purge_stale_submission_images(older_than_days=90)
            if cleared:
                print(f"  [submissions] Cleared {cleared} stale submission image(s)")
        except Exception as exc:
            print(f"  [submissions] Image purge skipped: {exc}")

    # Log retention. Both tables only ever grew before this: the API request log
    # gets a row per v1 request, and the admin audit log a row per admin write.
    # The build is the only thing that runs on a schedule, so it is where the
    # sweep belongs.
    if use_db and not dry_run:
        try:
            from backend.db import purge_admin_audit_log, purge_api_request_logs
            audit_rows = purge_admin_audit_log(older_than_days=365)
            api_rows = purge_api_request_logs(older_than_days=90)
            if audit_rows or api_rows:
                print(f"  [retention] Purged {audit_rows} audit row(s), "
                      f"{api_rows} api request log row(s)")
        except Exception as exc:
            print(f"  [retention] Log purge skipped: {exc}")

    # ---- STEP 1: Fetch from automated sources ----
    all_source_results: List[SourceResult] = []
    automated_events: List[Event] = []

    sources = [
        ("Ticketmaster", ticketmaster.fetch),
        ("Artifacts", artifacts.fetch),
    ]

    for source_name, fetch_fn in sources:
        print(f"  Fetching: {source_name}...", end=" ", flush=True)
        try:
            result = fetch_fn()
            all_source_results.append(result)
            automated_events.extend(result.events)
            print(result.status_line)
        except Exception as e:
            error_result = SourceResult(
                source_name=source_name,
                success=False,
                error_message=f"Unhandled exception: {str(e)[:100]}",
            )
            all_source_results.append(error_result)
            print(error_result.status_line)

    # Venue scrapers — run individually for better logging
    print(f"\n  Fetching: Venue Websites...")
    try:
        venue_results = venue_scrapers.fetch_individual()
        for vr in venue_results:
            all_source_results.append(vr)
            automated_events.extend(vr.events)
            print(f"    {vr.status_line}")
    except Exception as e:
        error_result = SourceResult(
            source_name="Venue Websites",
            success=False,
            error_message=f"Unhandled exception: {str(e)[:100]}",
        )
        all_source_results.append(error_result)
        print(f"    {error_result.status_line}")

    # Clean HTML entities
    for event in automated_events:
        event.artist = html.unescape(event.artist)
        event.venue = html.unescape(event.venue)

    # Canonicalize venues against the DB venues table BEFORE dedup so the
    # canonical name flows consistently through deduplicate(), _merge_events(),
    # and _save_events_to_db(). Without this, alias/room variants (e.g.
    # "Soundstage at Graceland", Hi Tone "[Big Room-Upstairs]") get stored
    # canonicalized but keyed on the raw name, so they never dedupe.
    if use_db:
        try:
            canon_map = _load_venue_canonical_map()
            for event in automated_events:
                match = canon_map.get((event.venue or "").lower())
                if match:
                    event.venue = match[0]
        except Exception as e:
            print(f"  WARNING: Could not canonicalize venues from DB: {e}")

    # Deduplicate automated events among themselves
    print(f"\n  Raw automated events: {len(automated_events)}")
    automated_events = deduplicate(automated_events)
    print(f"  After dedup: {len(automated_events)}")

    # ---- STEP 2: Load existing events ----
    if use_db:
        try:
            existing_events = _load_events_from_db()
            print(f"  Existing events in PostgreSQL: {len(existing_events)}")
        except Exception as e:
            print(f"  WARNING: Could not load from DB: {e}")
            print(f"  Falling back to events.json")
            use_db = False

    if not use_db:
        try:
            events_data = load_events_json()
        except (FileNotFoundError, json.JSONDecodeError):
            events_data = {"version": 1, "updated_at": "", "events": []}
        existing_events = events_data.get("events", [])
        print(f"  Existing events in events.json: {len(existing_events)}")

    # ---- STEP 3: Merge automated events into existing ----
    merged = _merge_events(existing_events, automated_events, run_timestamp)
    print(f"  After merge: {len(merged)}")

    # ---- STEP 4: Save to data store ----
    db_stats = None
    if not dry_run:
        if use_db:
            try:
                db_stats = _save_events_to_db(merged, run_timestamp)
                print(f"  Saved to PostgreSQL: {db_stats['added']} added, {db_stats['updated']} updated, {db_stats.get('errors', 0)} failed, {db_stats['pruned']} pruned")
            except Exception as e:
                print(f"  WARNING: Could not save to DB: {e}")

        # Always export events.json as a snapshot
        snapshot = {"version": 1, "updated_at": run_timestamp.isoformat(), "events": merged}
        save_events_json(snapshot)
        print(f"  Exported {len(merged)} events to {EVENTS_JSON_PATH}")

    # ---- STEP 6: Generate HTML ----
    # If DB is available, read active events from it (includes admin edits);
    # otherwise use the merged in-memory list.
    if use_db and not dry_run:
        try:
            db_active = _load_active_events_from_db(START_DATE, END_DATE)
            active_events = []
            for entry in db_active:
                event = _entry_to_event(entry)
                if event:
                    active_events.append(event)
        except Exception as e:
            print(f"  WARNING: Could not read active events from DB: {e}")
            active_events = _filter_active(merged)
    else:
        active_events = _filter_active(merged)

    active_events.sort(key=lambda e: e.sort_key)

    # Add a "Database" source for reporting
    db_result = SourceResult(
        source_name="Database" if use_db else "Events JSON",
        events=active_events,
        events_found=len(active_events),
    )
    all_source_results.append(db_result)

    html_output = generate_html(active_events, all_source_results, run_timestamp)

    if dry_run:
        print(f"\n{'='*60}")
        print("DRY RUN — Not writing files")
        print(f"{'='*60}\n")
        _print_summary(active_events)
        return

    # ---- STEP 7: Write output files ----
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html_output)
    print(f"\n  Wrote {INDEX_PATH}")

    # Generate the syndication outputs: RSS (60 days), iCalendar subscribe feed
    # and sitemap (both the full FEED_WINDOW_DAYS lookahead).
    #
    # One DB read serves all three — the RSS window is a slice of the wider one.
    # Each writer gets its own try/except so a failure in one still leaves the
    # others published rather than silently skipping everything downstream.
    if use_db:
        feed_events = []
        try:
            feed_events = _load_events_for_rss(days=FEED_WINDOW_DAYS)
        except Exception as e:
            print(f"  WARNING: Could not load events for feeds: {e}")

        rss_cutoff = (date.today() + timedelta(days=RSS_WINDOW_DAYS)).isoformat()
        rss_events = [e for e in feed_events if str(e.get("date", "")) <= rss_cutoff]

        try:
            rss_sponsors = _load_sponsors_for_rss(days=RSS_WINDOW_DAYS)
            rss_output = generate_rss(rss_events, run_timestamp, sponsors=rss_sponsors)
            rss_path = DOCS_DIR / "feed.xml"
            with open(rss_path, "w", encoding="utf-8") as f:
                f.write(rss_output)
            print(f"  Wrote {rss_path} ({len(rss_events)} events, {len(rss_sponsors)} sponsors)")
        except Exception as e:
            print(f"  WARNING: Could not generate RSS feed: {e}")

        try:
            ics_output = generate_ics(feed_events, run_timestamp)
            ics_path = DOCS_DIR / "calendar.ics"
            # newline="" so the CRLF line endings RFC 5545 requires are written
            # verbatim instead of being translated by the platform.
            with open(ics_path, "w", encoding="utf-8", newline="") as f:
                f.write(ics_output)
            print(f"  Wrote {ics_path} ({len(feed_events)} events)")
        except Exception as e:
            print(f"  WARNING: Could not generate iCalendar feed: {e}")

        try:
            sitemap_output = generate_sitemap(feed_events, run_timestamp)
            sitemap_path = DOCS_DIR / "sitemap.xml"
            with open(sitemap_path, "w", encoding="utf-8") as f:
                f.write(sitemap_output)
            robots_path = DOCS_DIR / "robots.txt"
            with open(robots_path, "w", encoding="utf-8") as f:
                f.write(ROBOTS_TXT)
            print(f"  Wrote {sitemap_path} ({len(feed_events)} event URLs)")
        except Exception as e:
            print(f"  WARNING: Could not generate sitemap: {e}")

    # Write log
    log_data = {
        "run_timestamp": run_timestamp.isoformat(),
        "date_range": {"start": START_DATE.isoformat(), "end": END_DATE.isoformat()},
        "total_events_db": len(merged),
        "total_active_display": len(active_events),
        "data_store": "postgresql" if use_db else "events.json",
        "sources": [
            {
                "name": sr.source_name,
                "success": sr.success,
                "events_found": sr.events_found,
                "events_after_filter": len(sr.events),
                "events_filtered": sr.events_filtered,
                "error": sr.error_message,
            }
            for sr in all_source_results
        ],
        "events": [
            {
                "artist": e.artist,
                "venue": e.venue,
                "date": e.date.isoformat(),
                "time": e.time,
                "source": e.source,
            }
            for e in active_events
        ],
    }

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2)
    print(f"  Wrote {LOG_PATH}")

    # Write build timestamp
    build_time_path = DOCS_DIR / "build_time.txt"
    with open(build_time_path, "w", encoding="utf-8") as f:
        f.write(strftime_nopad(run_timestamp, "%B %-d, %Y at %-I:%M %p CT"))
    print(f"  Wrote {build_time_path}")

    _print_summary(active_events)

    # Check for failures
    failures = [sr for sr in all_source_results if not sr.success]
    if failures:
        print(f"\n  {len(failures)} source(s) had errors — check log.json for details")
        for f in failures:
            print(f"     - {f.source_name}: {f.error_message}")

    # ---- STEP 8: Update scrape log ----
    if scrape_log_id:
        total_found = sum(sr.events_found for sr in all_source_results)
        # Use actual DB stats if available, otherwise estimate from merge counts
        if db_stats:
            new_count = db_stats.get("added", 0)
            updated_count = db_stats.get("updated", 0)
        else:
            new_count = max(len(merged) - len(existing_events), 0)
            updated_count = 0

        status = "success"
        error_msg = None
        if failures:
            if len(failures) == len(all_source_results) - 1:
                status = "failed"
            else:
                status = "partial"
            error_msg = "; ".join(f"{f.source_name}: {f.error_message}" for f in failures)

        _update_scrape_log(scrape_log_id, {
            "finished_at": datetime.now(ZoneInfo("UTC")),
            "status": status,
            "events_found": total_found,
            "events_added": max(new_count, 0),
            "events_updated": updated_count,
            "events_skipped": total_found - len(automated_events),
            "error_message": error_msg,
            "details": {
                "sources": [
                    {
                        "name": sr.source_name,
                        "success": sr.success,
                        "events": len(sr.events),
                        "events_found": sr.events_found,
                        "events_filtered": sr.events_filtered,
                        # Unconditional, matching docs/log.json: a successful
                        # scraper that parsed nothing still carries the "page
                        # structure may have changed" hint, and dropping it left
                        # the health check with only a bare zero to go on.
                        "error": sr.error_message,
                    }
                    for sr in all_source_results
                ],
            },
        })
        print(f"  [scrape_log] Updated log entry: status={status}")


def _filter_active(merged: List[dict]) -> List[Event]:
    """Filter merged events to active ones in the date range."""
    active = []
    for entry in merged:
        if not entry.get("is_active", True):
            continue
        event = _entry_to_event(entry)
        if event and START_DATE <= event.date <= END_DATE:
            active.append(event)
    return active


def _merge_events(
    existing: List[dict],
    automated: List[Event],
    run_timestamp: datetime,
) -> List[dict]:
    """Merge automated events into the existing event entries.

    - Admin/manual entries are never touched
    - Matching automated events update time/url/source but preserve admin fields
    - New automated events are appended
    """
    timestamp = run_timestamp.isoformat()

    # Build lookup of existing entries by normalized key
    existing_by_key: Dict[str, int] = {}
    for i, entry in enumerate(existing):
        key = _normalized_key(entry.get("title", ""), entry.get("venue", ""), entry.get("date", ""))
        existing_by_key[key] = i

    merged = list(existing)  # Start with all existing entries

    for event in automated:
        key = _normalized_key(event.artist, event.venue, event.date.isoformat())

        if key in existing_by_key:
            idx = existing_by_key[key]
            entry = merged[idx]
            existing_priority = _source_priority(entry.get("source", ""))
            incoming_priority = _source_priority(event.source)
            # Skip if existing source has higher priority
            if existing_priority > incoming_priority:
                continue
            # Update automated fields, preserve admin-editable fields
            entry["title"] = event.artist  # Update title in case website updated it
            entry["start_time"] = event.time or entry.get("start_time")
            entry["ticket_url"] = event.url or entry.get("ticket_url")
            # Fill image only if we don't already have one — never clobber a
            # manual/prior image.
            if not entry.get("image_url") and event.image_url:
                entry["image_url"] = event.image_url
            if event.source:
                entry["source"] = event.source
            entry["updated_at"] = timestamp
        else:
            # New event — add it
            event_id = f"evt_{int(time.time() * 1000)}_{len(merged)}"
            new_entry = {
                "id": event_id,
                "title": event.artist,
                "venue": event.venue,
                "date": event.date.isoformat(),
                "start_time": event.time,
                "doors_time": None,
                "ticket_url": event.url,
                "ticket_price": None,
                "image_url": event.image_url,
                "description": None,
                "genre": None,
                "source": event.source,
                "is_featured": False,
                "is_active": True,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            merged.append(new_entry)
            existing_by_key[key] = len(merged) - 1
            time.sleep(0.001)  # Ensure unique IDs

    return merged


def _normalized_key(title: str, venue: str, date_str: str) -> str:
    """Compute a normalized key for matching: artist|venue|date.

    Thin wrapper over the shared compute_dedup_key (src/models.py) so the
    build, the backend API, and the persisted events.dedup_key column all
    use identical logic.
    """
    return compute_dedup_key(title, venue, date_str)


def _entry_to_event(entry: dict) -> Event | None:
    """Convert a dict entry to an Event dataclass."""
    try:
        event_date = date.fromisoformat(entry["date"])
    except (KeyError, ValueError):
        return None

    title = entry.get("title", "").strip()
    venue = entry.get("venue", "").strip()
    if not title or not venue:
        return None

    return Event(
        artist=title,
        venue=venue,
        date=event_date,
        time=entry.get("start_time"),
        source=entry.get("source", "unknown"),
        url=entry.get("ticket_url"),
        is_featured=entry.get("is_featured", False),
        event_id=entry.get("id"),
    )


def _print_summary(events: List[Event]) -> None:
    """Print a text summary of events."""
    by_date = defaultdict(list)
    for e in events:
        by_date[e.date].append(e)

    print(f"\n{'='*60}")
    print("EVENT SUMMARY")
    print(f"{'='*60}")

    for d in sorted(by_date.keys()):
        day_name = strftime_nopad(d, "%A, %B %-d").upper()
        print(f"\n  {d} — {day_name}")
        for e in by_date[d]:
            featured = " [FEATURED]" if e.is_featured else ""
            print(f"    {e.display_line}{featured}")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
