# Feature Requests — WYXR Memphis Concert Calendar

Planning doc for upcoming features. Each section covers the what, why, and rough implementation notes based on the current architecture.

---

## Pending Fixes & New Sources

### Scrapers to Fix
- **Ticketmaster API** — needs API key configured in GitHub Secrets (`TICKETMASTER_API_KEY`)
- **B.B. King's Blues Club** — scraper returning 0 events, page structure may have changed
- **FedExForum** — scraper returning 0 events, page structure may have changed

### New Venues to Add
- **Nashoba Live** — https://nashoba.live/event-calendar/ (venue in Memphis area)
- **Lamplighter Lounge** — appears in Bandsintown data but not in VENUES config; need to determine scraping approach
- **Beale Street venues** — Blues City Cafe, Rum Boogie Cafe, Silky O'Sullivan's, Alfred's on Beale (nightly live music, not currently tracked)
- **Railgarten** — frequent outdoor shows, not currently tracked
- **Loflin Yard** — live music events, not currently tracked
- **Wiseacre Brewing** — hosts live music, not currently tracked
- **The Halloran Centre** — currently an Orpheum alias but has its own event calendar

### Venues to Research
- **DKDC** — currently marked as manual_only (Instagram), explore alternatives
- **B-Side** — currently marked as manual_only (socials), explore alternatives

---

## 1. Edit / Delete Events

**Problem:** Once events are imported (from scrapers, artifacts, Bandsintown, etc.), there's no way to correct bad data — misspelled artist names, wrong venues, duplicate entries that slipped through dedup, or events that got cancelled. The only options today are waiting for the next daily rebuild or manually editing `docs/log.json`.

**What this looks like:**
- A password-protected admin view (similar to the existing `/upload.html` page) listing all events for the current build
- Each event row gets Edit and Delete buttons
- Edit opens an inline form pre-filled with artist, venue, date, time
- Delete removes the event and flags it so future imports don't re-add it
- Changes persist in a `overrides.json` file that the build pipeline reads

**Implementation notes:**
- Add `docs/admin.html` — static page that fetches `log.json`, renders an editable table, and posts changes to a new `/api/override.py` endpoint
- New Vercel serverless function `api/override.py` — accepts POST with event edits/deletes, writes to `overrides.json` in the repo (via GitHub API using the existing `GITHUB_PAT`)
- `src/main.py` reads `overrides.json` at build time and applies edits/removals after dedup but before HTML generation
- Override format: `{ "deletes": ["normalized_key", ...], "edits": { "normalized_key": { "artist": "...", "venue": "...", ... } } }`
- Deleted keys act as a persistent blocklist so the same bad event doesn't reappear on the next scrape

---

## 2. Star / Feature Events (DJ Picks)

**Problem:** The calendar lists everything it finds, but WYXR DJs want a way to highlight the shows they're excited about — a curated "don't miss" layer on top of the raw data. Right now every event has equal visual weight.

**What this looks like:**
- In the admin view, each event also gets a Star toggle
- Starred events appear in a "DJ Picks" section at the top of the main calendar page, above the day-by-day listings
- Starred events still appear in their normal day section too, but with a visual indicator (bold, accent color, or a small star icon)
- Picks are per-day — a DJ can feature different shows each day of the week

**Implementation notes:**
- Extend `overrides.json` with a `"featured": ["normalized_key", ...]` array
- `generate_html.py` checks the featured list and renders a "DJ PICKS" section before the day sections
- The admin page star toggle calls `/api/override.py` with `{"action": "feature", "key": "..."}` or `{"action": "unfeature", "key": "..."}`
- Optionally support a short DJ note per pick (e.g., "Killer Memphis blues, don't sleep on this one") stored as `"featured_notes": { "key": "note text" }`
- CSS: featured events get a left border accent or background highlight that works in both light and dark mode

---

## 3. Custom Domain

**Problem:** The calendar currently lives at `concert-calendar.vercel.app`. A branded domain (e.g., `shows.wyxr.org` or `calendar.wyxr.org`) would look more professional and be easier for DJs to remember and share.

**What this needs:**
- A domain or subdomain pointed at Vercel (CNAME or A record)
- Vercel project settings updated to accept the custom domain
- No code changes required — Vercel handles SSL automatically

**Steps:**
1. Choose a subdomain (e.g., `shows.wyxr.org`)
2. In the WYXR DNS provider, add a CNAME record: `shows` → `cname.vercel-dns.com`
3. In the Vercel dashboard → Project Settings → Domains → add `shows.wyxr.org`
4. Vercel provisions an SSL cert automatically (Let's Encrypt)
5. Update the README with the new URL
6. Optionally add a redirect from the old `.vercel.app` URL to the custom domain

**Considerations:**
- If WYXR uses Squarespace/WordPress for their main site, DNS changes may need to go through whoever manages that
- The custom domain works regardless of whether the GitHub repo is public or private

---

## 4. Event Feed (JSON / RSS) for Website Embedding

**Problem:** The calendar data is locked inside a standalone HTML page. WYXR's main website (and potentially other local sites or apps) should be able to pull the event listing and display it natively — an upcoming shows widget in the sidebar, an events page, social media bots, etc.

**What this looks like:**
- A public JSON API endpoint (`/api/events.json` or `/feed.json`) returning the current event data in a clean, documented format
- An RSS/Atom feed (`/feed.xml`) for podcast apps, feed readers, and IFTTT-style automation
- Optionally, an embeddable `<iframe>` snippet or JS widget

**Implementation notes:**

### JSON feed
- Already partially exists — `docs/log.json` contains all event data, but the format is oriented toward debugging, not consumption
- Add a `docs/feed.json` generated by `main.py` with a cleaner schema:
  ```json
  {
    "updated": "2026-02-11T23:23:49Z",
    "date_range": { "start": "2026-02-12", "end": "2026-02-18" },
    "events": [
      {
        "artist": "Dale Watson",
        "venue": "Hernando's Hideaway",
        "date": "2026-02-12",
        "time": "8:00 PM",
        "url": "https://...",
        "featured": false
      }
    ]
  }
  ```
- Add CORS headers so any website can fetch it client-side

### RSS feed
- Generate `docs/feed.xml` in Atom or RSS 2.0 format during build
- Each event becomes an `<item>` with title, date, venue as description
- Useful for IFTTT ("new event posted → tweet it"), feed readers, newsletter tools

### Embeddable widget
- A lightweight `docs/widget.js` that fetches `feed.json` and renders a styled event list into any `<div id="wyxr-events"></div>` on another site
- Keeps styles scoped to avoid conflicts with host page CSS

---

## 5. Import Transparency — Source Status Dashboard

**Problem:** The calendar pulls from 10+ sources (Ticketmaster, venue websites, artifacts, Google Sheet, Bandsintown). Some fail silently — Growlers times out, Lafayette's returns 403, Overton Park Shell 404s, Graceland changed their page. DJs uploading artifacts don't know if their upload was processed or how many events were extracted. There's no visibility into what worked and what didn't unless you dig into `log.json`.

**What this looks like:**
- A "Source Status" section on the main page (or a dedicated `/status.html` page) showing each source and its last-run result
- Color-coded: green (working, found events), yellow (working, 0 events this week), red (error/failed)
- For each source: name, event count, and a short status message
- For artifacts specifically: list each uploaded file, how many events were extracted, and which events came from it
- Timestamp of last successful build

**Implementation notes:**
- Most of the data already exists in `docs/log.json` — the `sources` array has name, success, events_found, events_filtered, and error for every source
- Option A (simple): Add a collapsible "Source Status" footer to `index.html` generated by `generate_html.py` — renders the source results as a summary table
- Option B (separate page): Generate `docs/status.html` with a full dashboard:
  - Source-by-source breakdown with status indicators
  - Per-artifact detail (file name, upload time, events extracted, events that made it through dedup)
  - Historical trend (last N builds) if we start persisting `status.json` across runs
- For artifact transparency, extend `src/sources/artifacts.py` to write per-file results into the log — currently it aggregates all artifacts into one `SourceResult`
- Add a link from the main calendar footer: "How is this built?" → status page

**Quick win vs. full version:**
- Quick win: Add a small status summary directly to the calendar page footer — "Last updated Feb 11, 76 events from 8 sources (3 sources had errors)"
- Full version: Dedicated dashboard with per-source and per-artifact detail

---

## 6. HTML / SEO / Social Sharing Improvements

**Problem:** The generated `index.html` has no `<meta name="description">`, no OpenGraph tags, and no Twitter Card tags. When anyone shares the calendar link on social media or messaging apps, the preview is blank — no title, no description, no image. This limits organic discovery.

**What this needs:**
- Add `<meta name="description">` with a dynamic summary (e.g., "47 live music shows in Memphis this week")
- Add OpenGraph tags (`og:title`, `og:description`, `og:type`, `og:url`) for Facebook/LinkedIn/Discord/iMessage previews
- Add Twitter Card tags (`twitter:card`, `twitter:title`, `twitter:description`)
- Add a favicon (WYXR logo or a music note icon)
- Optionally, generate a dynamic OG image showing the week's highlight count

**Implementation notes:**
- All changes go in `generate_html.py` — add ~10 lines of meta tags to the `<head>` section
- Favicon: add a `docs/favicon.ico` or `docs/favicon.png` and reference it with `<link rel="icon">`
- The description and OG tags can use the same `total_events` and date range already available in the template
- No external dependencies required

**Effort:** Low (30 minutes)

---

## 7. Data Quality: HTML Entity Decoding

**Problem:** Some event titles contain raw HTML entities (e.g., `&#8217;` instead of an apostrophe in "Folk All Y'all: Lilly Hiatt"). This happens when JSON-LD source data contains encoded HTML and `BeautifulSoup.get_text()` doesn't decode it.

**Fix:**
- Add an `html.unescape()` pass to artist/venue text after extraction in venue scrapers and artifact parsers
- One-line fix per extraction point, or a single post-processing step in `main.py` before dedup
- Example: `import html; artist = html.unescape(artist)`

**Effort:** Low (15 minutes)

---

## 8. Scraper Resilience: HTTP Retry Logic

**Problem:** Each scraper makes a single `requests.get()` call. A transient network timeout or 503 response fails that entire source until the next build (12+ hours). This is especially painful for venue scrapers since each venue is an independent HTTP call.

**What this needs:**
- A simple retry wrapper: 2 attempts with a 3-second delay between retries
- Only retry on transient errors (timeout, 500, 502, 503, 429)
- Don't retry on 404 or 403 (those indicate a real problem)

**Implementation notes:**
- Add a shared `_get_with_retry(url, headers, timeout, retries=2)` function in `venue_scrapers.py` or a shared `http_utils.py`
- Replace bare `requests.get()` calls with the retry wrapper
- Alternatively, use `requests.adapters.HTTPAdapter` with `urllib3.util.Retry` (built-in retry support)

**Effort:** Low-Medium (1 hour)

---

## 9. Venue Link Enhancement

**Problem:** Events with URLs link the entire line (artist + venue + time). Users who want to see a venue's full schedule beyond the 8-day window have no way to navigate there from the calendar.

**What this looks like:**
- Venue names in the event listing link to the venue's own calendar page
- The artist name links to the ticket/event URL (as today)
- If no event URL exists, the venue link still works

**Implementation notes:**
- The venue `calendar_url` data already exists in `config.py` VENUES
- Pass a venue URL map to `generate_html.py`
- Modify the event line template to render venue as a separate `<a>` tag when a venue URL is known

**Effort:** Low-Medium (1 hour)

---

## 10. Date Parsing Consolidation

**Problem:** `google_sheet.py` (lines 109-123) reimplements date parsing with its own format list instead of using the shared `date_utils.parse_date_text()`. This means format improvements to the shared function don't benefit the Google Sheet source, and bugs could diverge.

**Fix:**
- Replace the inline date parsing in `google_sheet._parse_row()` with a call to `date_utils.parse_date_text()`
- The shared function already handles all the same formats plus more (regex fallback for "Wed Feb 12" etc.)

**Effort:** Low (10 minutes)

---

## 11. JSON-LD Parser Consolidation

**Problem:** There are three near-identical JSON-LD event parsers:
1. `venue_scrapers._try_jsonld()` + `_jsonld_to_event()`
2. `artifacts._parse_generic_event_html()` Strategy 1 + `_parse_jsonld_event()`
3. `dice._parse_jsonld()`

Each handles `@type: Event/MusicEvent`, extracts `startDate`, `location.name`, and `url` with minor variations. Bugs fixed in one copy aren't fixed in the others.

**Fix:**
- Create a shared `src/jsonld_utils.py` with `parse_jsonld_events(soup) -> List[Event]`
- Have all three sources import and use the shared parser
- Keep source-specific post-processing (e.g., DICE prefixes URLs with `https://dice.fm`)

**Effort:** Medium (1-2 hours)

---

## 12. Naive Timestamp Handling

**Problem:** `main.py` uses `datetime.now()` (line 42) which returns local time with no timezone info. In GitHub Actions this is UTC, but on a developer's machine it's local time. Then `generate_html.py` (line 55) force-assumes the timestamp is UTC with `replace(tzinfo=ZoneInfo("UTC"))`. If anyone runs `python -m src.main` locally in Central time, the displayed time will be wrong by 6 hours.

**Fix:**
- Change `main.py` line 42 from `datetime.now()` to `datetime.now(ZoneInfo("UTC"))`
- Remove the `replace(tzinfo=ZoneInfo("UTC"))` in `generate_html.py` since the timestamp is already timezone-aware
- Add `from zoneinfo import ZoneInfo` to `main.py`

**Effort:** Low (10 minutes)

---

## 13. Extended Date Range Option

**Problem:** The current 8-day window (today + 7 days) is good for "this week" but doesn't help people planning ahead. A 14-day view would let users see next weekend's shows too.

**What this needs:**
- Add an optional `--days N` argument to `main.py`
- Or generate two views: the current 8-day `index.html` and a 14-day `upcoming.html`
- Or add a simple "Next 7 Days / Next 14 Days" toggle in the HTML (client-side JS filtering events by date)

**Considerations:**
- More days = more events = more API calls (Ticketmaster is fine at 5000/day)
- Venue scrapers already fetch full calendars and filter by date range, so extending the range costs nothing extra
- The dedup and HTML generation scale fine to ~200 events

**Effort:** Low (main.py tweak) to Medium (two-view generation or client-side toggle)

---

## 14. Genre / Category Tags

**Problem:** The calendar currently treats all events equally — a jazz show and a punk show look the same. Genre tags would help users quickly find events they care about.

**What this needs:**
- Add an optional `genre` field to the `Event` model
- Extract genre from Ticketmaster API (already available in classification data)
- Infer genre from MUSIC_KEYWORDS matches (e.g., "blues" in title → Blues tag)
- Display as a small colored tag or pill next to the event

**Effort:** Medium (2-3 hours)

---

## 15. Price / Ticket Info

**Problem:** Users can't tell which shows are free vs. $50+ without clicking through to each event page.

**What this needs:**
- Add optional `price` field to `Event` model
- Extract from Ticketmaster API (`priceRanges` field)
- Extract from venue pages where available (Hernando's shows cover charges)
- Display as "Free", "$10", "$15-25" etc.

**Effort:** Medium (2-3 hours)

---

## Priority / Sequencing Suggestion

| # | Feature | Effort | Value | Suggested Order |
|---|---------|--------|-------|-----------------|
| 5 | Import transparency | Low | High | First — quick win adds immediate trust |
| 6 | HTML / SEO / social sharing | Low | High | Second — 30 min for major discoverability boost |
| 7 | HTML entity decoding | Low | Medium | Third — quick data quality fix |
| 10 | Date parsing consolidation | Low | Medium | Third — quick code quality fix |
| 12 | Naive timestamp fix | Low | Medium | Third — quick correctness fix |
| 3 | Custom domain | Low | High | Fourth — config only, no code |
| 8 | HTTP retry logic | Low-Med | High | Fifth — reduces stale data |
| 4 | Event feed (JSON) | Medium | High | Sixth — unlocks website integration |
| 11 | JSON-LD parser consolidation | Medium | Medium | Seventh — code quality |
| 9 | Venue link enhancement | Low-Med | Medium | Eighth — UX improvement |
| 1 | Edit / delete events | Medium | Medium | Ninth — needs admin UI + API |
| 2 | Star / feature events | Medium | Medium | Tenth — builds on edit/admin UI |
| 13 | Extended date range | Low-Med | Medium | Anytime — independent of other work |
| 14 | Genre / category tags | Medium | Medium | Later — nice-to-have |
| 15 | Price / ticket info | Medium | Medium | Later — nice-to-have |

Features 1 and 2 share an admin interface and the `overrides.json` mechanism, so they should be built together once that foundation is in place.
