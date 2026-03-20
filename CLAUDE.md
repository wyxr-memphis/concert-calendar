# Claude Code Instructions

This document provides context for AI assistants working on the Memphis Concert Calendar project.

## Project Overview

A daily-updating live music calendar for Memphis, Tennessee, built for WYXR 91.7 FM DJs.

**Architecture:**
- **Frontend:** Vercel at `concert-calendar.wyxr.org` (static HTML + interactive JS)
- **Backend API:** Flask on Render at `concert-calendar-api.onrender.com`
- **Database:** PostgreSQL on Render (single source of truth)
- **Build:** GitHub Actions 2x daily (midnight + noon Central)

## Key Technologies

- **Backend:** Python 3.12, Flask, PostgreSQL (psycopg2)
- **Frontend:** Vanilla JavaScript (no framework)
- **Deployment:** Render (backend), Vercel (frontend), GitHub Actions (CI/CD)
- **Data Sources:** Ticketmaster API, venue scrapers, Claude Vision API (for image artifacts)

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

### Deduplication
- Events are deduplicated during scraper runs using normalized keys (title|venue|date)
- `_save_events_to_db()` tracks inserted events within same batch to prevent duplicates
- **Never overwrite admin/manual source entries** - automated scrapers always defer to manual edits

### Security
- API keys stored in: `.zshrc` (local), GitHub Secrets (CI/CD), Render env vars (production)
- `.claude/settings.local.json` contains API keys in permission strings - protected by .gitignore
- Never commit secrets - use `test_before_push.sh` to check

### File Operations
- **Never have two writers to the same file** - race conditions cause data loss
- Render storage is ephemeral - commit artifacts to GitHub, not /tmp
- GitHub artifacts are auto-cleaned after 24 hours by daily build workflow

### API Patterns
- Admin uses JWT Bearer tokens (cross-origin from Vercel to Render)
- CORS configured for `ALLOWED_ORIGINS` environment variable
- Render health checks hit `/` not `/health` - both endpoints exist

## Important Files

### Core Application
- `src/main.py` - Orchestrator (fetch → merge → prune → HTML → RSS)
- `src/config.py` - Venues, neighborhoods, keywords, date ranges
- `src/normalize.py` - Deduplication logic
- `src/generate_rss.py` - RSS 2.0 feed generator (60-day window)
- `backend/app.py` - Flask REST API
- `backend/db.py` - PostgreSQL queries

### Scrapers
- `src/sources/ticketmaster.py` - Ticketmaster Discovery API
- `src/sources/venue_scrapers.py` - Custom scrapers (Hi Tone, Minglewood, etc.)
- `src/sources/artifacts.py` - Claude Vision for image processing

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

## Venues (15 total)

**Custom scrapers (7):** Hi Tone, Minglewood Hall, Hernando's Hideaway, Growlers (SeeTickets), Graceland (Wix), Lafayette's Music Room (Elfsight), Nashoba (Elfsight)

**Generic scraper (4):** Crosstown Arts, Overton Park Shell, FedExForum, Germantown PAC

**Manual only (4):** B.B. King's, Orpheum, Bar DKDC, B-Side Memphis

Venue scrapers use 6-month range (`SCRAPER_END_DATE`) for interactive calendar.

## Slack Image Upload Pipeline

DJs can upload venue schedule images directly to **#wyxr-concert-calendar** in Slack to add events without touching the admin UI.

### How it works
1. User uploads an image to #wyxr-concert-calendar with the caption **"add to calendar"**
2. Slack fires a `file_shared` event to `POST /api/slack/events`
3. Backend downloads the image, checks the caption via `conversations.history`
4. Claude Vision (`claude-sonnet-4-6`) extracts events from the image
5. New events are deduplicated and inserted into PostgreSQL
6. GitHub Actions rebuild is triggered
7. Bot replies in the channel with a list of added events

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
- **Image upload timing:** Image commits to `docs/sponsors/` via GitHub Contents API → Vercel redeploys (~1 min). Preview in modal uses local blob URL immediately; CDN URL goes live after deploy.

### Subscribe Modal
Email signup (Mailchimp) was previously a full yellow banner. Now a compact "📧 Subscribe" button in the header opens a dark modal. Same Mailchimp iframe form + sessionStorage success state (`wyxr_signup_banner_success`). If already subscribed, button shows "✓ Subscribed" (disabled).

## Common Tasks

### Add a new venue
1. Add to `VENUES` in `src/config.py`
2. Choose scraper type (generic, custom, or manual_only)
3. Seed venue in `backend/db.py` → `_seed_venues_if_empty()`
4. Test with `python -m src.main --dry-run`

### Fix duplicates
```bash
# Preview
python scripts/cleanup_duplicates.py

# Actually delete
python scripts/cleanup_duplicates.py --confirm
```

### Trigger build manually
- GitHub Actions: Actions tab → Daily Concert Calendar Update → Run workflow
- Admin UI: Tools tab → Trigger Build button

### Test before pushing
```bash
./test_before_push.sh
# If passed:
git push origin main
```

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

## License

Internal tool for WYXR 91.7 FM. Built in Memphis. 🎸
