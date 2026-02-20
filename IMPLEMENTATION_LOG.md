# Admin UI Implementation Log

## Overview
Replaced the Google Sheet manual-entry workflow with a `data/events.json` flat file + password-protected admin UI. The daily build merges automated events into events.json, and the admin can add/edit/feature/deactivate any event.

**Phase 2:** Added Render backend with PostgreSQL database, expanded admin UI with Import and Scraper Dashboard tabs, and enhanced featured event display.

## Architecture

### Current (Vercel-only)
- **events.json** = single source of truth for all events (manual + automated)
- **Daily build** = fetch automated sources → merge into events.json → generate HTML
- **Admin UI** = vanilla HTML+JS at `/admin/` → Python Vercel API routes → GitHub Contents API
- **Auth** = single password → HMAC-SHA256 JWT in httpOnly cookie

### New (Render backend + PostgreSQL)
- **Database** = PostgreSQL on Render with `events` and `scrape_logs` tables
- **Backend API** = Flask on Render serving REST endpoints at `/api/*`
- **Admin UI** = vanilla HTML+JS on Vercel with three tabs: Events, Import, Scrapers
- **Auth** = JWT via Bearer token (cross-origin) or httpOnly cookie (same-origin)
- **Scraper logging** = `src/main.py` writes to `scrape_logs` table when `DATABASE_URL` is set

## Environment Variables

### Vercel (Frontend — server-side only)
| Variable | Purpose | Setup |
|----------|---------|-------|
| `ADMIN_PASSWORD` | Login password | Set in Vercel dashboard |
| `ADMIN_SECRET_KEY` | JWT signing key | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GITHUB_PAT` | GitHub Contents API writes | Already exists |

### Render (Backend)
| Variable | Purpose | Setup |
|----------|---------|-------|
| `DATABASE_URL` | PostgreSQL connection string | Auto-set by Render when linking a database |
| `ADMIN_PASSWORD` | Login password for admin API | Set in Render dashboard (same as Vercel) |
| `ADMIN_SECRET_KEY` | JWT signing key | Set in Render dashboard (same as Vercel) |
| `ALLOWED_ORIGINS` | CORS allowed origins | Vercel frontend URL, e.g. `https://concert-calendar.vercel.app` |

### GitHub Actions (Scraper)
| Variable | Purpose | Setup |
|----------|---------|-------|
| `DATABASE_URL` | (Optional) Write scrape logs to PostgreSQL | Set as GitHub Actions secret |

### Optional overrides
| Variable | Default | Purpose |
|----------|---------|---------|
| `GITHUB_OWNER` | `wyxr-memphis` | GitHub repo owner |
| `GITHUB_REPO` | `concert-calendar` | GitHub repo name |
| `GITHUB_FILE_PATH` | `data/events.json` | Path to events file in repo |

## Setup Steps

### 1. Render Backend Setup

1. Create a PostgreSQL database on Render
2. Create a Web Service on Render:
   - **Root directory:** `./` (project root)
   - **Build command:** `pip install -r backend/requirements.txt`
   - **Start command:** `gunicorn backend.app:app`
   - **Environment variables:** Set `DATABASE_URL`, `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, `ALLOWED_ORIGINS`
3. Run the database schema:
   ```bash
   psql $DATABASE_URL < scripts/schema.sql
   ```
4. Run the migration to import existing events:
   ```bash
   DATABASE_URL=... python scripts/migrate_json_to_db.py
   ```

### 2. Vercel Frontend Setup

1. Ensure env vars are set: `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, `GITHUB_PAT`
2. (Optional) Set `window.__API_BASE` in admin pages to point to the Render backend URL
   - If not set, admin pages fall back to same-origin Vercel API routes
3. Deploy to Vercel

### 3. Admin UI Configuration

To point the admin UI at the Render backend, add a `<script>` tag before `admin-common.js` in each admin page:
```html
<script>window.__API_BASE = 'https://your-render-app.onrender.com';</script>
<script src="/admin/admin-common.js"></script>
```

If `__API_BASE` is not set, the admin UI uses the existing Vercel serverless API routes (backward compatible).

### 4. Enable Scrape Logging (Optional)

Add `DATABASE_URL` as a GitHub Actions secret. The scraper (`src/main.py`) will automatically write to the `scrape_logs` table when `DATABASE_URL` is set and `psycopg2` is available.

Add `psycopg2-binary` to `requirements.txt` if you want scrape logging during GitHub Actions builds.

## File Summary

### New files (Phase 2)
| File | Purpose |
|------|---------|
| `backend/app.py` | Flask backend with all REST API endpoints |
| `backend/db.py` | PostgreSQL connection and query helpers |
| `backend/auth.py` | JWT authentication for Flask |
| `backend/requirements.txt` | Python dependencies for Render |
| `backend/Procfile` | Render start command |
| `backend/__init__.py` | Python package marker |
| `scripts/schema.sql` | Database schema (events + scrape_logs) |
| `scripts/migrate_json_to_db.py` | Migration from events.json to PostgreSQL |
| `docs/admin/admin-common.js` | Shared admin JS utilities (auth, API calls) |
| `docs/admin/import.html` | Import tab (upload, preview, confirm) |
| `docs/admin/scrapers.html` | Scraper dashboard (status, logs) |

### New files (Phase 1)
| File | Purpose |
|------|---------|
| `data/events.json` | Central event database |
| `scripts/migrate_to_events_json.py` | One-time migration |
| `src/sources/events_json.py` | Source reader for build pipeline |
| `api/_auth.py` | JWT helpers (shared module) |
| `api/admin/login.py` | Login endpoint |
| `api/admin/logout.py` | Logout endpoint |
| `api/admin/me.py` | Auth check endpoint |
| `api/admin/events.py` | CRUD endpoint |

### Modified files (Phase 2)
| File | Change |
|------|--------|
| `src/main.py` | Added scrape_logs writing when DATABASE_URL is set |
| `src/generate_html.py` | Added WYXR Pick badge and event--featured CSS class |
| `docs/admin/index.html` | Added navigation tabs, shared admin-common.js, backward-compatible API calls |
| `docs/admin/edit.html` | Added image upload button, shared admin-common.js, backward-compatible API calls |
| `docs/admin/login.html` | Added sessionStorage token for cross-origin auth |

## API Endpoints (Render Backend)

### Public
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/events` | Active events (supports `start_date`, `end_date`, `featured_only`) |
| GET | `/api/events/:id` | Single event detail |

### Auth
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/login` | Login with password, returns JWT |
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

### Scraper
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/scraper/logs` | Recent scrape log entries |
| GET | `/api/admin/scraper/status` | Scraper status dashboard summary |

## Testing Checklist

### Database
- [ ] `events` table exists with all columns
- [ ] `scrape_logs` table exists
- [ ] Migration script runs successfully: `DATABASE_URL=... python scripts/migrate_json_to_db.py`
- [ ] Running migration twice doesn't duplicate data

### API
- [ ] `GET /api/events` returns active events sorted correctly
- [ ] `GET /api/events?featured_only=true` returns only featured events
- [ ] `POST /api/admin/login` rejects wrong password with 401
- [ ] `POST /api/admin/login` returns JWT for correct password
- [ ] All `/api/admin/*` routes return 401 without valid token
- [ ] `POST /api/admin/events` creates an event and returns it with an id
- [ ] `PUT /api/admin/events/:id` updates fields and bumps `updated_at`
- [ ] `DELETE /api/admin/events/:id` soft-deletes (sets `is_active = false`)
- [ ] `PATCH /api/admin/events/:id/featured` toggles featured status
- [ ] CORS allows requests from Vercel frontend domain

### Admin UI
- [ ] `/admin/` shows login page (redirects to login.html if not authenticated)
- [ ] Login with correct password redirects to event list
- [ ] Event list shows all events with correct data
- [ ] Featured toggle works inline (no page reload)
- [ ] Add new event form saves and appears in list
- [ ] Edit existing event saves and shows updated data
- [ ] Delete event soft-deletes and shows as inactive in admin
- [ ] Form validation: cannot save without title and date
- [ ] Navigation tabs work: Events, Import, Scrapers

### Import
- [ ] HTML file upload parses events and shows preview table
- [ ] Preview rows are editable before confirming
- [ ] Confirm import saves selected events to database with source = 'import'
- [ ] Image upload returns a working URL
- [ ] Image upload integrated into event form auto-fills the image_url field
- [ ] Multiple file upload works (HTML + images together)

### Scraper Dashboard
- [ ] Scraper status page shows all scrapers with last run info
- [ ] Status indicators display correctly based on log data
- [ ] Recent runs log shows entries with correct counts
- [ ] Clicking a log entry expands error details
- [ ] Stale "running" entries (>1 hour) show warning badge
- [ ] Failed scraper shows prominent alert at top of dashboard
- [ ] Falls back gracefully when Render API is unavailable

### Public Calendar
- [ ] Featured events appear first within each day
- [ ] Featured events have visual distinction (gold border + WYXR Pick badge)
- [ ] Non-featured events still display correctly
- [ ] Inactive events do not appear on public calendar

### Security
- [ ] No secrets in client code: `grep -r "GITHUB_PAT\|ADMIN_SECRET\|ADMIN_PASSWORD" docs/`
- [ ] Auth tokens expire after 8 hours
- [ ] All admin endpoints require valid JWT

## Open Questions
- Render backend URL needs to be configured in admin pages (via `window.__API_BASE`)
- Image uploads on Render currently save to `/tmp/uploads` — in production, configure `UPLOAD_DIR` and `UPLOAD_BASE_URL` for persistent storage (S3, Cloudflare R2, etc.)
- The existing Vercel serverless API routes (`api/admin/*`) continue to work alongside the new Render backend
