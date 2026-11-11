# Local Development Guide

This guide shows you how to run and test the entire Concert Calendar application locally before pushing changes to the remote main branch.

## Front-end only (no setup)

If you are only changing the public calendar (`docs/index.html`), you need no `.env`, no
backend and no admin login:

```bash
./run_local_frontend.sh
open http://localhost:8000/
```

Edit `docs/index.html` and refresh — there is no build step. The page reads its events from
the **production** API (the URL is hardcoded as `API_BASE` in `docs/index.html`), so you see
live data, read-only. Read [`dev/frontend.md`](dev/frontend.md) before pushing.

## Quick Start (full stack)

```bash
# 1. Set up environment variables
cp .env.example .env
# Edit .env with your credentials

# 2. Start the backend (in one terminal)
chmod +x run_local_backend.sh
./run_local_backend.sh

# 3. Start the frontend (in another terminal)
chmod +x run_local_frontend.sh
./run_local_frontend.sh

# 4. Open in browser
open http://localhost:8000/admin/local.html
```

> **`local.html` is not in a fresh clone.** `docs/admin/local.html`, `docs/admin/local_index.html`
> and `docs/local_index_home.html` are gitignored, so they exist only on machines where someone
> created them. Ask a maintainer for copies. Without them, every page in the clone talks to the
> production API, not your local backend.

## Setup Details

### 1. Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required variables:
- `DATABASE_URL` - Use the **external** PostgreSQL URL from Render (for local dev)
- `ADMIN_PASSWORD` - Same as production
- `ADMIN_SECRET_KEY` - Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`
- `TICKETMASTER_API_KEY` - From your Ticketmaster developer account
- `ANTHROPIC_API_KEY` - From your Anthropic account (for artifact processing)
- `GITHUB_PAT` - Fine-grained token with `contents:write` for this repo
- `CLOUDINARY_URL` - `cloudinary://<key>:<secret>@wyxr`, from Cloudinary console → Settings → API Keys. Needed for any image upload (admin event images, sponsors, Slack pipeline); without it those endpoints return 502.
- `SUBMISSION_IP_SALT` - Any random string; salts the hashed submitter IPs used to rate-limit the public submit form. Falls back to `ADMIN_SECRET_KEY` if unset.
- `CLOUDINARY_FOLDER_PREFIX` - Set to `concert-calendar-dev` locally. **Do this** — it keeps test uploads out of the production folder, which shares the same Cloudinary account and free-tier quota.

> **Note:** You can use the production Render database for local testing, or set up a local PostgreSQL instance if you prefer complete isolation.

### 2. Install Dependencies

Backend dependencies:
```bash
pip3 install -r backend/requirements.txt --break-system-packages
```

Main script dependencies:
```bash
pip3 install -r requirements.txt --break-system-packages
```

### 3. Running the Backend

The backend Flask API runs on port 5001 (5000 is often taken by macOS AirPlay):

```bash
./run_local_backend.sh
```

This will:
- Load environment variables from `.env`
- Verify required variables are set
- Install dependencies if needed
- Start Flask at `http://localhost:5001`

**API endpoints:**
- `http://localhost:5001/api/events` - Public events
- `http://localhost:5001/api/admin/login` - Admin login
- `http://localhost:5001/api/admin/events` - Admin event management
- `http://localhost:5001/health` - Health check

### 4. Running the Frontend

The frontend serves static files on port 8000:

```bash
./run_local_frontend.sh
```

This uses Python's built-in HTTP server to serve the `docs/` directory.

**Pages:**
- `http://localhost:8000/` - Homepage (interactive calendar; loads **production** data)
- `http://localhost:8000/local_index_home.html` - Homepage against your local backend (gitignored, see above)
- `http://localhost:8000/thisweek.html` - Static "This Week" page
- `http://localhost:8000/feed.xml` - RSS 2.0 feed (next 60 days of events)
- `http://localhost:8000/picks.xml` - WYXR Picks RSS feed (next 180 days, Pick-flagged only)
- `http://localhost:8000/admin/local.html` - **Local admin login** (points to localhost:5001; gitignored, see above)
- `http://localhost:8000/admin/login.html` - Production admin login (points to Render — a login here is a **production** login)

> **Important:** Use `local.html` for local development. It's configured to connect to your local backend at `http://localhost:5001`.
>
> The local server does not strip `.html` the way Vercel's `cleanUrls` does, so `/admin/login`
> is a 404 here — include the extension.

### 5. Testing the Admin UI

1. Start both backend and frontend
2. Open http://localhost:8000/admin/local.html
3. Log in with your `ADMIN_PASSWORD`
4. You can now:
   - View/edit/add events
   - Upload artifacts (images commit to GitHub)
   - Check scraper status
   - Manage venues

**Note:** When logged in through `local.html`, other admin pages will still use the production backend URL. To test all admin pages locally, you'll need to update the `window.__API_BASE` in each HTML file to `http://localhost:5001`.

## Testing the Scraper

Run the main scraper script locally:

```bash
# Dry run (no writes to DB or files)
python3 -m src.main --dry-run

# Full run (writes to DB and generates HTML)
python3 -m src.main

# Test specific sources
python3 -c "from src.sources import ticketmaster; print(ticketmaster.fetch())"
```

## Database Options

### Option A: Use Production Database (Recommended for Quick Testing)

Use the Render **external** database URL in your `.env`:
```bash
export DATABASE_URL="postgresql://user:pass@xxx.oregon-postgres.render.com/dbname"
```

**Pros:**
- No local setup needed
- Test against real data
- See changes immediately in production (after refresh)

**Cons:**
- Changes affect production (be careful!)
- Requires internet connection

### Option B: Local PostgreSQL (Full Isolation)

For complete isolation, run PostgreSQL locally:

```bash
# Install PostgreSQL
brew install postgresql@14
brew services start postgresql@14

# Create database
createdb concert_calendar_dev

# Run schema
psql concert_calendar_dev < scripts/schema.sql

# Update .env
export DATABASE_URL="postgresql://localhost/concert_calendar_dev"
```

## Pre-Push Checklist

Before pushing changes to main, verify:

- [ ] Backend starts without errors: `./run_local_backend.sh`
- [ ] Frontend serves correctly: `./run_local_frontend.sh`
- [ ] Admin login works: http://localhost:8000/admin/local.html
- [ ] API endpoints return valid JSON: `curl http://localhost:5001/api/events`
- [ ] Scraper runs without errors: `python3 -m src.main --dry-run`
- [ ] Tests pass: `./test_before_push.sh` (expect `24/24`; see [`dev/testing.md`](dev/testing.md) — it is not read-only against the `.env` database)
- [ ] No API keys committed: `git grep -i "api_key" src/ backend/`

## Troubleshooting

### Backend won't start

```bash
# Check if port 5001 is already in use
lsof -i :5001

# Check DATABASE_URL format (must be single line, no line breaks)
echo $DATABASE_URL

# Verify psycopg2 is installed
python3 -c "import psycopg2; print('OK')"
```

### Frontend can't connect to backend

```bash
# Check CORS settings in backend/app.py
# ALLOWED_ORIGINS should include http://localhost:8000

# Check browser console for CORS errors
# Open DevTools (Cmd+Option+I) -> Console tab
```

### Database connection fails

```bash
# Test connection directly
python3 -c "from backend.db import init_db; init_db(); print('Connected!')"

# Verify DATABASE_URL is external URL (not internal)
# Internal: @host.render.com (only works on Render)
# External: @xxx.oregon-postgres.render.com (works everywhere)
```

### "Module not found" errors

```bash
# Reinstall dependencies
pip3 install -r requirements.txt --break-system-packages
pip3 install -r backend/requirements.txt --break-system-packages

# Check Python version (should be 3.12)
python3 --version
```

## Git Workflow

1. Make changes locally
2. Test with local backend + frontend
3. Commit when working:
   ```bash
   git add .
   git commit -m "Description of changes"
   ```
4. Push to trigger CI/CD:
   ```bash
   git push origin main
   ```

GitHub Actions will run the scraper and deploy to Vercel automatically.

## Additional Resources

- `README.md` - Full project overview
- `IMPLEMENTATION_LOG.md` - Detailed setup and architecture notes
- `backend/app.py:6` - Flask run command for reference
- `.github/workflows/daily.yml` - CI/CD configuration
