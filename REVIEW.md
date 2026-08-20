# Concert Calendar — Code Review & Enhancement Roadmap

*Full-codebase review, August 20, 2026. Review only — no code was changed. Each item below
includes file/line references so it can be picked up as an individual task.*

**Contents:**
1. [Bugs & security fixes (do these first)](#1-bugs--security-fixes)
2. [Performance & optimization quick wins](#2-performance--optimization-quick-wins)
3. [Dead code & hygiene](#3-dead-code--hygiene)
4. [SEO](#4-seo)
5. [Missing venues & scrapers to add](#5-missing-venues--scrapers-to-add)
6. [Instagram ingestion — feasibility & recommended design](#6-instagram-ingestion)
7. [Other feature ideas](#7-other-feature-ideas)

---

## 1. Bugs & security fixes

### 1.1 Year-rollover bug — December builds silently drop Jan–Mar shows ⚠️ highest priority
`src/date_utils.py:36,43` defaults year-less dates ("Jan 15") to `START_DATE.year`. In a
December build, "Jan 15" parses to January of the *current* year — a past date — and is
dropped by the `START_DATE <=` filter at `src/sources/venue_scrapers.py:181`. Affected
scrapers: hi_tone, minglewood, hernandos, growlers, graceland, bbkings, landers, orpheum,
crosstown_arts (text fallback). Only `_parse_south_main_sounds`
(`venue_scrapers.py:1171-1173`) and `_parse_crosstown_beer` (`:1364-1371`) handle rollover.

The same bug exists independently in the admin import path: `_normalize_date_iso` at
`backend/app.py:1027-1033` replaces the 1900 default year with `datetime.now().year` — a
"Jan 15" flyer imported in December lands 11 months in the past.

**Fix:** centralize one rule in `parse_date_text`: if the parsed date is more than ~45 days
in the past, add a year. Reuse it from `app.py` too.

### 1.2 Dedup-key corruption — `normalize_text` strips inside words
`src/models.py:125` strips suffixes/noise words without word boundaries. Verified damage:
"Tourist" → "ist", "Live Wire" → "wire", "Showcase Showdown" → "case down",
"Olive Branch Boys" → "o branch boys", "The Show Ponies" → "ponies". This function feeds
`compute_dedup_key` (`models.py:140-155`), which is the *stored* `dedup_key` column — so
these mangled strings are the persisted event identity, causing both missed dedups and
false merges. **Fix:** add `\b` word boundaries to the strip regex, then re-backfill
`dedup_key` (pattern already exists in `scripts/backfill_dedup_key.py`).

Related: `_artists_match` in `src/normalize.py:73-75,103-104` is aggressive — ≥5-char
substring match and word-set subset both over-merge (e.g. Crosstown Brewing's literal
`"Live Music"` fallback at `venue_scrapers.py:1380` normalizes to `"music"` and collides).

### 1.3 Venue mis-canonicalization — bidirectional substring matching
`normalize_venue_name()` at `src/config.py:318-328` matches `alias in name or name in alias`.
Verified: `"Live"` → Graceland Soundstage, `"Nashoba Valley Ski Area"` → Nashoba,
`"Bside Bistro"` → B-Side Memphis. Any loose venue string from Ticketmaster or Claude
Vision can be silently rewritten to the wrong venue, and this feeds the dedup key.
**Fix:** exact/word-boundary alias matching only.

### 1.4 XSS — three distinct holes
1. **Public page, attribute injection:** `esc()` at `docs/index.html:2160-2165` doesn't
   escape `'` or `"`, but is interpolated into HTML *attributes* at lines 1755 (`data-neighborhood`),
   1926 (`aria-label`), 2004-2006 (`src`, `data-raw`), 2091-2092 (sponsor `href`/`src`).
   Titles come from scrapers and OCR — a `"` in a title breaks out of the attribute.
   (`openEventModal` at `:1419-1421` already hand-fixes this; the fix never propagated.)
2. **Public page, raw HTML:** `descEl.innerHTML = ev.description` at `docs/index.html:1477`
   injects DB HTML straight into the DOM. Submissions cap length (`backend/app.py:360`) but
   never sanitize. Use `textContent`.
3. **Stored XSS into the admin origin (worst):** `esc()` in
   `docs/admin/admin-common.js:107-111` also skips quotes, and is interpolated into
   single-quoted inline `onclick` handlers at `docs/admin/index.html:3303,3305`. The value
   (`k.name`) originates from the **unauthenticated** `POST /api/request-key`
   (`backend/app.py:2094-2114`), so an attacker-supplied key name executes JS in the admin
   session (where `sessionStorage.admin_token` lives). **Fix:** delegated listeners +
   `data-` attributes (the Events tab already does this correctly at `index.html:1550-1555`)
   plus a quote-escaping `escAttr()`.

### 1.5 CSRF on admin multipart routes
Admin cookie is `SameSite=None; Secure` (`backend/app.py:443-447`). Multipart POSTs are
CORS-*simple* (no preflight, cookie attached), so `/api/admin/import/upload` (`app.py:910`),
`/api/admin/import/image` (`:1107`), `/api/admin/sponsors/upload-image` (`:1200`), and
`/api/admin/calendar-sponsor/upload-image` (`:1279`) can be triggered cross-site by any page.
**Fix:** require the `Authorization: Bearer` header on these routes (reject cookie-only auth).

### 1.6 Admin login hardening
- No rate limit on `POST /api/admin/login` (`app.py:429`) — unlimited guesses against one
  shared password. Reuse the submissions rate-limiter pattern (`app.py:228`).
- `hmac.compare_digest(password, ADMIN_PASSWORD)` at `app.py:438` raises `TypeError`
  (→ 500) on non-ASCII input — encode both sides to bytes.
- `backend/auth.py:13`: if `ADMIN_SECRET_KEY` is unset, a random per-process key is used —
  every restart silently logs everyone out, and multi-worker tokens don't interoperate.
  Fail loudly at boot instead.

### 1.7 Submit form rejects same-day events after 7 PM
`docs/submit.html:473,526` uses `new Date().toISOString().split('T')[0]` — the **UTC** date —
for the min-date check. After 7 PM Central the form refuses tonight's show. Compute the
date in `America/Chicago`.

### 1.8 Ticketmaster pagination missing
`venue_scrapers.py:255` requests `size: 50` (city-wide: `ticketmaster.py:41`, `size: 100`)
with no `page` loop — any venue with >50 events in the 180-day window is silently truncated.
Also inconsistent: city-wide TM uses the 8-day `END_DATE` (`ticketmaster.py:39-40`) and
returned exactly 1 event in the latest build — nearly useless; per-venue uses the 180-day
window.

### 1.9 Presents section filters on stale state
`renderPresentsSection` (`docs/index.html:1897-1904`) re-reads `searchInput.value` and the
active chip from the DOM, shadowing module state — during the 200 ms search debounce the
Presents section and the main list filter on different queries.

### 1.10 `--dry-run` isn't dry
`_create_scrape_log` runs before the dry-run check (`src/main.py:506`) and is never
finalized (early return at `:660`), leaving a permanent `status='running'` scrape_logs row
that the health check can read as a hung build.

### 1.11 Smaller correctness items
- **Slack retry double-insert:** `slack_events` (`app.py:1858`) ignores `X-Slack-Retry-Num`;
  Slack retries non-2xx responses, so a slow Vision call can insert a flyer twice (fuzzy
  dedup is the only guard).
- **Slack caption window:** `_process_slack_image` searches only the last 10 messages
  (`app.py:1645`); busy channel → upload silently dropped.
- **Decompression-bomb guard missing** on the unauthenticated image path
  (`backend/images.py:141-142`) — set `Image.MAX_IMAGE_PIXELS` and catch
  `DecompressionBombError`.
- **`admin_venues_update` is non-atomic** (`app.py:631-668`): rename commits, then events
  propagate in a second transaction; a failure in between leaves them inconsistent. It also
  blindly overwrites every event's neighborhood (`:663-666`), clobbering manual overrides.
- **Escape-key handlers stack** (`docs/index.html:1141,1576`): Esc with the event modal open
  also closes the subscribe modal.
- **Subscribe modal always reports success** (`docs/index.html:1149-1198`): reading the
  cross-origin Mailchimp iframe always throws, and the catch resolves `'success'` — invalid
  emails and "already subscribed" are indistinguishable from success.
- **`bulk_action` 500s on malformed UUIDs** (`backend/db.py:634`).
- `%-I`/`%-d` strftime codes (`venue_scrapers.py:285`, `main.py:719`, `generate_rss.py:74`)
  are glibc-only — break local dev on macOS/Windows.

---

## 2. Performance & optimization quick wins

### Database
- **Missing indexes (biggest single win):**
  `CREATE INDEX idx_events_venue_lower ON events (LOWER(venue));` — five query sites filter
  or join on `LOWER(e.venue)` (`db.py:855,888,1005,1042`, `app.py:651`) and seq-scan today.
  Also add `(is_active, date)` for the hot public query (`db.py:443-455`); only
  `idx_events_date` exists.
- **`bulk_insert_events` is N+1²** (`db.py:684-712`): one INSERT per event, and each
  iteration's `_event_dedup_key` → `normalize_venue_from_db` opens its own pooled connection
  and runs a query. A 30-event flyer = ~60 round trips. Resolve venues once into a dict and
  use `execute_values`. Same fix for the Slack path, which calls `_canonical_venue`
  per event *three times* (`app.py:1750,1778,1827`) and `_venue_hint_from_caption` queries
  once per trailing-word prefix (`app.py:1549-1559`).
- **`GET /api/admin/events/<id>` doesn't exist** — `docs/admin/edit.html:416` downloads the
  entire events table to edit one record. Five-line route.
- **`GET /api/admin/events` has no LIMIT or default window** (`db.py:469-491`), called from
  three places with no params.
- **`api_request_logs` grows unboundedly** (`db.py:1592`) with a thread spawned per request
  (`app.py:1919`) against a `maxconn=10` pool — add retention + consider batching.
- No `ETag`/304 anywhere; `/api/events/<id>` and `/api/venues` lack even `max-age`.

### Build pipeline
- **Delete the "Clean up old artifacts" step** (`.github/workflows/daily.yml:48-65`): the
  `artifacts/` dir doesn't exist, every error is swallowed, and line 55 interpolates a
  repo-controlled filename into a `python3 -c` string — shell-injectable.
- **Remove the dead `GOOGLE_SHEET_CSV_URL` secret** (`daily.yml:42`) — nothing reads it.
- Add `timeout-minutes` to the job (worst-case scraper math allows ~54 s × venue, and
  blues_city_cafe multiplies by 7 month-pages with no overall deadline).
- `-X theirs` on the rebase (`daily.yml:85`) can silently clobber real conflicts in `docs/`.
- Full `data/events.json` (entire event history) is rewritten and committed twice daily —
  most of the repo's churn. Consider snapshotting only the active window, or stop
  committing it.
- `time.sleep(0.001)` per merged event (`main.py:858`) is pointless — the ID already embeds
  the index.
- Module-level date constants (`src/config.py:10-15`) are frozen at import — a long-running
  Flask process keeps yesterday's `TODAY` until restart.

### Frontend
- `deduplicateEvents` (`docs/index.html:1787-1835`) is O(n²) and re-runs 6 regex passes per
  comparison, on every render — precompute normalized titles once.
- Change detection double-`JSON.stringify`s ~2 MB (`:1698`) and always says "changed" on
  cold load — compare count + max `updated_at` instead.
- localStorage cache (`:1612-1626`) has no TTL/version and silently fails forever on quota.
- `new Date(d.toLocaleString('en-US',{timeZone}))` (`:1062,1843`) is engine-dependent — use
  `formatToParts` (already done correctly at `:1334-1337`); `toISOString()` for month
  boundaries (`:1671-1672`) slips a day at positive UTC offsets.
- `<meta charset>` sits *below* two script tags (lines 5–12); Google Fonts stylesheet is
  render-blocking.
- Legacy images are huge (1.9 MB / 1.2 MB / 1.1 MB PNGs in `docs/event-images/`; five
  identical 544 KB JPEGs in `docs/sponsors/`) and the `onerror` fallback (`:2006`) can serve
  them raw.

---

## 3. Dead code & hygiene

- **Dead source modules:** `src/sources/eventbrite.py` (calls an API endpoint Eventbrite
  removed in 2020), `bandsintown.py` (self-described disabled), `dice.py`,
  `google_sheet.py` — none imported by `src/main.py`. Also the dead serial `fetch()` at
  `venue_scrapers.py:49-80` and the unreachable `return events` (undefined name) at `:1479`.
- **Stale docs:** `CLAUDE.md` says "Venues (15 total)" — reality is **27** (≈14 custom,
  7 Ticketmaster-API, 2 Elfsight, 1 SiteWrench, 1 generic, 2 manual-only), and it lists
  B.B. King's as manual-only though a working `bbkings` scraper exists (`FEATURES.md:38` is
  stale the same way). CLAUDE.md also still describes the orchestrator as
  "fetch → merge → **prune** → …" though pruning was removed (`main.py:384` hardcodes
  `"pruned": 0`).
- **Duplicate scripts:** `scripts/cleanup_duplicates.py` vs `scripts/clean_duplicates.py`;
  four spent one-time migration scripts; `scripts/schema.sql` + `scripts/migrations/*.sql`
  duplicate `db.py:_run_migrations()` (two sources of truth for the schema).
- **Duplicated logic to consolidate:** three Ticketmaster event-conversion blocks
  (`venue_scrapers.py:269-297`, `ticketmaster.py:81-122`), two JSON-LD parsers
  (`venue_scrapers.py:448-513`, `artifacts.py:312-402` — already FEATURES.md #11), the
  time-format incantation repeated 8×, three "is this music" keyword filters
  (`config.py:397-424`, Landers `venue_scrapers.py:913-928`, Flyway `:1279-1281`).
- ~15 `except Exception: continue` blocks in scrapers mean a fully-broken parser reports
  success with 0 events; the `except (json.JSONDecodeError, Exception)` no-op tuple appears
  in three files.
- Admin misc: "Rebuild Calendar Only" button is a self-documented no-op alias
  (`docs/admin/index.html:2946-2947`); `edit.html:480-486,530-536` retry against endpoints
  that don't exist; custom neighborhoods live in `localStorage` (`index.html:1829`) so they
  don't sync between machines; `prompt()/confirm()` for destructive flows; tab switches
  pollute browser history (`:1406`).
- `test-mailchimp.html` (scratch file) and header-only `manual_events.csv` in the deployed
  tree; three 15-line redirect shells that could be `vercel.json` redirects.
- `_run_vision_api` (`artifacts.py:430-532`) has no timeout/retry and a hardcoded model id.

---

## 4. SEO

`docs/index.html` is 100 % client-rendered — `<main id="eventList">` ships empty and **no
page in `docs/` emits `application/ld+json`**. Google effectively sees a blank flagship page.
- Emit per-event **`Event` JSON-LD** at build time (the static generator already exists —
  `src/generate_html.py` builds `thisweek.html`).
- Optionally inline the current week's rendered HTML into `index.html` at build time as a
  no-JS first paint.
- **`docs/feed.xml` (324 KB, rebuilt every run) is linked from nowhere** — add
  `<link rel="alternate" type="application/rss+xml">` and a footer link. One-line fix that
  turns a dead deliverable into a discoverable one.
- RSS polish: `pubDate` is the *event* date (readers sort/expire on it) — use build time;
  `<enclosure type="image/jpeg" length="0">` is wrong for PNGs and technically invalid.

---

## 5. Missing venues & scrapers to add

Already covered (contrary to CLAUDE.md's stale list): Grind City Amphitheater, Satellite
Music Hall, Radians, Bluesville, Snowden Grove, Cannon Center — all via the
`ticketmaster_venue` API scraper.

**Recommended additions**, in rough value order (process per venue: verify page structure
live → add to `VENUES` in `src/config.py` → seed in `backend/db.py:_seed_venues_if_empty()`
→ `python -m src.main --dry-run`):

| Venue | Likely approach |
|---|---|
| **Railgarten** | `railgarten.com/events` — WordPress events pages; try the `generic` JSON-LD scraper first, else a small custom parser |
| **Black Lodge** | `blacklodgememphis.com/events` — inspect; frequent shows, strong WYXR-audience overlap |
| **Lamplighter Lounge** | Very active; site/Songkick inspection needed — flyers already arrive via the Slack pipeline today |
| **Young Avenue Deli** | Cooper-Young regional bands; inspect site |
| **Wild Bill's** | Juke joint; likely manual/Instagram — candidate for the IG pipeline below |
| From `FEATURES.md` backlog | Loflin Yard, Wiseacre taprooms, Halloran Centre; Beale St. residencies (Rum Boogie, Silky O'Sullivan's, Alfred's) |

**Aggregator fallback:** `src/sources/bandsintown.py` is already written (disabled). Reviving
it *scoped to specific venue pages* is the cheapest coverage for venues with no usable
website — fix its year handling and retry gaps first (§1.1, §3).

Constraint to respect: the stack has **no headless browser** (no Playwright/Selenium in
`requirements.txt`) — skip venues whose calendars only render via JS, or accept adding one.

---

## 6. Instagram ingestion

**Question asked:** can Instagram stories or posts be scraped automatically for venues that
only post to social (Bar DKDC, B-Side, etc.)?

### Stories — no legitimate automation exists
No Meta API exposes *other* accounts' stories. Scraping them requires a logged-in bot
session, which violates Instagram's ToS, risks the station's account, and breaks constantly.
**Recommendation: keep the existing Slack screenshot pipeline as the human bridge for
stories** — a DJ screenshots the story and posts it to #wyxr-concert-calendar with
"add to calendar <venue>". Friction-reducers: widen the caption search window past 10
messages (`app.py:1645`) and handle Slack retries (§1.11).

### Posts — yes, via the official **Business Discovery API** (recommended)
Using WYXR's *own* Instagram Business/Creator account token, the Graph API's
`business_discovery` edge returns another public business/creator account's recent **posts**
— caption, `media_url`, permalink, timestamp — by username. ToS-compliant, free, rate limit
~200 calls/hour (a handful of venues checked nightly doesn't come close). Most venue
accounts are business accounts. It does **not** return stories, and can't read personal
(non-business) accounts.

**One-time setup (Robby):**
1. Ensure the WYXR Instagram account is a Business/Creator account linked to a Facebook Page.
2. Create a Meta app (developers.facebook.com) with `instagram_basic` +
   `business_management`/`pages_show_list` permissions.
3. Generate a long-lived (60-day, refreshable) access token; note the IG Business Account ID.
4. Render env vars: `IG_ACCESS_TOKEN`, `IG_BUSINESS_ACCOUNT_ID`.

**Proposed architecture (reuses what's already built):**
- New `src/sources/instagram.py`: for each username in a new
  `INSTAGRAM_VENUE_ACCOUNTS = {"bardkdc": "Bar DKDC", "bsidememphis": "B-Side Memphis", ...}`
  in `src/config.py`, fetch posts newer than the last-seen timestamp (persist cursor in DB).
- Download each image and pass it through the **existing Vision pipeline**
  (`extract_events_from_image_bytes()` in `src/sources/artifacts.py`), passing the caption
  and the *known venue* as hints — this sidesteps the "flyer never names its own venue"
  problem the Slack pipeline solved with caption hints.
- Insert results as **pending rows in the existing `submissions` table** (not straight onto
  the calendar): flyer OCR is noisy, and the admin Submissions tab already provides
  approve/edit/reject. Skip non-event posts cheaply by pre-filtering captions (date-like
  text) before spending a Vision call (~$0.01/image).
- Run nightly from the daily workflow. Ships dark until the env vars are set.

**Fallback (not recommended as primary):** third-party scraper APIs (Apify's Instagram
scraper, etc.) can fetch public posts without Meta setup — but they cost money, sit in a ToS
gray zone (public-data scraping is lawful in the US post-*hiQ*, but breaches platform terms),
and break when Instagram changes markup. Reasonable only if the Meta app route stalls.

---

## 7. Other feature ideas

In rough value-for-effort order:

1. **iCal subscribe feed** (`docs/calendar.ics`, advertised as `webcal://`) — lets anyone
   subscribe to the whole calendar (or a venue/neighborhood filter) in Apple/Google Calendar.
   The ICS generation logic already exists client-side (`docs/index.html:1331-1348`); move
   it into the build alongside the RSS feed. Probably the highest-value listener-facing
   feature not yet built.
2. **Per-event deep links** — `#event=<id>` opens the modal on load, so DJs can share a
   specific show; plus per-event OG meta (or lightweight static event pages at build time)
   so shares unfurl with the flyer image.
3. **Weekly email digest** — the data and Mailchimp audience already exist; generate a
   this-week email from the same build that writes `thisweek.html`.
4. **Genre tags & price display** — already spec'd as FEATURES.md #14/#15; genre chips would
   be the most-used filter after neighborhood.
5. **"Tonight" Slack post** — the bot already lives in #wyxr-concert-calendar; a daily
   morning message listing tonight's shows closes the loop for DJs on air.
6. **Embeddable widget** for wyxr.org — a small iframe/JS embed of the next-7-days list.
7. **Visual unification** — `thisweek.html` still uses the pre-July-2026 palette
   (`#000/#FFCF2D`) vs. index's slate palette (`#2A2E35/#FFD64A`).
8. **Admin quality-of-life** — real `GET /api/admin/events/<id>` (§2), replace
   `prompt()/confirm()` flows, DB-backed custom neighborhoods, tie build-progress polling to
   the actual workflow run instead of inferring from log rows
   (`docs/admin/index.html:2985-3043`).
9. **Accessibility pass** — page has no `<h1>`, no skip link, modals lack live regions, and
   the subscribe modal stays in the a11y tree when closed.

---

## Suggested sequencing

1. **Round 1 (bugs/security):** §1.1–1.7 + the two DB indexes — small, independent, each
   verifiable with `./test_before_push.sh` and a local run.
2. **Round 2 (pipeline):** TM pagination, bulk-insert fix, workflow cleanup, dead-code
   removal, CLAUDE.md refresh.
3. **Round 3 (reach):** JSON-LD + feed link + iCal feed; then new venues (Railgarten and
   Black Lodge first).
4. **Round 4:** Instagram posts pipeline (after the Meta app/token exists).
