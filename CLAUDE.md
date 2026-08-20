# Claude Code Instructions

This document provides context for AI assistants working on the Memphis Concert Calendar project.

## Project Overview

A daily-updating live music calendar for Memphis, Tennessee, built for WYXR 91.7 FM DJs.

**Architecture:**
- **Frontend:** Vercel at `concert-calendar.wyxr.org` (static HTML + interactive JS)
- **Backend API:** Flask on Render at `concert-calendar-api.onrender.com`
- **Database:** PostgreSQL on Render (single source of truth)
- **Build:** GitHub Actions 2x daily (midnight + noon Central)

## Frontend Architecture (Critical — Read Before Touching the Index Page)

`docs/index.html` is **fully self-contained** — all CSS is in a single `<style>` block and all JS is in a single `<script>` block at the bottom. There is **no build step, no bundler, no separate CSS/JS files** for the public calendar. Admin pages have their own separate JS files under `docs/admin/`.

Key structural facts about `docs/index.html`:
- CSS variables defined at `:root` (lines ~34–43): `--wyxr-yellow`, `--wyxr-charcoal`, `--wyxr-border`, etc.
- Subscribe modal HTML: `#subscribeModal` with card class `.subscribe-modal-card` (background `#1A1A1A`, `border-radius: 8px`, overlay `rgba(0,0,0,0.75)`) — **reuse these patterns for any new modal**
- Event Detail Modal HTML: `#eventModal` — opened by clicking any `[data-event-id]` element
- All JS lives inside one IIFE `(function() { 'use strict'; ... })()` starting around line 800
- Events are fetched from the **production Render API** at runtime — the page is static, not server-rendered
- `allEvents` array holds all fetched events; `eventsById` map (`{id: event}`) is built in `showEvents()`
- Event rows use `data-event-id` attribute + event delegation on `#eventList` to open the modal (no per-row listeners)
- **Three escaping helpers, and picking the wrong one is a live XSS bug** (all near the bottom of the script):
  | Helper | Use for | Why not the others |
  |---|---|---|
  | `esc()` | text **between tags** only | Sets `textContent` and reads `innerHTML` back, which encodes `&`, `<`, `>` but **leaves quotes** — so it does not terminate a quoted attribute |
  | `escAttr()` | any value going into a **quoted attribute** | 136 of ~3100 event titles contain a quote character, so `esc()` in an attribute breaks on real data, not just on attacks |
  | `safeUrl()` | any value reaching **`href` / `src`** | Escaping does not stop a `javascript:` URL. Scraper ticket URLs and OCR'd image URLs are untrusted. No-op for `http(s):`, returns `""` otherwise |
  Compose them: `escAttr(safeUrl(cldImg(ev.image_url, 600)))`.
- **Never strip markup with the detached-`innerHTML` idiom.** Assigning to `innerHTML` on a detached div and reading `textContent` back looks safe because a detached element does not run `<script>` — but the parser still **builds the nodes**, so `<img src=x onerror=…>` fires immediately. Use `DOMParser` (its documents have no browsing context). This was a real sink in `_buildCalendarData`, found only by driving the page in a browser.

## Local Development

**Before making changes, always test locally:**

```bash
# Terminal 1: Backend
./run_local_backend.sh

# Terminal 2: Frontend
./run_local_frontend.sh

# Terminal 3: Test changes
./test_before_push.sh
```

See [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) for complete setup.

## Critical Patterns & Lessons Learned

### Data Flow
- **PostgreSQL is the single source of truth** - never write directly to events.json
- `data/events.json` is a read-only snapshot exported by builds
- Admin edits go directly to PostgreSQL via Render API
- Scrapers merge into PostgreSQL, then export snapshot

### Database
- Use **external** PostgreSQL URL for local dev (internal URL only works on Render)
- `gunicorn preload_app=True` is critical - prevents silent worker import failures
- **psycopg2 transaction poisoning:** Use separate `with get_cursor()` blocks per operation
- Root `/` route needed for Render health checks
- **Schema DDL must never run unguarded on boot.** `init_db()` checks the catalog first
  (`_schema_is_current()`) and skips migrations entirely when every table and column
  already exists — the case on every deploy after the first. Migrations that do run use
  `_ddl_cursor()`, which sets `lock_timeout = 5s`.
  **Why:** `CREATE TABLE` / `ALTER TABLE` need an ACCESS EXCLUSIVE lock, and in Postgres a
  *queued* exclusive request blocks every later query on that table — so a blocked boot
  takes plain reads down with it. On 2026-07-29 a stalled build held a lock on `events`
  while a deploy booted workers; their `CREATE TABLE IF NOT EXISTS events` queued, and the
  whole API went down (`/api/events`, `/api/sponsors`, even `/health`) until the stuck
  session was terminated. Any new DDL added to `_run_migrations()` must use `_ddl_cursor()`
  **and be registered for the fast path, or it will be skipped forever**: new tables go in
  `_SCHEMA_TABLES`, new columns on an existing table go in `_SCHEMA_COLUMNS[<table>]`. The
  column case is the sneaky one — the table already exists, so the check passes and the
  column is silently never created on any database that has run the app before.
- **Diagnosing a hung API:** query `pg_stat_activity` for `state = 'idle in transaction'`
  and `wait_event_type = 'Lock'`. Fix is `pg_terminate_backend(<pid>)` plus cancelling the
  build; the build's inserts are `ON CONFLICT DO NOTHING` and re-run next cycle.

### Deduplication
- Event identity is `dedup_key` = `normalize_text(title)|normalize_text(canonical_venue)|date`,
  computed by the single shared `compute_dedup_key` (`src/models.py`). It is stored as a
  column on `events` and enforced by the partial unique index `idx_events_dedup_key`
  (`ON events (dedup_key) WHERE is_active`), so duplicate *active* events are structurally
  impossible.
- `_save_events_to_db()` tracks inserted events within same batch to prevent duplicates
- **Never overwrite admin/manual source entries** - automated scrapers always defer to manual edits

⚠️ **Every path that decides "same event?" must canonicalize the venue through the DB
`venues` table (names + aliases) — not `config.normalize_venue_name` alone.** Aliases added
through Admin → Venues exist *only* in that table, so the config function cannot see them
and will score two rows for the same show as different events.

The three call sites that must agree:

| Path | Resolves venue via |
|---|---|
| the build — `canon_venue()` in `src/main.py` | `venue_lookup`, built from `SELECT name, aliases FROM venues` |
| `scripts/backfill_dedup_key.py` | `_venue_canonical_map()`, same query |
| `scripts/cleanup_duplicates.py` | `build_venue_canon()`, same query |

**Why:** on 2026-08-20 `cleanup_duplicates.py` was the odd one out, using
`normalize_venue_name` only. The 2026-07-15 Lamplighter bill was stored twice — once as
`Lamplighter Lounge`, once as `Lamplighter Lounge, 1702 Madison Ave, Memphis TN`, an alias
the venues table knows and the config does not. The backfill reported **4** collisions while
cleanup found **2**, so cleanup could never clear the last two and the unique index could
never be created. The two scripts simply disagreed about what a duplicate was. Add
`venue_canon` to any new dedup path for the same reason.

**`dedup_key` goes stale whenever normalization changes.** `src/models.normalize_text`,
`config.normalize_venue_name`, and the `venues` aliases all feed it — including a venue
rename. Re-run the backfill after touching any of them (see **Fix duplicates** below).
The daily build partially self-heals: it rebuilds its lookup by *recomputing* every row's
key with current code and refreshes `dedup_key` on any row it matches, so a re-scraped event
repairs itself. Rows nothing re-scrapes stay stale until the backfill runs.

### Security
- API keys stored in: `.zshrc` (local), GitHub Secrets (CI/CD), Render env vars (production)
- `.claude/settings.local.json` contains API keys in permission strings - protected by .gitignore
- Never commit secrets - use `test_before_push.sh` to check
- **`ADMIN_SECRET_KEY` must be set on Render.** Unset, `backend/auth.py` falls back to a
  per-process random key: tokens signed by one worker are rejected by every other and every
  restart silently invalidates all sessions. It warns loudly at startup and reports in
  `GET /health` (a `warnings` array means it is missing) rather than aborting boot — making
  it fatal would take the API down on deploy. **Confirmed set in production 2026-08-20.**
- **Login is throttled** — 10 failures per client per 15 min → 429, counted in process
  memory (a new table would add DDL to the boot path; see the `init_db` lock gotcha).
  Only failures count and success resets, so a legitimate admin retyping is never locked out.
- Passwords are compared as **UTF-8 bytes** — `hmac.compare_digest` raises `TypeError` on a
  non-ASCII `str`, which returned 500 instead of 401.

### File Operations
- **Never have two writers to the same file** - race conditions cause data loss
- Render storage is ephemeral - commit artifacts to GitHub, not /tmp
- GitHub artifacts are auto-cleaned after 24 hours by daily build workflow

### API Patterns
- Admin uses JWT Bearer tokens (cross-origin from Vercel to Render)
- CORS configured for `ALLOWED_ORIGINS` environment variable
- Render health checks hit `/` not `/health` - both endpoints exist
- **Multipart upload routes use `@require_bearer_auth`, not `@require_auth`.** The admin
  cookie is `SameSite=None` so Vercel can reach Render, which means the browser attaches it
  cross-site too — and a `multipart/form-data` POST is a **CORS-simple** request, so it sends
  with no preflight and the write lands even though the response is unreadable. Requiring the
  `Authorization` header forces a preflight that CORS rejects for unknown origins. Transparent
  to the admin UI, which always sends the header via `AdminAPI.apiFetch`.
  Apply it to **any new state-mutating route that reads form data**; routes parsing JSON
  already force a preflight.
- **The Bearer token lives in `sessionStorage`, which is per-tab — the cookie is not.** So a
  page opened in a *new* tab (the Slack bot's reply links go straight to
  `/admin/edit?id=<uuid>`; any middle-click does it too) authenticates fine on the cookie —
  `/api/admin/me` and every `require_auth` route work, the form loads and saves — while all
  four `require_bearer_auth` upload routes answer 401 `Not authenticated`. That tab could not
  recover on its own: `login.html` bounces to `/admin/` whenever the cookie is valid, so there
  was no way to get a token into it short of logging out. Reported 2026-08-20 as "Not
  authenticated" when uploading an event image.
  **Fix:** `GET /api/admin/me` echoes the token it authenticated with (`current_token()` in
  `backend/auth.py` — the *same* token, never a fresh one, so polling cannot extend the 8-hour
  session), and `AdminAPI.apiFetch` calls `hydrateToken()` before any request when
  `sessionStorage` is empty. Echoing it does not weaken the CSRF guard: a cross-site page can
  send that credentialed GET but CORS won't let it read the response, so it still cannot learn
  the token or forge the header.
  A 401 from an upload route now means the session genuinely expired — surface it with
  `uploadFailureMessage(resp, data)` rather than echoing the API's bare "Not authenticated",
  which reads like a page bug.

## Important Files

### Core Application
- `src/main.py` - Orchestrator (fetch → merge → prune → HTML → RSS)
- `src/config.py` - Venues, neighborhoods, keywords, date ranges
- `src/models.py` - `compute_dedup_key` / `normalize_text` — the shared event-identity logic
- `src/normalize.py` - Deduplication logic
- `src/generate_rss.py` - RSS 2.0 feed generator (60-day window)
- `src/date_utils.py` - Date parsing, incl. `resolve_yearless_date` (see below)
- `src/time_format.py` - `strftime_nopad` / `format_event_time` — **use these, never `%-d`/`%-I`**
- `src/http_utils.py` - Shared HTTP fetch helpers
- `backend/app.py` - Flask REST API
- `backend/db.py` - PostgreSQL queries
- `backend/auth.py` - JWT signing, `require_auth` / `require_bearer_auth`, login throttle
- `backend/images.py` - Cloudinary upload/delete + submitted-image sanitization

**Two rules these encode:**
- **A year-less date must go through `resolve_yearless_date`.** Defaulting to the current
  year meant every December build read "Jan 15" as 11 months in the past and the `START_DATE`
  filter silently dropped it — affecting every venue scraper. A date more than 45 days before
  the reference rolls forward, so a slightly stale listing stays put but a New Year date moves.
  `backend/app.py`'s `_normalize_date_iso` shares the same helper.
- **`%-d` / `%-I` are glibc-only** and break local dev on macOS/Windows. Use `strftime_nopad`,
  and `format_event_time` for the "7:30 PM" rendering (previously duplicated at 11 sites).

### Scrapers
- `src/sources/ticketmaster.py` - Ticketmaster Discovery API
- `src/sources/venue_scrapers.py` - Custom scrapers (Hi Tone, Minglewood, etc.)
- `src/sources/artifacts.py` - Claude Vision for image processing

### Frontend (Public Calendar)
- `docs/index.html` - **All-in-one**: CSS + JS + HTML. No separate asset files. Events loaded via API at runtime.
- `docs/thisweek.html` - Static 8-day view, generated by build
- `docs/feed.xml` - RSS 2.0 feed, generated by build

### Event Detail Modal (in docs/index.html)
- Opened by clicking any `[data-event-id]` element (event delegation on `#eventList`)
- `openEventModal(eventId, triggerEl)` / `closeEventModal(method)` — module-scope functions
- `_buildCalendarData(ev)` — builds Google Calendar URL, Outlook.com URL, and Apple .ics Blob
- GA4: fires `modal_open`, `modal_close`, `add_to_calendar`, `external_link_click` via `trackEvent()`
- Visual style matches subscribe modal: `#1A1A1A` card, `border-radius: 12px`, yellow primary CTA

### Admin UI
- `docs/admin/` - Admin interface (Events, Import, Scrapers, Venues, Sponsors tabs)
- `docs/admin/admin-common.js` - Shared admin utilities (auth, API calls)
- All admin pages use `window.__API_BASE` to point to Render backend

### Deployment
- `.github/workflows/daily.yml` - CI/CD (2x daily + manual trigger)
- `backend/gunicorn_conf.py` - Gunicorn config
- `vercel.json` - Vercel config
- `scripts/schema.sql` - PostgreSQL schema

### Feeds
- `docs/feed.xml` - RSS 2.0 feed (next 60 days, auto-generated each build)
- Feed URL: `concert-calendar.wyxr.org/feed.xml`
- **Badge flags are machine-readable, not just text.** WYXR Pick / WYXR Presents ship as
  `<category>` plus a `wyxr:` namespaced trio (`<wyxr:pick>`, `<wyxr:presents>`,
  `<wyxr:badge>`) on every event item — see the RSS Feed section of README.md for the
  contract. The badge words are *also* still inside `<title>`/`<description>`/
  `<content:encoded>` for older consumers; keep both in sync if you touch the labels
  (`BADGE_PICK` / `BADGE_PRESENTS` in `src/generate_rss.py` are the single source).
  The two booleans are independent — an event can be both — and `<wyxr:badge>` applies the
  Presents-wins precedence for consumers that can only show one.

## Venues (27 configured)

Source of truth is `VENUES` in `src/config.py`; each entry's `scraper` field selects the
fetcher. Regenerate this list with:
`python3 -c "import sys;sys.path.insert(0,'.');from src.config import VENUES;print(len(VENUES))"`

**Ticketmaster by venue ID (7)** — `ticketmaster_venue`: BankPlus Amphitheater at Snowden
Grove, Bluesville at Horseshoe, Cannon Center, FedExForum, Grind City Amphitheater, Radians
Amphitheater, Satellite Music Hall

**Custom scrapers (17):** Hi Tone, Minglewood Hall, Hernando's Hideaway, Growlers
(SeeTickets), Graceland Soundstage (Wix), Lafayette's Music Room + Nashoba (Elfsight),
Crosstown Arts, Crosstown Brewing Co., Flyway Brewing (Wix), Huey's (`sitewrench`, all
locations), Overton Park Shell (Squarespace), B.B. King's (Webflow), Blues City Cafe,
Landers Center, Orpheum Theatre, South Main Sounds

**Generic scraper (1)** — JSON-LD: Germantown Performing Arts Center

**Manual only (2):** Bar DKDC, B-Side Memphis

Venue scrapers use 6-month range (`SCRAPER_END_DATE`) for interactive calendar.

> The DB `venues` table is much larger (~104) — it also holds venues created by Slack/artifact
> uploads and admin entries, which have aliases but no scraper. Those aliases are load-bearing
> for deduplication (see **Deduplication**).

`ticketmaster_venue` is the cheap win for any Live Nation / Ticketmaster room: a
`livenation.com/venue/<ID>/…` URL exposes the ID — add a `VENUES` entry plus a
`backend/db.py` `_SEED_VENUES` row, and no page scraping is needed at all.

## Slack Image Upload Pipeline

DJs can upload venue schedule images directly to **#wyxr-concert-calendar** in Slack to add events without touching the admin UI.

### How it works
1. User uploads an image to #wyxr-concert-calendar with the caption **"add to calendar"**,
   optionally naming the venue: **"add to calendar B-Side"**
2. Slack fires a `file_shared` event to `POST /api/slack/events`
3. Backend downloads the image, checks the caption via `conversations.history`
4. Claude Vision (`claude-sonnet-4-6`) extracts events from the image
5. The venue is resolved (see **Venue resolution** below)
6. New events are deduplicated and inserted into PostgreSQL. The uploaded image is attached
   **only when every extracted event is the same show** — same canonical venue, same date.
   A 4-act bill on one night gets the flyer; a venue's month schedule does not (it would
   thumbnail the whole flyer onto every row). Venue is canonicalized via
   `normalize_venue_from_db` first, so "Lamplighter Lounge, Memphis, TN" groups with
   "Lamplighter Lounge".
7. GitHub Actions rebuild is triggered
8. Bot replies in the channel listing each added event, with the title linked to
   `{SITE_BASE}/admin/edit?id=<uuid>` for one-click correction

The reply counts and lists only events that **actually inserted** — `bulk_insert_events`
uses `ON CONFLICT DO NOTHING`, so a row that collides returns nothing and is skipped.
`SITE_BASE_URL` overrides the site origin (defaults to `https://concert-calendar.wyxr.org`).

### Venue resolution

A venue's own monthly schedule usually never prints the venue name on it — B-Side's August
flyer is just "AUGUST" over their logo. Vision has nothing to read, so it used to return
"Unknown Venue" and 40 shows landed on the public calendar under that string (2026-08-04).

- **Caption wins.** `_venue_hint_from_caption()` reads whatever follows "add to calendar"
  and resolves it strictly against the DB `venues` table (names + aliases), trimming
  trailing words one at a time so "add to calendar b-side thanks!" still matches. When it
  resolves, that venue is applied to **every** event from the image — one flyer is one
  venue. Nothing in the caption matching a known venue → no hint (chatter can't invent a
  venue).
- **Placeholders never insert.** `_is_placeholder_venue()` catches "Unknown Venue",
  "Venue TBA", "TBA/TBD", "N/A", empty, etc. Those events are dropped and the reply tells
  the DJ to re-upload with the venue in the caption. Applied **before** the
  `is_fuzzy_duplicate` check, which keys off venue.
- The Vision prompt also asks for an empty venue rather than a guessed placeholder.
- **Recovery for rows already inserted under a wrong venue:**
  `python scripts/reassign_venue.py --from "Unknown Venue" --to "B-Side Memphis"`
  (dry-run by default, `--confirm` to write). It sets neighborhood from the venues table,
  recomputes `dedup_key`, and skips any row that would collide with an existing event.
  Don't use Admin → Venues **merge** for this — merge adds the bad string as a permanent
  alias, which would silently route every future venue-less flyer to that venue.

### Environment variables (Render)
| Variable | Source |
|---|---|
| `SLACK_BOT_TOKEN` | api.slack.com → OAuth & Permissions → Bot User OAuth Token |
| `SLACK_SIGNING_SECRET` | api.slack.com → Basic Information → Signing Secret |
| `SLACK_CHANNEL_ID` | Right-click channel in Slack → View channel details → Channel ID |

### Slack app config (api.slack.com)
- **OAuth scopes:** `files:read`, `chat:write`, `channels:history`
- **Event Subscriptions → Request URL:** `https://concert-calendar-api.onrender.com/api/slack/events`
- **Subscribe to bot events:** `file_shared`
- Bot must be invited to the channel: `/invite @WYXR Concert Calendar`

### Key implementation files
- `backend/app.py` — `slack_events()` route, `_process_slack_image()` background thread
- `src/sources/artifacts.py` — `extract_events_from_image_bytes()` public entry point

### Debugging
- All Slack activity logs with `[slack]` prefix in Render logs
- If no `[slack]` lines appear after upload: bot not in channel, wrong event subscription, or needs reinstall
- If "No events extracted": check Vision response in logs — year assumption issues are common for handwritten schedules with no year shown (prompt instructs Claude to assume current/next year)
- Reinstall app after any scope changes: api.slack.com → OAuth & Permissions → Reinstall to WYXR

## Image Hosting (Cloudinary)

All **uploaded** images — admin event images, sponsor images, calendar sponsor images, and
Slack-pipeline images — are hosted on Cloudinary. `backend/images.py` is the only place that
writes them.

```python
upload_image(file_data, orig_filename, folder) -> str | None   # folder: "event-images" | "sponsors"
delete_image(image_url) -> bool
is_cloudinary_url(url) -> bool
```

- **Config:** `CLOUDINARY_URL` (`cloudinary://<key>:<secret>@wyxr`) — the SDK reads it
  automatically. Optional `CLOUDINARY_FOLDER_PREFIX` (default `concert-calendar`; set to
  `concert-calendar-dev` locally so test uploads stay out of the production folder).
- **Limits:** 10 MB max, extensions `.jpg .jpeg .png .webp .gif`. Enforced in `validate()`.
- **Error contract:** `ImageUploadError` → HTTP 400 (bad/oversized/corrupt file); `None`
  return → HTTP 502 (network or provider failure). The Slack path catches `ImageUploadError`
  and continues without an image — a bad image must never block event insertion.
- **Deletes actually delete.** The CDN edge may serve a cached copy for a few minutes after
  `delete_image()`; the Admin API is authoritative, not a browser request to the URL.

**Legacy images stay on the repo.** Files already under `docs/event-images/` and
`docs/sponsors/` are still served by Vercel and were deliberately not migrated. Both URL
shapes coexist, so **never assume `image_url` is a Cloudinary URL** — use
`is_cloudinary_url()` to branch.

`cldImg()` in `docs/index.html` must handle three URL shapes. Getting this wrong is the main
regression risk in this area:
| Source | Handling |
|---|---|
| `res.cloudinary.com/…/image/upload/…` (new uploads) | splice the transformation into the delivery path — **never** fetch-wrap. A nested URL still returns 200, so this fails silently; the cost is that each one bills as a separate derived asset |
| `concert-calendar.wyxr.org/…` (legacy) and remote scraper images | `/image/fetch/` wrapped, as before |
| relative paths | passed through untouched |

`artifacts/` is **not** on Cloudinary — it's a build input read off disk during GitHub
Actions, so `admin_import_upload()` still commits it to the repo via the Contents API.

### Public submit-form images

`/submit` accepts an optional flyer. **Anonymous uploads never reach Cloudinary** — that is
the design constraint, not an implementation detail. Bytes are held in
`submissions.image_data` (BYTEA) and only uploaded when an admin approves, so the free-tier
quota is spent solely on images someone chose to publish.

- **Browser downscales first** — canvas to 1600px max edge, JPEG q0.82. A 12 MB phone photo
  becomes a few hundred KB, so submitters never hit a size wall, and EXIF/GPS is dropped.
- **Server re-encodes anyway** — `sanitize_submitted_image()` in `backend/images.py` decodes
  with Pillow and writes fresh JPEG bytes. Never store what was submitted: a file can carry
  a valid image header and be something else. Cap is 3 MB (`MAX_SUBMISSION_IMAGE_BYTES`),
  tighter than the 10 MB admin cap because this path is unauthenticated.
- **Rate limit:** 5 submissions/hour per hashed IP (`SUBMISSIONS_PER_HOUR`). Keyed on the
  leftmost `X-Forwarded-For` entry — `request.remote_addr` is Render's proxy, so using it
  would put every submitter in one bucket. IP is stored as a salted SHA-256
  (`SUBMISSION_IP_SALT`), never in the clear.
- **Rights checkbox** is required when a file is attached, recorded in
  `image_rights_confirmed`.
- **Bytes are freed** on approve (after upload), on reject, and by a 90-day sweep
  (`purge_stale_submission_images()`) at the start of the daily build.

⚠️ `image_data` must never reach `jsonify` — psycopg2 returns it as a `memoryview` and
`serialize_event()` doesn't convert it, which would break the whole admin Submissions tab.
All submission queries select `_SUBMISSION_COLUMNS` (which exposes a derived `has_image`
boolean instead); the bytes come back only from `get_submission_image()`.

## Sponsor System

### Sponsor Callouts
Inline promotional cards that appear between day sections in the calendar and RSS feed. Managed in the Admin → Sponsors tab → "Sponsor Callouts" section.
- DB table: `sponsors` (name, image_url, link_url, display_after_date, start_date, end_date, is_active)
- Public API: `GET /api/sponsors`
- Admin API: `GET/POST /api/admin/sponsors`, `PUT/DELETE /api/admin/sponsors/<id>`, `POST /api/admin/sponsors/upload-image`

### Calendar Sponsor
A single featured sponsor banner shown above the event list (below the filter bar). One active sponsor per date range — POST returns 409 on overlap.
- DB table: `calendar_sponsor` (name, image_url, link_url, copy_line, start_date, end_date, is_active)
- Recommended image size: **600 × 120px** (5:1 horizontal). Any aspect ratio works — image displays at natural proportions, max-width 600px.
- Public API: `GET /api/calendar-sponsor` — returns single object or `{}`
- Admin API: `GET/POST /api/admin/calendar-sponsor`, `PUT/DELETE /api/admin/calendar-sponsor/<id>`, `POST /api/admin/calendar-sponsor/upload-image`
- Managed in Admin → Sponsors tab → "Calendar Sponsor" section (top of tab)
- **Image upload timing:** Uploads go to Cloudinary and the returned URL resolves immediately — no commit, no Vercel redeploy, no wait. (Before July 2026 these were committed to `docs/sponsors/` and took ~1 min to go live.)

### Subscribe Modal
Email signup (Mailchimp) was previously a full yellow banner. Now a compact "📧 Subscribe" button in the header opens a dark modal. Same Mailchimp iframe form + sessionStorage success state (`wyxr_signup_banner_success`). If already subscribed, button shows "✓ Subscribed" (disabled).

## GA4 Analytics

Measurement ID: **`G-9866JXK4ND`** (loaded via gtag.js in `<head>` of `docs/index.html`).

All tracking calls go through a single helper in the page script:
```javascript
function trackEvent(name, params) {
    if (typeof gtag === 'function') gtag('event', name, params);
}
```
The `typeof gtag` guard prevents errors in local dev where the gtag script isn't loaded.

### Custom Events & Parameters

| Event name | Parameters | Fired when |
|---|---|---|
| `modal_open` | `event_id`, `event_title`, `venue`, `event_date` (YYYY-MM-DD), `has_ticket_url` (bool) | User opens an event detail modal |
| `modal_close` | `event_id`, `close_method` ("x" / "esc" / "overlay") | User closes the modal |
| `add_to_calendar` | `event_id`, `event_title`, `service` ("google" / "apple" / "outlook") | User clicks a calendar button |
| `external_link_click` | `event_id`, `event_title`, `destination_url` | User clicks "Buy Tickets" |

### GA4 Custom Dimensions (must be registered in GA4 Admin)

These parameters are sent correctly by the code but are only visible in GA4 reports after being registered as **Event-scoped Custom Dimensions** in GA4 Admin → Data display → Custom definitions.

| Dimension name | Event parameter | Used in |
|---|---|---|
| Event Title | `event_title` | `modal_open`, `add_to_calendar`, `external_link_click` |
| Venue | `venue` | `modal_open` |
| Event Date | `event_date` | `modal_open` |
| Has Ticket URL | `has_ticket_url` | `modal_open` |
| Close Method | `close_method` | `modal_close` |
| Calendar Service | `service` | `add_to_calendar` |
| Destination URL | `destination_url` | `external_link_click` |

**Note:** The dropdown in GA4 Admin only shows parameters it has already indexed (24–48 hr delay). Type the parameter name directly into the field — it accepts free text even if not in the autocomplete list.

### Verified behaviour (tested 2026-04-24)
- All 38 distinct `start_time` formats in production parse correctly (0 failures), including narrow no-break space variants (`10:00 PM`) and range formats (`6:30 PM - 8:30 PM` → uses start time)
- `event_title`, `venue`, and `event_date` are always populated (every event in the DB has these fields)
- `has_ticket_url` is `true` for ~51% of events (74/144 in current dataset)

## Common Tasks

### Add a new venue
1. Add to `VENUES` in `src/config.py`
2. Choose scraper type (generic, custom, or manual_only)
3. Seed venue in `backend/db.py` → `_seed_venues_if_empty()`
4. Test with `python -m src.main --dry-run`

### Fix duplicates

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
  them, which historically meant the two scripts disagreed about venue canonicalization
  (see **Deduplication** above).
- Before deleting, check that each doomed row holds no field its survivor lacks —
  `detail_score()` breaks ties arbitrarily when scores are equal.
- Re-run steps 3–5 after any change to `normalize_text`, `normalize_venue_name`, or venue
  aliases — including a venue rename, which leaves every one of that venue's keys stale.
- ⚠️ Never run a bulk DB edit while a build is in flight — check `gh run list` first
  (see the *Build reverts edits made while it runs* gotcha).

### Trigger build manually
- GitHub Actions: Actions tab → Daily Concert Calendar Update → Run workflow
- Admin UI: Tools tab → Trigger Build button

### Test before pushing
```bash
./test_before_push.sh
# If passed:
git push origin main
```

`test_before_push.sh` runs **13 checks**: env vars, dependencies, DB connection, exposed-key
scan, Python syntax, git status, and six regression suites. There is no test framework —
each suite is a standalone script following the `scripts/test_*.py` convention, offline
except for the DB connection check.

| Suite | Covers |
|---|---|
| `scripts/test_health_check.py` | nightly health-check report parsing |
| `scripts/test_normalization.py` | year rollover, title/venue normalization, strftime |
| `scripts/test_admin_auth.py` | CSRF guard, login throttle, non-ASCII password (no DB needed) |
| `scripts/test_escaping.mjs` | `escAttr`/`safeUrl` vs attack payloads |
| `scripts/test_ticketmaster_pagination.py` | paging, 1000-item ceiling, non-terminating API |
| `scripts/test_xss_browser.py` | the real page in Chromium against live payloads |

- `test_escaping.mjs` **extracts the helper sources from the shipped files** rather than
  copying them, so it fails if the implementation regresses, and it asserts no attribute
  site reverts to `esc()`.
- `test_xss_browser.py` needs Chromium (`pip3 install playwright && python3 -m playwright
  install chromium`). It **skips cleanly when absent** — so a green run can hide it. Check
  for `13/13`, not just "all checks passed": a skip shows as `11/11`. Override discovery
  with `CHROME_PATH` if needed.

## Debugging Tips

### Backend won't start
- Check `DATABASE_URL` format (must be single line, no breaks)
- Verify port 5001 isn't in use: `lsof -i :5001`
- Test DB connection: `python -c "from backend.db import init_db; init_db()"`

### Frontend can't connect
- Check CORS settings in `backend/app.py` - should include `localhost:8000`
- Open browser console (Cmd+Option+I) for CORS errors

### Duplicates appearing
- Check `_save_events_to_db()` updates `db_key_to_row` after inserts
- Run `python scripts/cleanup_duplicates.py` to remove existing

### Scraper failing
- Check scraper logs in admin UI (Tools tab)
- Test individual scrapers: `python -c "from src.sources import ticketmaster; print(ticketmaster.fetch())"`

### Transient Postgres connection timeouts
Anything reaching the Render database **over the internet** — the local backend (`.env`
holds the external `DATABASE_URL`) and the GitHub Actions build — hits occasional
`psycopg2.OperationalError: ... timeout expired`. It is latency, not a defect.

- Locally it surfaces as a **500 on whatever admin endpoint happened to fire**; the same
  request succeeds on retry.
- In CI the build logs `[scrape_log] Could not create log entry: ... timeout expired` and
  continues correctly — so **a build with no `scrape_logs` row is not a failed build**.
  Confirm against the run's own log (`Saved to PostgreSQL: N added, …`) before investigating.

Retry 2–3 times and grep for `OperationalError` before chasing it as a bug.

## Workflow Preferences

- Always commit and push to remote after completing work
- Test locally before pushing (use `test_before_push.sh`)
- Use descriptive commit messages
- Include "Co-Authored-By: Claude" in commits when appropriate

## Environment

- Python 3.12 via Homebrew (not conda)
- pip install with `--break-system-packages` on macOS
- Current date for context: Check system for latest

## Cost

- **Render:** Starter plan ($7/month) - no cold starts
- **Vercel:** Free tier
- **GitHub Actions:** Free
- **Ticketmaster API:** Free
- **Anthropic API:** ~$0.01 per image processed

## Deployment

- After making changes, always commit, push, and deploy without waiting to be asked. Confirm the deployment is live by checking the production URL.

## Debugging

- When debugging image or asset display issues, always check: 
	1) URL encoding (spaces, special chars)
	2) CDN/Vercel caching of 404s
	3) aspect ratio constraints. 
Never assume a fix worked without verifying the live URL.

## External APIs

- When working with external APIs (Qgiv, Mailchimp, Twilio, etc.), always verify the exact request format (form-encoded vs JSON), correct base URLs/subdomains, and required credentials before making the first call.

## Session Start

- When resuming work from a previous session, read recent git log and open TODO/backlog files to understand what's unfinished before asking the user.

## License

Internal tool for WYXR 91.7 FM. Built in Memphis. 🎸
