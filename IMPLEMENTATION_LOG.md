# Implementation Log

## Overview

The concert calendar started as a Python script that wrote events to a flat `events.json` file. It evolved through several phases to its current architecture where PostgreSQL is the single source of truth.

## Current Architecture

- **PostgreSQL on Render** = single source of truth for all events (manual + automated)
- **Backend API** = Flask on Render serving REST endpoints at `/api/*`
- **Admin UI** = vanilla HTML+JS on Vercel with two tabs: Events (with Import), Scrapers
- **Auth** = JWT via Bearer token (cross-origin sessionStorage)
- **Daily build** = GitHub Actions 2x daily -> fetch scrapers -> merge into PostgreSQL -> export events.json snapshot -> generate HTML
- **Scraper logging** = `src/main.py` writes to `scrape_logs` table via `DATABASE_URL`
- **`data/events.json`** = read-only snapshot exported by the build (not an input)

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
   - **Start command:** `gunicorn backend.app:app --timeout 120`
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
| GET | `/api/events` | Active events (supports `start_date`, `end_date`, `featured_only`) |
| GET | `/api/events/:id` | Single event detail |

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
| GET | `/api/admin/scraper/status` | Scraper status summary |
| POST | `/api/admin/build/trigger` | Trigger GitHub Actions build |
| POST | `/api/admin/events/prune` | Hard-delete events older than today |

## Deployment Status

- **Render backend:** `https://concert-calendar-api.onrender.com` (Starter plan, always-on)
- **Vercel frontend:** `https://concert-calendar-eight.vercel.app`
- **PostgreSQL:** Render Starter plan, `events` + `scrape_logs` tables
- **Scrape logging:** Enabled via `DATABASE_URL` GitHub Actions secret
- **Run Scrapers:** Admin Scrapers tab, calls GitHub Actions workflow_dispatch
- **Prune Old Events:** Admin Scrapers tab, hard-deletes events before today from PostgreSQL

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

## Known Limitations

- Image uploads via Import commit to GitHub `artifacts/` folder (not Render). Render storage is ephemeral.
- The existing Vercel serverless API routes (`api/admin/*`) are legacy and unused when `__API_BASE` is set.
- Without `DATABASE_URL`, the build falls back to events.json as a local data store (useful for development).
- Event deduplication across sources (scrapers + vision imports) is basic — see FEATURES.md #16.
