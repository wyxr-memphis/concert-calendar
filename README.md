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

### Venues tracked (27)

**Custom scrapers:** Hi Tone, Minglewood Hall, Hernando's Hideaway, Growlers, Graceland
Soundstage, Lafayette's Music Room, Nashoba, Crosstown Arts, Crosstown Brewing Co., Flyway
Brewing, Huey's (all locations), Overton Park Shell, B.B. King's Blues Club, Blues City Cafe,
Landers Center, Orpheum Theatre, South Main Sounds

**Ticketmaster (by venue ID):** FedExForum, Cannon Center, Satellite Music Hall, Grind City
Amphitheater, Radians Amphitheater, BankPlus Amphitheater at Snowden Grove, Bluesville at
Horseshoe

**Generic scraper:** Germantown Performing Arts Center

**Manual entry via admin UI, Slack, or artifact upload:** Bar DKDC, B-Side Memphis

Events also arrive for many other rooms via the Slack flyer pipeline and admin entry, so the
calendar covers more venues than are scraped on a schedule.

Want to add your venue? Email [contact@wyxr.org](mailto:contact@wyxr.org).

## Architecture

```
GitHub Actions (twice daily: midnight + noon Central)
  -> Python fetches from all sources
  -> Merges into PostgreSQL (single source of truth)
  -> Exports data/events.json (read-only snapshot)
  -> Generates docs/thisweek.html (static 8-day calendar, with Event JSON-LD)
  -> Generates docs/feed.xml (RSS feed, next 60 days)
  -> Generates docs/calendar.ics (iCalendar subscribe feed, next 180 days)
  -> Generates docs/sitemap.xml + docs/robots.txt
  -> Commits & pushes
  -> Triggers Vercel redeploy

Render (Backend API)
  -> Flask REST API at concert-calendar-api.onrender.com
  -> PostgreSQL database (events + scrape_logs + venues)
  -> Admin auth (JWT), event CRUD, venue management, import, scraper status
  -> Renders /e/<id> event permalink pages (server-side, for shares + crawlers)

Vercel (Frontend)
  -> Serves docs/index.html (interactive calendar with 6-month lookahead)
  -> Serves docs/thisweek.html (static "This Week" page)
  -> Serves docs/feed.xml (RSS 2.0 feed for app integration)
  -> Serves docs/calendar.ics (webcal:// subscribe feed)
  -> Rewrites /e/<id> to the Render API so shared links stay on the public domain
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

### Badge flags (WYXR Pick / WYXR Presents)

The badges are also published as **machine-readable flags**, so a consumer never has to string-match `"WYXR Pick"` out of `<title>` or `<description>` to style a row:

```xml
<rss version="2.0"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:wyxr="https://concert-calendar.wyxr.org/ns/rss/1.0">
  ...
  <item>
    <title>The Danny Banks Quartet — Huey's (Midtown)</title>
    <description>Sunday, August 23, 2026 | Huey's (Midtown) | 3 PM | WYXR Pick</description>
    <category>WYXR Pick</category>
    <wyxr:presents>false</wyxr:presents>
    <wyxr:pick>true</wyxr:pick>
    <wyxr:badge>WYXR Pick</wyxr:badge>
  </item>
```

| Element | Notes |
|---|---|
| `<category>` | Standard RSS, so generic readers surface it. Emitted **only when true** — `WYXR Presents` and/or `WYXR Pick`. Sponsor callout items use `Sponsored`. |
| `<wyxr:presents>` | Always present on event items: `true` / `false`. Maps to the DB column `is_wyxr_presents`. |
| `<wyxr:pick>` | Always present on event items: `true` / `false`. Maps to the DB column `is_featured`. |
| `<wyxr:badge>` | The single label to display when a row can only show one badge. Omitted when the event has neither. **WYXR Presents wins** if an event is flagged both — same precedence as the calendar and the `<description>` text. |

Both flags can be `true` on the same event, which is why they're separate elements rather than one enum. Read `<wyxr:badge>` if you want the one-badge answer with precedence already applied; read the two booleans if you want to render both.

The existing human-readable text in `<title>`, `<description>`, and `<content:encoded>` is unchanged — this is additive, so nothing consuming the feed today breaks.

## Calendar Subscribe Feed (iCal / webcal)

The whole calendar is published as an iCalendar feed so anyone can subscribe to it in Apple
Calendar, Google Calendar or Outlook and have it refresh itself twice a day:

| | |
|---|---|
| **Subscribe** | `webcal://concert-calendar.wyxr.org/calendar.ics` |
| **Download / fetch** | [`concert-calendar.wyxr.org/calendar.ics`](https://concert-calendar.wyxr.org/calendar.ics) |
| **Window** | next 180 days (wider than RSS — a subscribed calendar should show everything we know) |
| **Refresh hint** | `REFRESH-INTERVAL` / `X-PUBLISHED-TTL` of 12 hours, matching the build cadence |

`webcal://` is what makes a calendar app offer to *subscribe* rather than import a one-off
copy; the `https://` link next to it in the footer is the fallback.

Each `VEVENT` carries `SUMMARY` ("Artist — Venue"), `LOCATION`, `DTSTART`/`DTEND`,
`CATEGORIES` (WYXR Presents / WYXR Pick / genre), and a `DESCRIPTION` with doors and show
times, price, and links to tickets and to the event page.

Two implementation notes that matter if you edit `src/generate_ics.py`:

- **Times are UTC instants, not floating local times with a `VTIMEZONE`.** A hand-maintained
  VTIMEZONE block can drift; converting Central to UTC through `zoneinfo` cannot. A summer
  show is `-05:00` and a winter show `-06:00`, and `scripts/test_ics_feed.py` asserts both.
- **UIDs match the per-event `.ics` download** from the calendar's event modal
  (`wyxr-event-<id>@concert-calendar.wyxr.org`), so someone who grabbed a single show and
  later subscribes gets one entry, not two.

## Event Permalinks (`/e/<id>`)

Every event has its own shareable page, e.g.
`concert-calendar.wyxr.org/e/2f9c…`. Vercel rewrites that path to the Render API, which
renders the page **from the database on request** — so an admin correction is live
immediately, with no build.

Why it exists: the homepage is client-rendered, so before this every shared link unfurled
with the same generic site card in Slack, iMessage and Facebook, and no individual show was
indexable. Each page carries its own `og:` tags (including the flyer image) plus
`MusicEvent` structured data, and is listed in `sitemap.xml`.

In the calendar itself:

- Opening a show pushes `#event=<id>` into the URL, so the browser's Back button closes the
  modal and the address bar always names what is on screen.
- Loading `/#event=<id>` opens that show's modal directly.
- The modal has a **Copy link** button that copies the `/e/<id>` permalink — the one that
  unfurls properly — not the hash URL.

## SEO

- `thisweek.html` is the server-rendered page, so its `ItemList` of `MusicEvent` JSON-LD is
  visible to crawlers that do not run JavaScript. This is the page that gets Memphis shows
  into search results.
- `index.html` carries `WebSite` + `RadioStation` JSON-LD statically and injects an
  `ItemList` for the rendered month once the API responds.
- `/e/<id>` pages carry per-event `MusicEvent` JSON-LD, server-rendered.
- `sitemap.xml` lists the static pages plus one URL per event in the 180-day window;
  `robots.txt` points at it. Past events are deliberately excluded. Static entries use the
  extensionless form (`/thisweek`, not `/thisweek.html`) because `cleanUrls` 308-redirects
  the `.html` paths — each page's `rel=canonical` and `og:url` match.
- Both feeds are advertised with `<link rel="alternate">` on every page and linked in the
  footer. Before this they existed with nothing pointing at them.

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
│   ├── auth.py                # JWT auth, login throttle, CSRF-safe upload guard
│   ├── event_page.py          # Server-rendered /e/<id> permalink pages (OG + JSON-LD)
│   ├── images.py              # Cloudinary upload/delete + image sanitization
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
│   ├── date_utils.py          # Shared date parsing (incl. year-rollover resolution)
│   ├── time_format.py         # Cross-platform strftime + event time formatting
│   ├── http_utils.py          # HTTP client with retry logic
│   ├── normalize.py           # Deduplication logic
│   ├── generate_html.py       # Static "This Week" page generator (+ Event JSON-LD)
│   ├── generate_rss.py        # RSS 2.0 feed generator (60-day window)
│   ├── generate_ics.py        # iCalendar subscribe feed (180-day window)
│   ├── generate_sitemap.py    # sitemap.xml + robots.txt
│   └── sources/
│       ├── ticketmaster.py    # Ticketmaster Discovery API
│       ├── venue_scrapers.py  # Venue website scrapers (custom + generic)
│       ├── events_json.py     # Read/write data/events.json
│       └── artifacts.py       # Image + web page artifact processing
├── data/
│   └── events.json            # Read-only snapshot (exported by build)
├── scripts/
│   ├── schema.sql             # PostgreSQL schema
│   ├── migrate_json_to_db.py  # Migration to PostgreSQL
│   ├── cleanup_duplicates.py  # Remove duplicate events (dry run by default)
│   ├── backfill_dedup_key.py  # Recompute dedup_key + build the unique index
│   ├── reassign_venue.py      # Move events between venues (dry run by default)
│   ├── nightly_health_check.py
│   ├── browser_test_util.py   # Shared Chromium discovery + static server for browser tests
│   └── test_*.py / test_escaping.mjs   # Regression suites (see Testing)
├── docs/
│   ├── index.html             # Interactive calendar (homepage)
│   ├── thisweek.html          # Static "This Week" page (auto-generated)
│   ├── feed.xml               # RSS 2.0 feed (auto-generated, 60-day window)
│   ├── calendar.ics           # iCalendar subscribe feed (auto-generated, 180-day window)
│   ├── sitemap.xml            # Sitemap incl. every /e/<id> page (auto-generated)
│   ├── robots.txt             # Points at the sitemap (auto-generated)
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

## Testing

```bash
./test_before_push.sh     # expect 16/16
```

There is no test framework. Each suite is a standalone script under `scripts/`, offline
apart from the database connection check, wired into `test_before_push.sh`:

| Suite | Covers |
|---|---|
| `test_health_check.py` | nightly health-check report parsing |
| `test_normalization.py` | year rollover, title/venue normalization, date + time formatting |
| `test_admin_auth.py` | CSRF guard, login throttling, non-ASCII password (needs no DB) |
| `test_escaping.mjs` | `escAttr` / `safeUrl` against attack payloads |
| `test_ticketmaster_pagination.py` | paging, the API's 1000-item ceiling, non-terminating API |
| `test_ics_feed.py` | iCalendar DST offsets, RFC 5545 folding and escaping, UID stability |
| `test_event_page.py` | `/e/<id>` escaping, JSON-LD, price parsing, 404/503 route behaviour |
| `test_xss_browser.py` | the real calendar page in Chromium against live payloads |
| `test_deeplink_browser.py` | `#event=` deep links, Back/Forward, injected JSON-LD, feed links |

The two browser suites need Chromium and **skip cleanly without it**, so check the count
rather than the "all checks passed" line — skipping both reports 14/14 instead of 16/16
(the count exceeds the number of numbered checks because check 1 counts two env vars):

```bash
pip3 install playwright && python3 -m playwright install chromium
```

`test_escaping.mjs` extracts the escaping helpers from the shipped files rather than copying
them, so it fails if the implementation regresses.

### Maintenance scripts

Both preview by default and take `--confirm` (or `--dry-run` for the backfill) — see
`CLAUDE.md` → *Fix duplicates* for the required order.

```bash
python scripts/cleanup_duplicates.py            # preview duplicate removal
python scripts/backfill_dedup_key.py --dry-run  # preview dedup_key changes
```

## Cost

Render Starter plan ($7/month) for always-on backend + PostgreSQL. GitHub Actions, Vercel free tier, and Ticketmaster API are all free. Anthropic API usage for image artifact processing is ~$0.01 per image.

## License

Internal tool for WYXR 91.7 FM. Built in Memphis.
