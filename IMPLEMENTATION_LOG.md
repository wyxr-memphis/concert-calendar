# Implementation Log

## Overview

The concert calendar started as a Python script that wrote events to a flat `events.json` file. It evolved through several phases to its current architecture where PostgreSQL is the single source of truth, with an interactive calendar homepage and comprehensive admin UI.

## Current Architecture

- **PostgreSQL on Render** = single source of truth for all events (manual + automated), venues, and scrape_logs
- **Backend API** = Flask on Render serving REST endpoints at `/api/*`, gunicorn with `preload_app=True`
- **Interactive calendar** = `docs/index.html` — client-side filtering (neighborhoods, search, month nav) over 6-month API data
- **Static "This Week" page** = `docs/thisweek.html` — auto-generated 8-day view
- **Admin UI** = vanilla HTML+JS on Vercel with tabs: Events (with Import), Tools/Scrapers, Venues
- **Auth** = JWT via Bearer token (cross-origin sessionStorage)
- **Daily build** = GitHub Actions 2x daily -> fetch scrapers -> merge into PostgreSQL -> export events.json snapshot -> generate HTML
- **Scraper logging** = `src/main.py` writes to `scrape_logs` table via `DATABASE_URL`
- **`data/events.json`** = read-only snapshot exported by the build (not an input)

## Database Tables

| Table | Purpose |
|-------|---------|
| `events` | All events with `neighborhood` column, indexed |
| `venues` | Canonical venue names, neighborhoods, aliases for auto-normalization |
| `scrape_logs` | Per-build scraper results with per-source details |

## Environment Variables

### Vercel (Frontend)
| Variable | Purpose |
|----------|---------|
| `ADMIN_PASSWORD` | Login password |
| `ADMIN_SECRET_KEY` | JWT signing key |
| `GITHUB_PAT` | GitHub Contents API writes |

### Render (Backend)
| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (internal URL) |
| `ADMIN_PASSWORD` | Login password for admin API |
| `ADMIN_SECRET_KEY` | JWT signing key |
| `ALLOWED_ORIGINS` | CORS allowed origins (Vercel URL) |
| `GITHUB_PAT` | GitHub PAT with `actions:write` scope |
| `CLOUDINARY_URL` | Image hosting for all uploads — `cloudinary://<key>:<secret>@wyxr` |
| `CLOUDINARY_FOLDER_PREFIX` | Optional; defaults to `concert-calendar` |
| `SUBMISSION_IP_SALT` | Salts hashed submitter IPs for submit-form rate limiting |
| `ANTHROPIC_API_KEY` | Claude Vision for the Slack image pipeline |
| `SLACK_BOT_TOKEN` | Slack bot token (`files:read`, `chat:write`, `channels:history`) |
| `SLACK_SIGNING_SECRET` | Verifies inbound Slack webhooks |
| `SLACK_CHANNEL_ID` | Channel ID for #wyxr-concert-calendar |

### GitHub Actions
| Variable | Purpose |
|----------|---------|
| `TICKETMASTER_API_KEY` | Ticketmaster API |
| `ANTHROPIC_API_KEY` | Claude Vision for artifacts |
| `DATABASE_URL` | PostgreSQL (external URL) |
| `VERCEL_DEPLOY_HOOK` | Auto-redeploy after builds |

## Setup Steps

### 1. Render Backend

1. Create a PostgreSQL database on Render (Starter plan recommended)
2. Create a Web Service on Render:
   - **Root directory:** `./`
   - **Build command:** `pip install -r backend/requirements.txt`
   - **Start command:** `gunicorn -c backend/gunicorn_conf.py backend.app:app`
   - **Environment variables:** `DATABASE_URL`, `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, `ALLOWED_ORIGINS`, `GITHUB_PAT`
3. Run the database schema:
   ```bash
   psql $DATABASE_URL < scripts/schema.sql
   ```
4. Run the migration to import existing events:
   ```bash
   DATABASE_URL=... python scripts/migrate_json_to_db.py
   ```

**Note:** Use the internal DATABASE_URL for Render services, external URL for GitHub Actions and local scripts. Paste carefully — line breaks in the URL cause connection failures.

### 2. Vercel Frontend

1. Set env vars: `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, `GITHUB_PAT`
2. Deploy to Vercel

### 3. Admin UI Configuration

Each admin page has a `<script>` tag before `admin-common.js`:
```html
<script>window.__API_BASE = 'https://concert-calendar-api.onrender.com';</script>
<script src="/admin/admin-common.js"></script>
```

## API Endpoints (Render Backend)

### Public
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (also served at `/`) |
| GET | `/api/events` | Active events (supports `start_date`, `end_date`, `featured_only`) |
| GET | `/api/events/:id` | Single event detail |
| GET | `/api/neighborhoods` | Neighborhood list with event counts |

### Auth
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/login` | Login, returns JWT |
| POST | `/api/admin/logout` | Clear session |
| GET | `/api/admin/me` | Check auth status |

### Admin Events
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/events` | All events (including inactive) |
| POST | `/api/admin/events` | Create event |
| PUT | `/api/admin/events/:id` | Update event |
| DELETE | `/api/admin/events/:id` | Soft-delete event |
| PATCH | `/api/admin/events/:id/featured` | Toggle featured |
| POST | `/api/admin/events/bulk` | Bulk actions |
| POST | `/api/admin/events/prune` | Hard-delete events older than today |

### Admin Venues
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/venues` | List all venues with neighborhoods |
| GET | `/api/admin/venues/unmapped` | Venues with no neighborhood assigned |
| POST | `/api/admin/venues` | Create new venue |
| PUT | `/api/admin/venues/:id` | Update venue name/neighborhood |
| DELETE | `/api/admin/venues/:id` | Delete a venue |
| POST | `/api/admin/venues/merge` | Merge two venues (keep_id, merge_id) |
| POST | `/api/admin/venues/backfill` | Backfill neighborhoods on existing events |

### Import
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/import/upload` | Upload HTML/images, get parsed preview |
| POST | `/api/admin/import/confirm` | Save confirmed events to DB |
| POST | `/api/admin/import/image` | Single image upload |

### Scraper & Maintenance
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/scraper/logs` | Recent scrape log entries |
| GET | `/api/admin/scraper/status` | Per-source scraper status summary |
| POST | `/api/admin/build/trigger` | Trigger GitHub Actions build |

## Venue Scrapers

| Venue | Scraper Type | Method |
|-------|-------------|--------|
| Hi Tone | `hi_tone` | Custom HTML parser (hitonecafe.com) |
| Minglewood Hall | `minglewood` | Custom HTML parser (minglewoodhallmemphis.com) |
| Hernando's Hideaway | `hernandos` | Custom HTML parser (hernandoshideawaymemphis.com) |
| Growlers | `growlers` | SeeTickets widget parser (901growlers.com) |
| Graceland Soundstage | `graceland` | Wix section parser (gracelandlive.com/shows) |
| Lafayette's Music Room | `elfsight` | Elfsight JSON API (widget ID: a23b899c...) |
| Nashoba | `elfsight` | Elfsight JSON API (widget ID: cec78113...) |
| Crosstown Arts | `generic` | JSON-LD parser (crosstownarts.org) |
| Overton Park Shell | `generic` | JSON-LD parser (overtonparkshell.org) |
| FedExForum | `generic` | JSON-LD parser (fedexforum.com) |
| Germantown PAC | `generic` | JSON-LD parser (gpacweb.com) |

Venue scrapers use a 6-month date range (`SCRAPER_END_DATE`) for the interactive calendar. The `is_music_event()` filter is bypassed for venue scrapers since venue calendars are music events by definition.

## Deployment Status

- **Render backend:** `https://concert-calendar-api.onrender.com` (Starter plan, always-on)
- **Vercel frontend:** `https://concert-calendar.wyxr.org`
- **PostgreSQL:** Render Starter plan, `events` + `scrape_logs` + `venues` tables
- **Scrape logging:** Enabled via `DATABASE_URL` GitHub Actions secret
- **Trigger Build:** Admin Tools tab, calls GitHub Actions workflow_dispatch
- **Prune Old Events:** Admin Tools tab, hard-deletes events before today from PostgreSQL

## Gunicorn Configuration

`backend/gunicorn_conf.py`:
- `preload_app=True` — loads app in master before forking workers (critical for Render stability)
- `timeout=120` — accommodates cold DB connections
- `graceful_timeout=10` — old workers release port quickly during deploys
- Lifecycle hooks log worker fork/exit/abort for debugging

## Evolution Notes

### Phase 1: Flat File
- `data/events.json` as the central event store
- Admin UI wrote directly to events.json via Vercel serverless API routes
- No database

### Phase 2: Render Backend + PostgreSQL
- Added Flask API on Render with PostgreSQL
- Admin UI switched to Render API via `window.__API_BASE`
- PostgreSQL held events + scrape_logs
- events.json remained the "source of truth" with write-through sync from admin

### Phase 3: Write-Through Sync (removed)
- Every admin action synced to both PostgreSQL and events.json via GitHub API
- Debounced build trigger auto-rebuilt the calendar after admin changes
- **Problem:** Race condition between admin writes and GitHub Actions builds both targeting events.json caused git merge conflicts. Silent `|| true` on `git stash pop` led to corrupted JSON being committed, wiping 37 events.

### Phase 4: PostgreSQL as Single Source of Truth (current)
- Removed all events.json write-through from the backend
- Build reads/writes PostgreSQL directly (with events.json fallback for local dev)
- events.json is now a read-only snapshot exported by the build
- Eliminated the two-writer race condition entirely

### Phase 5: Interactive Calendar + Venue Management (current)
- Added interactive calendar as homepage (`docs/index.html`) with 6-month lookahead
- Client-side filtering: neighborhoods, text search, month navigation
- `venues` table in PostgreSQL with neighborhood mapping and alias support
- Venue merge capability in admin UI (consolidates duplicate venues)
- Per-source scraper status cards in admin (replaced public page source logs)
- Custom scrapers: SeeTickets (Growlers), Wix (Graceland), Elfsight (Lafayette's, Nashoba)
- Static "This Week" page moved to `docs/thisweek.html`

## Known Limitations

- **Artifact** uploads (files to be processed by Claude Vision) commit to the GitHub `artifacts/` folder, not Render — Render storage is ephemeral, and the build reads them off disk during Actions. This is separate from **event/sponsor image** uploads, which go to Cloudinary and resolve immediately.
- Without `DATABASE_URL`, the build falls back to events.json as a local data store (useful for development).
- Event deduplication across sources (scrapers + vision imports) is basic — see FEATURES.md #16.
- Generic scrapers (JSON-LD) depend on venue sites implementing structured data — some venues don't.

---

## Migration: PostgreSQL as Single Source of Truth (Consolidation)

### Pre-Implementation Analysis

**Current state (what's already done):**
- Frontend (`docs/index.html`) already fetches from Render API — NOT from `events.json`
- Admin UI already points to Flask backend via `window.__API_BASE`
- Scrapers already write to PostgreSQL via `_save_events_to_db()`
- `source` column exists with `DEFAULT 'manual'`
- Source priority partially implemented (skips `"admin"` and `"manual"` on upsert)

**What still needs to change:**
1. Standardize source values to `manual`, `scraper:{name}`, `artifact` convention
2. Add full source priority: manual > scraper > artifact
3. Admin edits must set source to `"manual"` when saving
4. Remove Vercel serverless functions (`api/` directory) — all have Flask equivalents
5. GitHub Actions should stop committing data files
6. Clean up residual `events.json` references

### Task Checklist

- [x] Step 1: Standardize source column values
- [x] Step 2: Full source priority in scraper upsert
- [x] Step 3: Verify public events API endpoint (already existed)
- [x] CHECKPOINT 1
- [x] Step 4: Confirm frontend uses API (already done — no changes needed)
- [x] Step 5: Verify Vercel functions are redundant (all have Flask equivalents)
- [x] Step 6: Remove `api/` directory and update vercel.json
- [x] CHECKPOINT 2
- [x] Step 7: GitHub Actions stops committing data files
- [x] Step 8: Clean up residual references
- [x] CHECKPOINT 3

### Decisions Made

1. **Source value for `submission`**: Backfilled to `"manual"` — approved submissions are human-vetted
2. **Source value for `import`**: Backfilled to `"artifact"` — automated HTML extraction
3. **Venue source slug format**: `"Hi Tone"` → `"scraper:hi_tone"` via regex slug
4. **SourceResult display names unchanged**: `"Venue: Hi Tone"` still used in logs/UI, only Event.source changed
5. **`events_json.py` kept**: Still needed for snapshot export and DB-unavailable fallback
6. **Migration scripts kept**: `scripts/migrate_*.py` are historical one-time scripts, not actively used
7. **`thisweek.html` generation kept**: Still generated by builds but no longer committed to git
