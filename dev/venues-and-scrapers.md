# Venues & Scrapers

> Tripwires live in `CLAUDE.md`. This file is the detail behind them.

Source of truth is `VENUES` in `src/config.py`; each entry's `scraper` field selects the
fetcher. **Counts below drift — regenerate rather than trusting them:**

```bash
python3 -c "import sys;sys.path.insert(0,'.');from src.config import VENUES;print(len(VENUES))"
```

## Configured venues (28 at last count)

**Ticketmaster by venue ID (7)** — `ticketmaster_venue`: BankPlus Amphitheater at Snowden
Grove, Bluesville at Horseshoe, Cannon Center, FedExForum, Grind City Amphitheater, Radians
Amphitheater, Satellite Music Hall

**Custom scrapers (17):** Hi Tone, Minglewood Hall, Hernando's Hideaway, Growlers
(SeeTickets), Graceland Soundstage (Wix), Lafayette's Music Room + Nashoba (Elfsight),
Crosstown Arts, Crosstown Brewing Co., Flyway Brewing (Wix), Huey's (`sitewrench`, all
locations), Overton Park Shell (Squarespace), B.B. King's (Webflow), Blues City Cafe, Landers
Center, Orpheum Theatre, South Main Sounds

**Generic scraper (1)** — JSON-LD: Germantown Performing Arts Center

**Manual only (3):** Bar DKDC, B-Side Memphis, Hotel Pontotoc (see below)

**The Events Calendar API (0 active)** — `tribe_events` is implemented and correct, but the
only venue on it is currently blocked. See the Cloudflare note below.

Venue scrapers use the 6-month range (`SCRAPER_END_DATE`) for the interactive calendar.

## Permanently closed — never add

**Railgarten** and **Black Lodge** are closed. `REVIEW.md` §5 recommends both; that
recommendation is stale.

## The DB `venues` table is much larger than the configured set

~104 rows — it also holds venues created by Slack/artifact uploads and admin entries, which
have aliases but no scraper. **Those aliases are load-bearing for deduplication** — see
`dev/database.md`.

## Disabled sources — deliberately not in use

**Eventbrite, Bandsintown, DICE, Memphis Flyer,** and the old **Google Sheet** were all
removed. The sheet was replaced by the admin UI; the rest were dropped for coverage or
reliability. Don't re-add one without a reason that isn't "we don't have it yet."

## Scraper notes

- `is_music_event()` is bypassed for venue scrapers **except** `crosstown_arts` (mixed music +
  gallery); it also excludes titles containing "film".
- **`tribe_events` is the reusable win for WordPress venues.** The Events Calendar (the
  plugin formerly by Modern Tribe) publishes a paginated JSON API at
  `/wp-json/tribe/events/v1/events` — categories included, and it survives theme changes.
  Point `calendar_url` at any site running it. Spot it by `tribe-events` / `the-events-calendar`
  in the page source. (Crosstown Arts runs it too and still uses a bespoke HTML parser — a
  possible future simplification, untested.)
  Three opt-in filters exist because a hotel or bar calendar is not a pure music feed:
  `tribe_skip_categories` (Hotel Pontotoc tags buyouts `Private`), `tribe_own_venues` (the same
  calendar lists football watch parties at stadiums it doesn't own, which would otherwise
  publish under its name), and `tribe_music_only` (applies `is_music_event()`). Without all
  three, 23 of Hotel Pontotoc's 25 upcoming entries were noise.
  ⚠️ **Classify before stripping labels.** `_strip_billing_label` drops a leading
  `Live Music:` for display, but `is_music_event()` must run on the *raw* title — that label
  is the only music signal an artist-only name like "Spaceman's Dead Friends" carries, and
  stripping first silently drops the show.
  ⚠️ It sends `_TRIBE_HEADERS`, **not** the shared `HEADERS` — Hotel Pontotoc's WAF 403s the
  full Chrome user-agent on `/wp-json/` while allowing a plain self-identifying one.

### ⛔ Hotel Pontotoc is disabled — Cloudflare blocks the CI runner

Set to `manual_only` on 2026-09-01. The scraper itself is verified correct (25 found, 23
filtered, 2 real shows kept, run from a normal connection). **Two independent blocks exist:**

| Origin | User-agent | Result |
|---|---|---|
| normal connection | full Chrome UA | 403 |
| normal connection | `WYXR-Concert-Calendar/1.0` | 200 |
| GitHub Actions runner | `WYXR-Concert-Calendar/1.0` | **403** |

The first is a UA rule, solved by `_TRIBE_HEADERS`. The second is IP reputation on the runner
and **cannot be fixed from our side** — confirmed on two consecutive builds, so it is not a
fluctuating bot score. Things already ruled out: WordPress's alternate `?rest_route=` form
behaves identically (so the rule is not path-based on `/wp-json/`), and there is **no HTML
fallback** — `hotelpontotoc.com/events/` is a JS shell containing zero event data, no
server-rendered cards and no `Event` JSON-LD.

**To re-enable:** ask the venue to add a Cloudflare WAF skip rule for our user-agent, then
change `"scraper": "manual_only"` back to `"tribe_events"` in `src/config.py`. Nothing else
needs to change. An untested alternative is moving this one fetch to the Render backend, whose
egress IP may not be blocked — that has never been probed.

Until then Pontotoc arrives via Slack flyers, which is how its five existing events got there.
- **Elfsight widget pattern** — a JSON API at `core.service.elfsight.com/p/boot/` returns
  structured events. Reusable across any Elfsight-backed site (Lafayette's, Nashoba).
- **`ticketmaster_venue` is the cheap win** for any Live Nation / Ticketmaster room: a
  `livenation.com/venue/<ID>/…` URL exposes the ID. Add a `VENUES` entry plus a
  row to the `_SEED_VENUES` list inside `_seed_venues_if_empty()` (`backend/db.py`) and no
  page scraping is needed at all. Despite the function name, `_SEED_VENUES` rows are
  upserted on **every** `init_db()`, not only when the table is empty. New venues get a
  neighborhood only if present in the DB `venues` table at save time.

Scraper source files:
- `src/sources/ticketmaster.py` — Ticketmaster Discovery API
- `src/sources/venue_scrapers.py` — custom scrapers
- `src/sources/artifacts.py` — Claude Vision for image processing

## Runbook: add a new venue

1. Add to `VENUES` in `src/config.py`
2. Choose a scraper type (generic, custom, or `manual_only`)
3. Seed the venue in `backend/db.py` → `_seed_venues_if_empty()` → the `_SEED_VENUES` list
4. Test with `python -m src.main --dry-run`
