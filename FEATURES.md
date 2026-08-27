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
- ~~Event Submission Form (#18)~~ — `/submit.html` public form + `POST /api/submissions` endpoint + admin review queue. Optional flyer upload (2026-07-30): the browser downscales to 1600px, the server re-encodes and holds the bytes in Postgres, and the image reaches Cloudinary **only on approval** — so anonymous submissions can't consume the free-tier quota. Rate limited to 5/hour per hashed IP.
- ~~Sponsor Callout (#19)~~ — Inline promo cards between day sections + Calendar Sponsor banner above event list. Full admin UI in Sponsors tab. DB tables: `sponsors`, `calendar_sponsor`.
- ~~iCal / webcal Subscribe Feed~~ — `docs/calendar.ics` (180-day window), generated each build by `src/generate_ics.py`, advertised as `webcal://concert-calendar.wyxr.org/calendar.ics`. UTC instants (no VTIMEZONE), UIDs shared with the modal's per-event export.
- ~~Per-Event Deep Links + OG Unfurls~~ — `#event=<id>` opens a show's modal (Back closes it); `/e/<id>` is a server-rendered permalink page with per-event `og:` tags and `MusicEvent` JSON-LD, proxied through Vercel to Render. "Copy link" button in the modal.
- ~~SEO Basics~~ — `MusicEvent` JSON-LD on `thisweek.html` (server-rendered, so crawlable), `WebSite`/`RadioStation` on the homepage plus a client-injected `ItemList`, `sitemap.xml` + `robots.txt`, `<link rel="alternate">` feed discovery, `<h1>` and a skip link.

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

**Status update (2026-08-20):** largely addressed. Event identity is now the shared
`compute_dedup_key` (`src/models.py`), stored as a column and enforced by the partial unique
index `idx_events_dedup_key`, with every dedup path canonicalizing the venue through the DB
`venues` table. What remains of this item is the *fuzzy* half — near-duplicate artist names
("Dale Watson" vs "Dale Watson & His Lone Stars") and an admin UI to review them.

---

## New Since the Roadmap

Pulled from [`REVIEW.md`](REVIEW.md) — the August 2026 full-codebase review, which carries a
per-item status layer and the detailed reasoning behind these (venue-by-venue scraper
approach in its §5, Instagram feasibility in its §6). Still pending:

- **New venues** — Lamplighter Lounge and Young Avenue Deli. Neither is in `src/config.py`
  or `_SEED_VENUES`; Lamplighter already has rows in the DB from Slack uploads but no
  scraper, so its coverage depends on someone photographing a flyer.
  ⚠️ **Railgarten and Black Lodge are permanently closed** (confirmed 2026-08-20) — do not
  add them. `REVIEW.md` §5 recommended both before they closed. Neither has any events or a
  `venues` row in the database, so nothing needs cleaning up.
- **"Tonight" Slack post** — the bot already has `chat:write` in the channel; a morning
  message listing tonight's shows. Highest value per line of code.
- **Weekly email digest** — Mailchimp audience and this-week data both exist.
- **Instagram posts ingestion** — ⛔ **abandoned 2026-08-27** (tested, then dropped).
  The Meta app exists and its token authenticates, but `business_discovery` returns
  `(#10) Application does not have permission for this action` for every account, our own
  included. It needs **Advanced Access** to `instagram_basic`, which only Meta App Review
  grants — and review expects a per-user OAuth consent flow this tool does not have.
  Dropped because the Slack screenshot pipeline already covers these venues: this would
  have removed a DJ's screenshot step, not added a capability. See `REVIEW.md` §6 for the
  full finding, and `scripts/check_instagram_access.py` to re-test in one command if Meta's
  policy changes. Stories were never automatable either.
- **Remaining security-audit items (issue #15)** — security headers (no CSP/HSTS/
  X-Frame-Options), `app.run(debug=True)`, magic-byte MIME validation, Slack webhook
  processing when the signing secret is unset.
- **Embeddable widget** for wyxr.org; **visual unification** of `thisweek.html` with the
  slate palette; **accessibility** beyond the h1/skip-link pass.

---

## Priority

| # | Feature | Effort | Value | Status |
|---|---------|--------|-------|--------|
| 9 | Venue link enhancement | Low-Med | Medium | Pending |
| 11 | JSON-LD parser consolidation | Medium | Medium | Pending — code quality |
| 14 | Genre / category tags | Medium | Medium | Pending |
| 15 | Price / ticket info | Medium | Medium | Pending |
| 16 | Fuzzy near-duplicate merge UI | Medium | Medium | Pending — exact dedup shipped |
| — | New venues (Lamplighter, Young Ave Deli) | Medium | High | Pending |
| — | "Tonight" Slack post | Low | Medium | Pending |
| — | iCal subscribe feed | Low-Med | High | ✅ Shipped 2026-08-20 |
| — | Per-event deep links + OG unfurls | Medium | High | ✅ Shipped 2026-08-20 |
| — | SEO basics (JSON-LD, sitemap, feed links) | Low | High | ✅ Shipped 2026-08-20 |
