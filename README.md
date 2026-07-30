# WYXR Memphis Concert Calendar

A daily-updating live music calendar for Memphis, Tennessee. Built for [WYXR 91.7 FM](https://wyxr.org) DJs to reference on-air.

**Live page:** [concert-calendar.wyxr.org](https://concert-calendar.wyxr.org)
**Admin:** [concert-calendar.wyxr.org/admin/](https://concert-calendar.wyxr.org/admin/)

## How It Works

A Python script runs twice daily (midnight and noon Central) via GitHub Actions. It pulls event data from multiple sources, merges everything into a PostgreSQL database (the single source of truth), and publishes both an interactive calendar (homepage) and a static "This Week" page. A password-protected admin UI lets you add/edit/feature/deactivate events, manage venues and neighborhoods, upload artifacts, and monitor scraper health.

### Sources (checked daily)

| Source | Method | Notes |
|--------|--------|-------|
| Ticketmaster | API | Best coverage for major venues |
| Venue websites | Custom scrapers | Hi Tone, Minglewood, Hernando's, Growlers, Graceland, Lafayette's, Nashoba, Crosstown, GPAC, and more |
| Artifacts (images/pages) | Claude Vision API + HTML parsing | Upload flyers or saved web pages |
| Admin UI | Direct to PostgreSQL | Manual entries, edits, featured picks |

### Venues tracked (15)

**Custom scrapers:** Hi Tone, Minglewood Hall, Hernando's Hideaway, Growlers, Graceland Soundstage, Lafayette's Music Room, Nashoba

**Generic scrapers:** Crosstown Arts/Green Room, FedExForum, Germantown PAC, Overton Park Shell

**Manual entry via admin UI or artifact upload:** B.B. King's Blues Club, Orpheum Theatre, Bar DKDC, B-Side Memphis

Want to add your venue? Email [contact@wyxr.org](mailto:contact@wyxr.org).

## Architecture

```
GitHub Actions (twice daily: midnight + noon Central)
  -> Python fetches from all sources
  -> Merges into PostgreSQL (single source of truth)
  -> Exports data/events.json (read-only snapshot)
  -> Generates docs/thisweek.html (static 8-day calendar)
  -> Generates docs/feed.xml (RSS feed, next 60 days)
  -> Commits & pushes
  -> Triggers Vercel redeploy

Render (Backend API)
  -> Flask REST API at concert-calendar-api.onrender.com
  -> PostgreSQL database (events + scrape_logs + venues)
  -> Admin auth (JWT), event CRUD, venue management, import, scraper status

Vercel (Frontend)
  -> Serves docs/index.html (interactive calendar with 6-month lookahead)
  -> Serves docs/thisweek.html (static "This Week" page)
  -> Serves docs/feed.xml (RSS 2.0 feed for app integration)
  -> Serves docs/submit.html (public event submission form, optional flyer upload)
  -> Serves docs/admin/ (admin UI — Events, Import, Scrapers, Venues, Sponsors, Submissions)
```

### Data Flow

- **Admin edits** go directly to PostgreSQL via the Render API
- **Scrapers** fetch external sources, merge into PostgreSQL, then export `events.json` as a snapshot
- **Static HTML** is generated from PostgreSQL during the build (8-day "This Week" page)
- **Interactive calendar** fetches events from the API with a 6-month window, filters client-side
- **`data/events.json`** is a read-only export — never edited directly

## Setup

### 1. Deploy to Vercel (Frontend)

```bash
cd concert-calendar
vercel          # Link to the repo
vercel --prod   # Deploy
```

Set these environment variables in the Vercel dashboard:
- `UPLOAD_PASSWORD` — password for the upload form
- `GITHUB_PAT` — fine-grained PAT with `contents:write` scope for this repo
- `ADMIN_PASSWORD` — password for admin login
- `ADMIN_SECRET_KEY` — JWT signing key (generate: `python -c "import secrets; print(secrets.token_hex(32))"`)

### 2. Deploy to Render (Backend API)

1. Create a PostgreSQL database on Render
2. Create a Web Service pointing to this repo
3. Set environment variables: `DATABASE_URL` (internal), `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, `ALLOWED_ORIGINS` (Vercel URL), `GITHUB_PAT`, `CLOUDINARY_URL` (image hosting — uploads return 502 without it), `SUBMISSION_IP_SALT`, plus `ANTHROPIC_API_KEY` / `SLACK_*` for the Slack image pipeline. Full list in `IMPLEMENTATION_LOG.md`.
4. Run `psql $DATABASE_URL < scripts/schema.sql` and `python scripts/migrate_json_to_db.py`

See `IMPLEMENTATION_LOG.md` for detailed setup steps.

### 3. GitHub Secrets

Add these as GitHub Secrets (Settings -> Secrets -> Actions):

| Secret Name | Value | Required? |
|------------|-------|-----------|
| `TICKETMASTER_API_KEY` | Ticketmaster consumer key | Yes |
| `ANTHROPIC_API_KEY` | Anthropic API key (for image artifact processing) | For image uploads |
| `DATABASE_URL` | PostgreSQL external URL | Yes |
| `VERCEL_DEPLOY_HOOK` | Vercel deploy hook URL (for auto-redeploy after builds) | Recommended |

### 4. Test It

Trigger a manual run from the **Actions** tab -> **Daily Concert Calendar Update** -> **Run workflow**. Or use the "Trigger Build" button in the admin Tools tab.

## Admin UI

Visit `/admin/` on your Vercel deployment to manage events:

- **Events tab** — List all events, toggle featured/active, search, filter, edit, add new
- **Import** — Upload images (Claude Vision) or saved web pages (HTML parsing)
- **Tools tab** — Per-source scraper status cards with run history, trigger builds, prune old events
- **Venues tab** — Manage venue-to-neighborhood mapping, merge duplicate venues
- **Submissions tab** — Review community submissions from `/submit`. A submitted flyer is held in Postgres and only uploaded to Cloudinary when you approve, so unreviewed images never touch the image quota.

## RSS Feed

An RSS 2.0 feed is available at [`concert-calendar.wyxr.org/feed.xml`](https://concert-calendar.wyxr.org/feed.xml) for integration with the WYXR app, feed readers, and other platforms. It includes the next 60 days of events, updated automatically with every build (twice daily). Each item includes artist, venue, date, time, price, genre, and WYXR Presents/Pick badges.

## Interactive Calendar

The homepage (`/`) is an interactive calendar with:
- **6-month lookahead** — browse events months in advance
- **Neighborhood filtering** — filter by area (Midtown, Downtown, etc.) via chips
- **Text search** — find events by artist, venue, or keyword
- **Month navigation** — browse forward/backward through months

## Uploading Artifacts

Use the **Import** section within the Events tab to upload event sources:

- **Images** (PNG, JPG, WebP, GIF) — flyers, screenshots of event listings. Processed by Claude Vision API.
- **Web pages** (MHTML, HTML) — saved venue calendars. Parsed directly with BeautifulSoup.

Uploaded files are committed to the `artifacts/` folder in the repo. Hit "Trigger Build" to process them immediately, or wait for the next daily run. Artifacts older than 24 hours are automatically cleaned up.

## Adding a New Venue

1. Add the venue to `VENUES` in `src/config.py` with `name`, `aliases`, `neighborhood`, `calendar_url`, and `scraper` type
2. The generic scraper handles JSON-LD and common CMS patterns (Squarespace, WordPress Events Calendar, etc.)
3. If needed, add a custom parser in `src/sources/venue_scrapers.py` — existing parsers include SeeTickets (Growlers), Wix (Graceland), and Elfsight (Lafayette's, Nashoba)
4. For Instagram-only venues, set `scraper: "manual_only"` and use the admin UI or artifact upload
5. After adding, seed the venue in `db.py` `_seed_venues_if_empty()` and assign a neighborhood

## Project Structure

```
concert-calendar/
├── .github/workflows/
│   └── daily.yml              # GitHub Actions schedule (2x daily)
├── backend/
│   ├── app.py                 # Flask REST API (Render)
│   ├── db.py                  # PostgreSQL queries (events, venues, scrape_logs)
│   ├── gunicorn_conf.py       # Gunicorn config (preload_app, lifecycle hooks)
│   ├── auth.py                # JWT auth for Flask
│   ├── requirements.txt       # Backend dependencies
│   └── Procfile               # Render start command
├── api/
│   ├── upload.py              # Vercel serverless: artifact upload
│   ├── rebuild.py             # Vercel serverless: trigger rebuild
│   └── _auth.py               # JWT helpers (Vercel)
├── src/
│   ├── main.py                # Orchestrator (fetch -> merge -> DB -> HTML -> RSS)
│   ├── config.py              # Venues, neighborhoods, keywords, settings
│   ├── models.py              # Event and SourceResult data models
│   ├── date_utils.py          # Shared date parsing
│   ├── http_utils.py          # HTTP client with retry logic
│   ├── normalize.py           # Deduplication logic
│   ├── generate_html.py       # Static "This Week" page generator
│   ├── generate_rss.py        # RSS 2.0 feed generator (60-day window)
│   └── sources/
│       ├── ticketmaster.py    # Ticketmaster Discovery API
│       ├── venue_scrapers.py  # Venue website scrapers (custom + generic)
│       ├── events_json.py     # Read/write data/events.json
│       └── artifacts.py       # Image + web page artifact processing
├── data/
│   └── events.json            # Read-only snapshot (exported by build)
├── scripts/
│   ├── schema.sql             # PostgreSQL schema
│   └── migrate_json_to_db.py  # Migration to PostgreSQL
├── docs/
│   ├── index.html             # Interactive calendar (homepage)
│   ├── thisweek.html          # Static "This Week" page (auto-generated)
│   ├── feed.xml               # RSS 2.0 feed (auto-generated, 60-day window)
│   ├── admin/                 # Admin UI (login, events, import, scrapers, venues)
│   └── log.json               # Latest run log
├── vercel.json                # Vercel config (redirects, rewrites)
├── requirements.txt
└── README.md
```

## Local Development

Full local development environment with backend, frontend, and admin interface:

```bash
# 1. Set up environment variables
cp .env.example .env
# Edit .env with your credentials (DATABASE_URL, ADMIN_PASSWORD, etc.)

# 2. Start backend (terminal 1)
./run_local_backend.sh

# 3. Start frontend (terminal 2)
./run_local_frontend.sh

# 4. Open in browser
open http://localhost:8000/admin/local.html
```

**Local URLs:**
- Admin: `http://localhost:8000/admin/local.html`
- Homepage: `http://localhost:8000/local_index_home.html`
- Backend API: `http://localhost:5001/api/events`

See **[LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)** for complete setup guide, troubleshooting, and pre-push testing.

### Quick Scraper Test

```bash
# Dry run — prints results without writing files
python -m src.main --dry-run

# Full run — generates docs/thisweek.html and updates database
python -m src.main
```

## Cost

Render Starter plan ($7/month) for always-on backend + PostgreSQL. GitHub Actions, Vercel free tier, and Ticketmaster API are all free. Anthropic API usage for image artifact processing is ~$0.01 per image.

## License

Internal tool for WYXR 91.7 FM. Built in Memphis.
