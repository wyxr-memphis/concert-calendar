# Claude Code Instructions

Context for AI assistants working on the Memphis Concert Calendar — a daily-updating live
music calendar for Memphis, Tennessee, built for WYXR 91.7 FM DJs.

**This file holds only what you need loaded on every turn: the tripwires, the file map, and
the working preferences.** The reasoning and history behind each rule live in `dev/`.
**Read the relevant `dev/` doc before working on that subsystem** — every rule below was
learned from a real outage or bug, and the doc says which one.

## Architecture

- **Frontend:** Vercel at `concert-calendar.wyxr.org` (static HTML + interactive JS)
- **Backend API:** Flask on Render at `concert-calendar-api.onrender.com`
- **Database:** PostgreSQL on Render (**single source of truth**)
- **Build:** GitHub Actions 2x daily (midnight + noon Central)

`data/events.json` is a read-only snapshot exported by builds, never an input.

## Deep-dive docs (`dev/` — outside `docs/`, so not published)

| Doc | Read before touching |
|---|---|
| [`dev/frontend.md`](dev/frontend.md) | `docs/index.html` — escaping, modal, deep links |
| [`dev/database.md`](dev/database.md) | schema/DDL, dedup, dates & times, DB debugging |
| [`dev/security.md`](dev/security.md) | auth, CSP, upload validation, audit log, API keys |
| [`dev/feeds-and-seo.md`](dev/feeds-and-seo.md) | RSS, picks, ICS, sitemap, `/e/<id>`, JSON-LD |
| [`dev/venues-and-scrapers.md`](dev/venues-and-scrapers.md) | adding a venue, scraper types |
| [`dev/slack-pipeline.md`](dev/slack-pipeline.md) | the Slack image-upload flow |
| [`dev/images.md`](dev/images.md) | Cloudinary, `cldImg()`, public submit uploads |
| [`dev/sponsors-and-analytics.md`](dev/sponsors-and-analytics.md) | sponsors, subscribe modal, GA4 |
| [`dev/testing.md`](dev/testing.md) | `test_before_push.sh` and its suites |
| [`dev/instagram-dead-end.md`](dev/instagram-dead-end.md) | ⛔ read before any Instagram ingestion idea |
| [`dev/test-plan.md`](dev/test-plan.md) | 79 adversarial cases — a reference catalogue, not a checklist |

Also: [`LOCAL_DEVELOPMENT.md`](LOCAL_DEVELOPMENT.md) for setup, [`FEATURES.md`](FEATURES.md)
for live work, [`REVIEW.md`](REVIEW.md) for the August 2026 codebase review — most of its
findings are fixed and its line numbers have moved. Its one still-live design is the
venue-by-venue scraper approach (§5); **§6's Instagram ingestion is abandoned, not pending**
— see [`dev/instagram-dead-end.md`](dev/instagram-dead-end.md) before acting on it.

---

## Tripwires

Break one of these and you ship a bug that will not show up in review. Each links to the
doc that explains why.

### Frontend — `docs/index.html` → [`dev/frontend.md`](dev/frontend.md)

The page is **fully self-contained**: one `<style>` block, one `<script>` block, no build
step, no bundler. Admin pages have separate JS under `docs/admin/`.

- **Three escaping helpers; picking the wrong one is a live XSS bug.** `esc()` for text
  between tags only (it leaves quotes intact). `escAttr()` for anything in a quoted
  attribute. `safeUrl()` for anything reaching `href`/`src` (escaping does not stop
  `javascript:`). Compose them: `escAttr(safeUrl(cldImg(ev.image_url, 600)))`.
- **Never strip markup with the detached-`innerHTML` idiom** — the parser still builds the
  nodes, so `<img src=x onerror=…>` fires. Use `DOMParser`.
- ⚠️ **Never write a literal `</script>` inside the inline script** — not even in a comment.
  It closes the script element and takes the whole page's JS with it. All three JSON-LD
  emitters unicode-escape `<`/`>`/`&` for the same reason.

### Database → [`dev/database.md`](dev/database.md)

- **Schema DDL must never run unguarded on boot.** New DDL in `_run_migrations()` must use
  `_ddl_cursor()` **and** register in the fast path (`_SCHEMA_TABLES` / `_SCHEMA_COLUMNS`),
  or it is silently skipped forever. An unguarded `CREATE TABLE` took the whole API down on
  2026-07-29.
- **psycopg2 transaction poisoning** — one caught exception poisons the block. Use a
  separate `with get_cursor()` per operation.
- **Every "same event?" path must canonicalize the venue through the DB `venues` table**
  (names + aliases), not `config.normalize_venue_name` alone. Three call sites must agree:
  `src/main.py` `canon_venue()`, `scripts/backfill_dedup_key.py`, `scripts/cleanup_duplicates.py`.
- **`dedup_key` goes stale whenever normalization changes** — including a venue rename.
  Re-run the backfill (runbook in the doc).
- ⚠️ **Never run a bulk DB edit while a build is in flight** — check `gh run list` first.
  The build writes back stale rows and reverts your edits.
- **Never write directly to `data/events.json`** and **never overwrite admin/manual source
  entries** — automated scrapers always defer to manual edits.
- **`gunicorn preload_app=True`** is load-bearing; the root `/` route is what Render health-
  checks hit.

### Dates and times → [`dev/database.md`](dev/database.md#date-and-time-rules)

- **A year-less date must go through `resolve_yearless_date`** — otherwise every December
  build drops January shows.
- **`%-d` / `%-I` are glibc-only.** Use `strftime_nopad` / `format_event_time`.
- **`start_time` is parsed in exactly one place:** `time_format.parse_start_time`.
  `_parseEventStartTime` in `docs/index.html` mirrors it — change both or neither.
- **A time shown to a human is am/pm**, via `format_time_of_day` (not `parse_start_time`).

### Security → [`dev/security.md`](dev/security.md)

- **Never commit secrets.** Keys live in `.zshrc`, GitHub Secrets, Render env vars.
- **`ADMIN_SECRET_KEY` must be set on Render** or every worker rejects every other's tokens.
- **Any new state-mutating route that reads form data needs `@require_bearer_auth`**, not
  `@require_auth` — a multipart POST is CORS-simple and lands with no preflight.
- **Everything from scrapers, Vision OCR, and `/submit` is untrusted** — including on the
  server-rendered `/e/<id>` page.
- **Errors are never echoed into the Slack channel** — the whole station is in it.
- Re-run `scripts/test_security_headers.py` after touching either CSP or adding any
  third-party embed. The GA4 host list was found empirically, not from docs.

### Files and images → [`dev/images.md`](dev/images.md)

- **Never have two writers to the same file** — a race once wiped 37 events.
- **Render storage is ephemeral** — commit artifacts to GitHub, not `/tmp`.
- **Never assume `image_url` is a Cloudinary URL** — legacy repo-hosted images coexist. Use
  `is_cloudinary_url()`.
- ⚠️ **`submissions.image_data` must never reach `jsonify`** — it is a `memoryview` and would
  break the whole admin Submissions tab.

### Testing → [`dev/testing.md`](dev/testing.md)

- ⚠️ **`./test_before_push.sh` is not read-only against production.** It calls `init_db()`
  with the `.env` `DATABASE_URL`, so it applies pending migrations to the live database. For
  a migration that drops or renames anything, deploy first.
- **Expect `18/18`, not just "all checks passed"** — `15/15` means the three Chromium browser
  suites silently skipped.
- Anything new in `test_admin_auth.py` that mutates state must be stubbed — it drives the
  real app with `.env` loaded.

### Instagram → [`dev/instagram-dead-end.md`](dev/instagram-dead-end.md)

- ⛔ **Instagram ingestion is a settled dead end (2026-08-27) — don't re-open it** without new
  information from Meta. `business_discovery` needs Advanced Access via Meta App Review, and
  it fails even against WYXR's own account, so the Tester workaround is ruled out too. The
  Slack pipeline already covers these venues.
- ⚠️ `scripts/instagram_setup_helper.py`: use `--write-env`, **never `--show-token`** — the
  latter has already leaked a live 60-day token into a screenshot.

### Feeds and URLs → [`dev/feeds-and-seo.md`](dev/feeds-and-seo.md)

- **The public footer links only `/picks.xml`.** `/feed.xml` is Admin → Tools → Feeds. Don't
  "fix" this by adding it back.
- **Don't change the ICS UID format on one side only** — it must match the modal's per-event
  `.ics`.
- **Verify a URL with `curl -I` (no `-L`) before putting it in a sitemap or canonical tag.**
  `cleanUrls: true` 308-redirects every `.html` path.

---

## File map

**Core:** `src/main.py` (orchestrator: fetch → merge → prune → HTML → RSS) ·
`src/config.py` (venues, neighborhoods, keywords, date ranges) ·
`src/models.py` (`compute_dedup_key` / `normalize_text` — shared event identity) ·
`src/normalize.py` · `src/date_utils.py` (incl. `resolve_yearless_date`) ·
`src/time_format.py` (`strftime_nopad`, `format_event_time`, `format_time_of_day`,
`parse_start_time`) · `src/http_utils.py`

**Generators:** `src/generate_html.py` (→ `docs/thisweek.html`) ·
`src/generate_rss.py` (→ `docs/feed.xml` 60-day, `docs/picks.xml` 180-day) ·
`src/generate_ics.py` (→ `docs/calendar.ics` 180-day) ·
`src/generate_sitemap.py` (→ `docs/sitemap.xml` + `robots.txt`)

**Backend:** `backend/app.py` (Flask REST API) · `backend/db.py` (PostgreSQL queries) ·
`backend/auth.py` (JWT, `require_auth` / `require_bearer_auth`, login throttle) ·
`backend/images.py` (Cloudinary + submission sanitization) ·
`backend/event_page.py` (server-rendered `/e/<id>`) · `backend/gunicorn_conf.py`

**Scrapers:** `src/sources/ticketmaster.py` · `src/sources/venue_scrapers.py` ·
`src/sources/artifacts.py` (Claude Vision)

**Frontend:** `docs/index.html` (all-in-one calendar) · `docs/thisweek.html` ·
`docs/admin/` (Events, Import, Scrapers, Venues, Sponsors) ·
`docs/admin/admin-common.js` (auth, API calls; all admin pages set `window.__API_BASE`)

**Deploy:** `.github/workflows/daily.yml` · `vercel.json` · `scripts/schema.sql`

## Local development

```bash
./run_local_backend.sh      # Terminal 1 — localhost:5001
./run_local_frontend.sh     # Terminal 2 — localhost:8000
./test_before_push.sh       # Terminal 3
```

Admin: `http://localhost:8000/admin/local.html` · Homepage:
`http://localhost:8000/local_index_home.html`. Config in `.env` (from `.env.example`), which
holds the **external** `DATABASE_URL`. See [`LOCAL_DEVELOPMENT.md`](LOCAL_DEVELOPMENT.md).

**Trigger a build manually:** `gh workflow run "Daily Concert Calendar Update"`, or Admin →
Tools → Trigger Build, or the Actions tab.

## Workflow preferences

- **Test locally before pushing** — `./test_before_push.sh`, expect `18/18`.
- **Always commit and push after completing work**, then trigger a build, wait for it to
  finish, and verify live. Don't wait to be asked.
- Use descriptive commit messages; include "Co-Authored-By: Claude" where appropriate.
- **When resuming from a previous session**, read the recent git log and open TODO/backlog
  files to see what's unfinished before asking.
- **When working with external APIs** (Qgiv, Mailchimp, Twilio, …), verify the exact request
  format (form-encoded vs JSON), base URL/subdomain, and required credentials before the
  first call.
- Transient `psycopg2.OperationalError: timeout expired` against Render Postgres is latency,
  not a defect — retry 2–3 times before investigating.

## Environment

- Python 3.12 via Homebrew (not conda); `pip install --break-system-packages` on macOS
- Check the system for the current date rather than assuming

## Cost

Render Starter ($7/mo, no cold starts) · Vercel free · GitHub Actions free · Ticketmaster API
free · Anthropic API ~$0.01 per image processed

---

Internal tool for WYXR 91.7 FM. Built in Memphis. 🎸
