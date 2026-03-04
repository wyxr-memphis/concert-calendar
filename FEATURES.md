# Feature Requests — WYXR Memphis Concert Calendar

Planning doc for upcoming features.

---

## Pending Fixes & New Sources

### Scrapers to Fix
- **FedExForum** — generic scraper returning 0 events, page structure may have changed
- **Overton Park Shell** — generic scraper returning 0 events (may be seasonal)
- **Crosstown Arts** — generic scraper gets events but coverage is inconsistent

### New Venues to Add
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
- ~~Interactive Calendar~~ — 6-month lookahead, month navigation, text search, neighborhood chip filtering
- ~~Neighborhood Filtering~~ — Venues table with neighborhood mapping, admin UI management, merge duplicates
- ~~Extended Date Range~~ — Venue scrapers use 6-month range (SCRAPER_END_DATE) for interactive calendar
- ~~Nashoba Live~~ — Added with Elfsight scraper
- ~~Lafayette's Music Room~~ — Switched from broken generic to Elfsight scraper
- ~~Growlers~~ — Custom SeeTickets scraper at 901growlers.com
- ~~Graceland Soundstage~~ — Custom Wix scraper at gracelandlive.com/shows
- ~~Per-Source Scraper Status~~ — Expandable cards with run history, DB event counts, build timeline (moved from public page to admin)
- ~~B.B. King's~~ — Changed to manual_only (scraper was returning 0 events)

---

## 3. Custom Domain

**Problem:** The calendar lives at `concert-calendar.wyxr.org` (branded domain). ✅ Implemented!

**Steps:**
1. Choose a subdomain (e.g., `shows.wyxr.org`)
2. In DNS, add CNAME: `shows` -> `cname.vercel-dns.com`
3. In Vercel dashboard -> Domains -> add `shows.wyxr.org`
4. Vercel provisions SSL automatically

**Effort:** Config only, no code changes.

---

## ~~4. Event Feed (JSON / RSS) for Website Embedding~~ ✅

**Implemented:** RSS 2.0 feed at `concert-calendar.wyxr.org/feed.xml`. Generated automatically every build (2x daily) with the next 60 days of events. Each item includes artist, venue, date, time, price, genre, rich HTML content, image enclosures, and WYXR Presents/Pick badges. Used for WYXR app integration.

**Files:** `src/generate_rss.py`, integrated in `src/main.py` Step 7.

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

## 17. Email Signup (Mailchimp)

**Problem:** Visitors to the concert calendar have no way to subscribe for updates or newsletters. The WYXR Mailchimp list is already embedded on Concert.wyxr.org and should be surfaced here too.

**Implementation:**
- Add a compact Mailchimp signup form to the footer of `docs/index.html`
- Use the same Mailchimp list as Concert.wyxr.org (form action URL needs to be pulled from that page — format: `https://wyxr.us##.list-manage.com/subscribe/post?u=...&id=...`)
- Style to match the existing dark WYXR theme (yellow on black)
- Keep it minimal: email field + submit button, no extra fields

**Steps:**
1. Retrieve the Mailchimp form action URL from Concert.wyxr.org
2. Add the signup form HTML to `docs/index.html` footer area
3. Style inline with existing CSS variables

**Effort:** Low

---

## 18. Event Submission Form (Community Events)

**Problem:** Community members, promoters, and venues have no self-service way to submit events for consideration. Currently all events come from scrapers, the Ticketmaster API, or admin manual entry.

**What this looks like:**
- A public form (on the calendar page or a separate `/submit` page) where anyone can submit an event
- Fields: Artist/Event name, Venue, Date, Time, Ticket URL, Contact email (for follow-up)
- Submissions go to a moderation queue — admin reviews and approves before publishing
- Optional: email confirmation to submitter

**Implementation:**
- Add a `POST /api/events/submit` endpoint to the Flask API that writes to a `pending_events` table
- Add an admin review view at `/admin/pending/` to approve or reject submissions
- Add the submission form to the public calendar page (or a linked `/submit.html`)
- Send a simple confirmation email via SendGrid or similar (optional)

**Effort:** Medium

---

## 19. Sponsor Callout (Admin + Display)

**Problem:** No way to surface sponsors on the calendar or manage them through the admin.

**Specs TBD** — will define display placement, admin UI, rotation logic, and content fields when ready.

**Effort:** TBD

---

## Priority

| # | Feature | Effort | Value | Status |
|---|---------|--------|-------|--------|
| 17 | Email signup (Mailchimp) | Low | High | Pending — needs Mailchimp action URL from Concert.wyxr.org |
| 18 | Event submission form | Medium | High | ✅ Completed — /submit page + admin review |
| 3 | Custom domain | Low | High | Pending — config only |
| 4 | Event feed (RSS) | Medium | High | ✅ Completed — feed.xml for WYXR app |
| 9 | Venue link enhancement | Low-Med | Medium | Pending |
| 11 | JSON-LD parser consolidation | Medium | Medium | Pending — code quality |
| 14 | Genre / category tags | Medium | Medium | Pending |
| 15 | Price / ticket info | Medium | Medium | Pending |
| 16 | Deduplication improvements | Medium | High | Pending |
| 19 | Sponsor callout (admin + display) | TBD | High | Pending — specs TBD |
