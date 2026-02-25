# Feature Requests — WYXR Memphis Concert Calendar

Planning doc for upcoming features.

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

## Completed

- ~~Edit / Delete Events~~ — Full admin CRUD via PostgreSQL + Flask API
- ~~Star / Feature Events~~ — Featured toggle, gold border + "WYXR Pick" badge
- ~~Import Transparency~~ — Scraper dashboard with status cards, run logs, trigger build
- ~~HTML Entity Decoding~~ — `html.unescape()` on all text after collection
- ~~HTTP Retry Logic~~ — `get_with_retry()` with 2 retries, 3s backoff
- ~~Date Parsing Consolidation~~ — Shared `date_utils.parse_date_text()`
- ~~Naive Timestamp Fix~~ — `datetime.now(ZoneInfo("UTC"))`

---

## 3. Custom Domain

**Problem:** The calendar lives at `concert-calendar.vercel.app`. A branded domain (e.g., `shows.wyxr.org`) would look more professional.

**Steps:**
1. Choose a subdomain (e.g., `shows.wyxr.org`)
2. In DNS, add CNAME: `shows` -> `cname.vercel-dns.com`
3. In Vercel dashboard -> Domains -> add `shows.wyxr.org`
4. Vercel provisions SSL automatically

**Effort:** Config only, no code changes.

---

## 4. Event Feed (JSON / RSS) for Website Embedding

**Problem:** The calendar data is locked inside a standalone HTML page. WYXR's main website should be able to pull event data and display it natively.

**What this looks like:**
- A public JSON feed (`/feed.json`) with a clean, documented schema
- An RSS/Atom feed (`/feed.xml`) for feed readers and automation
- Optionally, an embeddable JS widget

**Implementation:**
- Generate `docs/feed.json` during build with events array, timestamps, date range
- Generate `docs/feed.xml` in RSS 2.0 format
- Add CORS headers so any site can fetch client-side

**Effort:** Medium

---

## 9. Venue Link Enhancement

**Problem:** Venue names in the event listing don't link to the venue's own calendar. Users who want to see a venue's full schedule have no way to navigate there.

**Implementation:**
- Venue `calendar_url` data already exists in `config.py`
- Pass venue URL map to `generate_html.py`
- Render venue as a separate `<a>` tag when a venue URL is known

**Effort:** Low-Medium

---

## 11. JSON-LD Parser Consolidation

**Problem:** Three near-identical JSON-LD event parsers exist in `venue_scrapers.py`, `artifacts.py`, and `dice.py`. Bugs fixed in one copy aren't fixed in the others.

**Fix:** Create shared `src/jsonld_utils.py` with `parse_jsonld_events(soup) -> List[Event]`.

**Effort:** Medium

---

## 13. Extended Date Range Option

**Problem:** The 8-day window doesn't help people planning ahead. A 14-day view would cover next weekend too.

**Options:**
- `--days N` argument to `main.py`
- Two views: 8-day `index.html` + 14-day `upcoming.html`
- Client-side toggle in the HTML

**Effort:** Low-Medium

---

## 14. Genre / Category Tags

**Problem:** All events look the same — a jazz show and a punk show are indistinguishable.

**Implementation:**
- Add optional `genre` field to `Event` model
- Extract from Ticketmaster API classification data
- Infer from MUSIC_KEYWORDS matches
- Display as colored tag/pill

**Effort:** Medium

---

## 15. Price / Ticket Info

**Problem:** Users can't tell free shows from $50+ shows without clicking through.

**Implementation:**
- Add optional `price` field to `Event` model
- Extract from Ticketmaster `priceRanges` field
- Display as "Free", "$10", "$15-25" etc.

**Effort:** Medium

---

## 16. Event Deduplication Improvements

**Problem:** Events from multiple sources (Ticketmaster, scrapers, artifacts, admin) often describe the same show. Near-duplicates slip through — e.g., "Dale Watson" vs "Dale Watson & His Lone Stars". Artifact imports via Claude Vision are especially prone to creating duplicates.

**Implementation:**
- Fuzzy matching on artist names (token overlap or Levenshtein)
- Check artifact imports against existing DB events for same date+venue before inserting
- Admin UI: surface potential duplicates for manual merge/dismiss

**Effort:** Medium

---

## Priority

| # | Feature | Effort | Value | Status |
|---|---------|--------|-------|--------|
| 3 | Custom domain | Low | High | Pending — config only |
| 4 | Event feed (JSON/RSS) | Medium | High | Pending — unlocks website integration |
| 9 | Venue link enhancement | Low-Med | Medium | Pending |
| 11 | JSON-LD parser consolidation | Medium | Medium | Pending — code quality |
| 13 | Extended date range | Low-Med | Medium | Pending |
| 14 | Genre / category tags | Medium | Medium | Pending |
| 15 | Price / ticket info | Medium | Medium | Pending |
| 16 | Deduplication improvements | Medium | High | Pending |
