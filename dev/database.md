# Database, Dedup & Date Handling

> Tripwires live in `CLAUDE.md`. This file is the detail behind them.

## Data flow

- **PostgreSQL is the single source of truth** — never write directly to `events.json`
- `data/events.json` is a read-only snapshot exported by builds
- Admin edits go directly to PostgreSQL via the Render API
- Scrapers merge into PostgreSQL, then export the snapshot

## Connection

- Use the **external** PostgreSQL URL for local dev (the internal URL only works on Render)
- `DATABASE_URL` must be a single line — line breaks break the connection
- `gunicorn preload_app=True` is critical — with `False`, workers silently fail to import
  the app on Render
- Root `/` route is needed — Render health checks hit `/`, not `/health`
- **psycopg2 transaction poisoning:** a caught exception inside one `with get_cursor()` block
  leaves it `InFailedSqlTransaction`. Use a separate cursor block per operation.

## Schema DDL must never run unguarded on boot

`init_db()` checks the catalog first (`_schema_is_current()`) and skips migrations entirely
when every table and column already exists — the case on every deploy after the first.
Migrations that do run use `_ddl_cursor()`, which sets `lock_timeout = 5s`.

**Why:** `CREATE TABLE` / `ALTER TABLE` need an ACCESS EXCLUSIVE lock, and in Postgres a
*queued* exclusive request blocks every later query on that table — so a blocked boot takes
plain reads down with it. On 2026-07-29 a stalled build held a lock on `events` while a deploy
booted workers; their `CREATE TABLE IF NOT EXISTS events` queued, and the whole API went down
(`/api/events`, `/api/sponsors`, even `/health`) until the stuck session was terminated.

Any new DDL added to `_run_migrations()` must use `_ddl_cursor()` **and be registered for the
fast path, or it will be skipped forever**: new tables go in `_SCHEMA_TABLES`, new columns on
an existing table go in `_SCHEMA_COLUMNS[<table>]`. The column case is the sneaky one — the
table already exists, so the check passes and the column is silently never created on any
database that has run the app before.

**Diagnosing a hung API:** query `pg_stat_activity` for `state = 'idle in transaction'` and
`wait_event_type = 'Lock'`. Fix is `pg_terminate_backend(<pid>)` plus cancelling the build;
the build's inserts are `ON CONFLICT DO NOTHING` and re-run next cycle.

## Deduplication

Event identity is `dedup_key` = `normalize_text(title)|normalize_text(canonical_venue)|date`,
computed by the single shared `compute_dedup_key` (`src/models.py`). It is stored as a column
on `events` and enforced by the partial unique index `idx_events_dedup_key`
(`ON events (dedup_key) WHERE is_active`), so duplicate *active* events are structurally
impossible.

- `_save_events_to_db()` tracks inserted events within the same batch to prevent duplicates
- **Never overwrite admin/manual source entries** — automated scrapers always defer to manual edits

### Every dedup path must canonicalize the venue through the DB `venues` table

Not `config.normalize_venue_name` alone. Aliases added through Admin → Venues exist *only* in
that table, so the config function cannot see them and will score two rows for the same show
as different events.

The three call sites that must agree:

| Path | Resolves venue via |
|---|---|
| the build — `canon_venue()` in `src/main.py` | `venue_lookup`, built from `SELECT name, aliases FROM venues` |
| `scripts/backfill_dedup_key.py` | `_venue_canonical_map()`, same query |
| `scripts/cleanup_duplicates.py` | `build_venue_canon()`, same query |

**Why:** on 2026-08-20 `cleanup_duplicates.py` was the odd one out, using
`normalize_venue_name` only. The 2026-07-15 Lamplighter bill was stored twice — once as
`Lamplighter Lounge`, once as `Lamplighter Lounge, 1702 Madison Ave, Memphis TN`, an alias the
venues table knows and the config does not. The backfill reported **4** collisions while
cleanup found **2**, so cleanup could never clear the last two and the unique index could
never be created. The two scripts simply disagreed about what a duplicate was. Add
`venue_canon` to any new dedup path for the same reason.

### `dedup_key` goes stale whenever normalization changes

`src/models.normalize_text`, `config.normalize_venue_name`, and the `venues` aliases all feed
it — including a venue rename. Re-run the backfill after touching any of them.

The daily build partially self-heals: it rebuilds its lookup by *recomputing* every row's key
with current code and refreshes `dedup_key` on any row it matches, so a re-scraped event
repairs itself. Rows nothing re-scrapes stay stale until the backfill runs.

### Runbook: fix duplicates

Run in this order — cleanup **before** backfill, index last. Both scripts preview by default.

```bash
# 1. Preview what would be deleted (dry run)
python scripts/cleanup_duplicates.py

# 2. Actually delete the redundant rows
python scripts/cleanup_duplicates.py --confirm

# 3. Preview the key changes — writes nothing, and reports whether any
#    active group would MERGE or SPLIT (a merge means real duplicates surfaced)
python scripts/backfill_dedup_key.py --dry-run

# 4. Recompute and store dedup_key on every row
python scripts/backfill_dedup_key.py

# 5. Build the partial unique index — refuses while any collision remains
python scripts/backfill_dedup_key.py --create-index
```

- Step 4 reports any remaining **active collisions**; a non-zero count means step 2 missed
  them, which historically meant the two scripts disagreed about venue canonicalization.
- Before deleting, check that each doomed row holds no field its survivor lacks —
  `detail_score()` breaks ties arbitrarily when scores are equal.
- Re-run steps 3–5 after any change to `normalize_text`, `normalize_venue_name`, or venue
  aliases — including a venue rename, which leaves every one of that venue's keys stale.
- ⚠️ Never run a bulk DB edit while a build is in flight — check `gh run list` first.

## Date and time rules

- **A year-less date must go through `resolve_yearless_date`** (`src/date_utils.py`).
  Defaulting to the current year meant every December build read "Jan 15" as 11 months in the
  past and the `START_DATE` filter silently dropped it — affecting every venue scraper. A date
  more than 45 days before the reference rolls forward, so a slightly stale listing stays put
  but a New Year date moves. `backend/app.py`'s `_normalize_date_iso` shares the same helper.
- **`%-d` / `%-I` are glibc-only** and break local dev on macOS/Windows. Use `strftime_nopad`,
  and `format_event_time` for the "7:30 PM" rendering (previously duplicated at 11 sites).
- **A time shown to a human is am/pm, never a 24-hour clock.** The public submit form's
  `<input type="time">` posts `19:30` and psycopg2 hands back a `datetime.time`;
  `format_time_of_day` renders either as `7:30 PM`. It is *not* `parse_start_time` — that one
  reads a bare `7:30` as the evening, correct for a scraped flyer and wrong for a form field
  where `07:30` is the morning. Used by the Slack submission notification, the event created
  on approve, and (as `formatTime`) the admin Edit & Approve link.
- **`start_time` is parsed in exactly one place: `time_format.parse_start_time`.** The ICS
  feed, the `/e/<id>` page and `thisweek.html` all call it, and `_parseEventStartTime` in
  `docs/index.html` mirrors it. `DEFAULT_START_HOUR` (20) and `DEFAULT_DURATION_HOURS` (3)
  live there too. **Why:** three surfaces publish machine-readable start times for the same
  show — an iCalendar `DTSTART`, a schema.org `startDate`, and the modal's calendar buttons.
  If they disagree, a subscriber and a search result show different times for the same gig,
  and nothing surfaces the contradiction.

## Transient Postgres connection timeouts

Anything reaching the Render database **over the internet** — the local backend (`.env` holds
the external `DATABASE_URL`) and the GitHub Actions build — hits occasional
`psycopg2.OperationalError: ... timeout expired`. It is latency, not a defect.

- Locally it surfaces as a **500 on whatever admin endpoint happened to fire**; the same
  request succeeds on retry.
- In CI the build logs `[scrape_log] Could not create log entry: ... timeout expired` and
  continues correctly — so **a build with no `scrape_logs` row is not a failed build**.
  Confirm against the run's own log (`Saved to PostgreSQL: N added, …`) before investigating.

Retry 2–3 times and grep for `OperationalError` before chasing it as a bug.

## Other debugging

**Backend won't start**
- Check `DATABASE_URL` format (single line, no breaks)
- Verify port 5001 isn't in use: `lsof -i :5001`
- Test the connection: `python -c "from backend.db import init_db; init_db()"`

**Frontend can't connect**
- Check CORS in `backend/app.py` — should include `localhost:8000`
- Open the browser console (Cmd+Option+I) for CORS errors

**Duplicates appearing**
- Check `_save_events_to_db()` updates `db_key_to_row` after inserts
- Run `python scripts/cleanup_duplicates.py`

**Scraper failing**
- Check scraper logs in the admin UI (Tools tab)
- Test one: `python -c "from src.sources import ticketmaster; print(ticketmaster.fetch())"`
