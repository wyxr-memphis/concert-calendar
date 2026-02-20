# WYXR Memphis Concert Calendar

A daily-updating live music calendar for Memphis, Tennessee. Built for [WYXR 91.7 FM](https://wyxr.org) DJs to reference on-air.

**Live page:** [concert-calendar-eight.vercel.app](https://concert-calendar-eight.vercel.app)
**Admin:** [concert-calendar-eight.vercel.app/admin/](https://concert-calendar-eight.vercel.app/admin/)

## How It Works

A Python script runs twice daily (midnight and noon Central) via GitHub Actions. It pulls event data from multiple sources, merges into a PostgreSQL database (preserving admin edits), and publishes a static HTML calendar. A password-protected admin UI lets you add/edit/feature/deactivate events, upload artifacts, and monitor scraper health.

### Sources (checked daily)

| Source | Method | Notes |
|--------|--------|-------|
| Ticketmaster | API | Best coverage for major venues |
| Venue websites | Custom scrapers | Hi Tone, Minglewood, Hernando's, Crosstown, GPAC |
| Artifacts (images/pages) | Claude Vision API + HTML parsing | Upload flyers or saved web pages |
| Admin UI | PostgreSQL database | Manual entries, edits, featured picks |

### Venues tracked

**Scraped automatically:** Hi Tone, Minglewood Hall, Hernando's Hideaway, Crosstown Arts/Green Room, Germantown PAC, B.B. King's, FedExForum, Graceland Soundstage

**Manual entry via Google Sheet or artifact upload:** Bar DKDC, B-Side Memphis, Orpheum Theatre, Lafayette's Music Room, Overton Park Shell

Want to add your venue? Email [contact@wyxr.org](mailto:contact@wyxr.org).

## Architecture

```
GitHub Actions (twice daily: midnight + noon Central)
  → Python fetches from all sources
  → Merges into data/events.json (preserving admin edits)
  → Writes scrape logs to PostgreSQL
  → Generates docs/index.html
  → Commits & pushes
  → Triggers Vercel redeploy

Render (Backend API)
  → Flask REST API at concert-calendar-api.onrender.com
  → PostgreSQL database (events + scrape_logs)
  → Admin auth (JWT), event CRUD, import, scraper status

Vercel (Frontend)
  → Serves docs/index.html (public calendar)
  → Serves docs/admin/ (admin UI — Events, Import, Scrapers)
  → Serves docs/upload.html (artifact upload form)
```

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
3. Set environment variables: `DATABASE_URL` (internal), `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, `ALLOWED_ORIGINS` (Vercel URL), `GITHUB_PAT`
4. Run `psql $DATABASE_URL < scripts/schema.sql` and `python scripts/migrate_json_to_db.py`

See `IMPLEMENTATION_LOG.md` for detailed setup steps.

### 3. GitHub Secrets

Add these as GitHub Secrets (Settings → Secrets → Actions):

| Secret Name | Value | Required? |
|------------|-------|-----------|
| `TICKETMASTER_API_KEY` | Ticketmaster consumer key | Yes |
| `ANTHROPIC_API_KEY` | Anthropic API key (for image artifact processing) | For image uploads |
| `DATABASE_URL` | PostgreSQL external URL (for scrape logging) | Recommended |
| `VERCEL_DEPLOY_HOOK` | Vercel deploy hook URL (for auto-redeploy after builds) | Recommended |

### 4. Test It

Trigger a manual run from the **Actions** tab → **Daily Concert Calendar Update** → **Run workflow**. Or use the "Trigger Build" button in the admin Scrapers tab.

## Admin UI

Visit `/admin/` on your Vercel deployment to manage events:

- **Events tab** — List all events, toggle featured/active, search, filter, edit, add new
- **Import tab** — Upload HTML files (parsed for events) or images, preview and confirm imports
- **Scrapers tab** — Monitor scraper health, view run logs, trigger builds on demand

## Uploading Artifacts

Visit `/upload.html` on your Vercel deployment to upload event sources from any device (phone, laptop, etc.):

- **Images** (PNG, JPG, WebP, GIF) — flyers, screenshots of event listings. Processed by Claude Vision API.
- **Web pages** (MHTML, HTML) — saved venue calendars. Parsed directly with BeautifulSoup.

Uploaded files are committed to the `artifacts/` folder in the repo. Hit "Rebuild Calendar" to process them immediately, or wait for the next daily run. Artifacts older than 24 hours are automatically cleaned up.

## Adding a New Venue

1. Add the venue to `VENUES` in `src/config.py` with `name`, `aliases`, `calendar_url`, and `scraper` type
2. The generic scraper handles JSON-LD and common CMS patterns (Squarespace, WordPress Events Calendar, etc.)
3. If needed, add a custom parser in `src/sources/venue_scrapers.py`
4. For Instagram-only venues, set `scraper: "manual_only"` and use the Google Sheet or artifact upload

## Project Structure

```
concert-calendar/
├── .github/workflows/
│   └── daily.yml              # GitHub Actions schedule (2x daily)
├── backend/
│   ├── app.py                 # Flask REST API (Render)
│   ├── db.py                  # PostgreSQL queries
│   ├── auth.py                # JWT auth for Flask
│   ├── requirements.txt       # Backend dependencies
│   └── Procfile               # Render start command
├── api/
│   ├── upload.py              # Vercel serverless: artifact upload
│   ├── rebuild.py             # Vercel serverless: trigger rebuild
│   ├── _auth.py               # JWT helpers (Vercel)
│   └── admin/                 # Vercel admin API routes (legacy)
├── src/
│   ├── main.py                # Orchestrator (fetch → merge → HTML)
│   ├── config.py              # Venues, keywords, settings
│   ├── models.py              # Event and SourceResult data models
│   ├── date_utils.py          # Shared date parsing
│   ├── http_utils.py          # HTTP client with retry logic
│   ├── normalize.py           # Deduplication logic
│   ├── generate_html.py       # Static page generator
│   └── sources/
│       ├── ticketmaster.py    # Ticketmaster Discovery API
│       ├── venue_scrapers.py  # Individual venue website scrapers
│       ├── events_json.py     # Read/write data/events.json
│       └── artifacts.py       # Image + web page artifact processing
├── data/
│   └── events.json            # Central event database
├── scripts/
│   ├── schema.sql             # PostgreSQL schema
│   └── migrate_json_to_db.py  # Migration to PostgreSQL
├── docs/
│   ├── index.html             # Published calendar (auto-generated)
│   ├── upload.html            # Upload form
│   ├── admin/                 # Admin UI (login, events, import, scrapers)
│   └── log.json               # Latest run log
├── vercel.json                # Vercel config
├── requirements.txt
└── README.md
```

## Run Locally

```bash
git clone https://github.com/wyxr-memphis/concert-calendar.git
cd concert-calendar
pip install -r requirements.txt

export TICKETMASTER_API_KEY="your_key"

# Dry run — prints results without writing files
python -m src.main --dry-run

# Full run — generates docs/index.html
python -m src.main
```

## Cost

**$0/month** for hosting and APIs. GitHub Actions, Vercel free tier, Render free tier, and Ticketmaster API are all free. Only cost is Anthropic API usage for image artifact processing (pennies per image). Note: Render free tier databases expire after 90 days.

## License

Internal tool for WYXR 91.7 FM. Built in Memphis.
