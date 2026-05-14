# Feature Requests — WYXR Memphis Concert Calendar

Planning doc for upcoming features.

---

## Pending Fixes & New Sources

### New Venues to Add
- **Beale Street venues** — Blues City Cafe, Rum Boogie Cafe, Silky O'Sullivan's, Alfred's on Beale (nightly live music, not currently tracked)
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
- ~~Interactive Calendar~~ — 6-month lookahead, month navigation, text search, neighborhood chip filtering
- ~~Neighborhood Filtering~~ — Venues table with neighborhood mapping, admin UI management, merge duplicates
- ~~Extended Date Range~~ — Venue scrapers use 6-month range (SCRAPER_END_DATE) for interactive calendar
- ~~Nashoba Live~~ — Added with Elfsight scraper
- ~~Lafayette's Music Room~~ — Switched from broken generic to Elfsight scraper
- ~~Growlers~~ — Custom SeeTickets scraper at 901growlers.com
- ~~Graceland Soundstage~~ — Custom Wix scraper at gracelandlive.com/shows
- ~~Per-Source Scraper Status~~ — Expandable cards with run history, DB event counts, build timeline (moved from public page to admin)
- ~~B.B. King's~~ — Changed to manual_only (scraper was returning 0 events)
- ~~Overton Park Shell~~ — Custom Squarespace scraper (`_parse_overton_shell()` in venue_scrapers.py)
- ~~Email Signup / Mailchimp (#17)~~ — "📧 Subscribe" button in header opens dark modal with Mailchimp iframe form (wyxr.us19.list-manage.com). sessionStorage tracks signed-up state.
- ~~Event Submission Form (#18)~~ — `/submit.html` public form + `POST /api/submissions` endpoint + admin review queue
- ~~Sponsor Callout (#19)~~ — Inline promo cards between day sections + Calendar Sponsor banner above event list. Full admin UI in Sponsors tab. DB tables: `sponsors`, `calendar_sponsor`.

---

## 3. Custom Domain

**Status: ✅ Implemented** — calendar lives at `concert-calendar.wyxr.org`.

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

**Problem:** Two near-identical JSON-LD event parsers exist in `venue_scrapers.py` (`_try_jsonld` / `_jsonld_to_event`) and `artifacts.py` (`_parse_jsonld_event`). Bugs fixed in one copy aren't fixed in the other.

**Fix:** Create shared `src/jsonld_utils.py` with `parse_jsonld_events(soup) -> List[Event]`.

**Effort:** Medium

---

## 14. Genre / Category Tags

**Problem:** All events look the same — a jazz show and a punk show are indistinguishable.

**Implementation:**
- `genre` field already exists in the `events` DB table (schema.sql) but is not in the Python `Event` model or UI
- Add `genre` to the `Event` dataclass and `db.py` queries
- Extract from Ticketmaster API classification data
- Infer from MUSIC_KEYWORDS matches
- Display as colored tag/pill

**Effort:** Medium

---

## 15. Price / Ticket Info

**Problem:** Users can't tell free shows from $50+ shows without clicking through.

**Implementation:**
- `ticket_price` field already exists in the `events` DB table (schema.sql) but is not in the Python `Event` model or UI
- Add `ticket_price` to the `Event` dataclass and `db.py` queries
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
| 9 | Venue link enhancement | Low-Med | Medium | Pending |
| 11 | JSON-LD parser consolidation | Medium | Medium | Pending — code quality |
| 14 | Genre / category tags | Medium | Medium | Pending |
| 15 | Price / ticket info | Medium | Medium | Pending |
| 16 | Deduplication improvements | Medium | High | Pending |
