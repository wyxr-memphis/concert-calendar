# Venues & Scrapers

> Tripwires live in `CLAUDE.md`. This file is the detail behind them.

Source of truth is `VENUES` in `src/config.py`; each entry's `scraper` field selects the
fetcher. **Counts below drift — regenerate rather than trusting them:**

```bash
python3 -c "import sys;sys.path.insert(0,'.');from src.config import VENUES;print(len(VENUES))"
```

## Configured venues (30 at last count)

**Ticketmaster by venue ID (7)** — `ticketmaster_venue`: BankPlus Amphitheater at Snowden
Grove, Bluesville at Horseshoe, Cannon Center, FedExForum, Grind City Amphitheater, Radians
Amphitheater, Satellite Music Hall

**Custom scrapers (16):** Hi Tone, Minglewood Hall, Hernando's Hideaway + Growlers
(`eventim_whitelabel` — see below), Graceland Soundstage (Wix), Lafayette's Music Room + Nashoba
(`elfsight` — API only, no page fetch), Crosstown Arts (`dice_promoter` — see below), Flyway
Brewing (Wix), Society Memphis (Wix Events), Huey's (`sitewrench`, all locations), Overton Park
Shell (Squarespace), Blues City Cafe, Landers Center (`plain_user_agent` — see below), Orpheum
Theatre, South Main Sounds

**Generic scraper (1)** — JSON-LD: Germantown Performing Arts Center

**Multi-venue (1)** — `memphis_symphony`: Memphis Symphony Orchestra (see below)

**Manual only (3):** Bar DKDC, B-Side Memphis, B.B. King's (no calendar left to scrape — see below)

**The Events Calendar API (2)** — `tribe_events`: Memphis Listening Lab, and Hotel Pontotoc
through the Cloudflare proxy fallback (`requires_proxy` — see below).

**Homepage cards (1)** — `mosh`: Museum of Science & History, laser shows and music films only
(`include_patterns` — see below).

Venue scrapers use the 6-month range (`SCRAPER_END_DATE`) for the interactive calendar.

## Permanently closed — never add

**Railgarten** and **Black Lodge** are closed. `REVIEW.md` §5 recommends both; that
recommendation is stale.

**Crosstown Brewing Co.** closed in October 2026 (removed from `VENUES` and `_SEED_VENUES`
2026-10-28; its `crosstown_beer` parser is deleted). Its DB `venues` row stays for the
history, and its last events page had not been updated since Oct 17.

**B.B. King's Blues Club** is open but has **no calendar**: its Webflow site was rebuilt and
`/memphis/music` lists four house bands with no dates while `/memphis/events` is private-event
rentals. The `bbkings` parser returned 0 in all 40 October builds and is deleted; the venue is
`manual_only`. Don't write a new scraper until the site publishes dated listings again.

## The DB `venues` table is much larger than the configured set

~104 rows — it also holds venues created by Slack/artifact uploads and admin entries, which
have aliases but no scraper. **Those aliases are load-bearing for deduplication** — see
`dev/database.md`.

## Disabled sources — deliberately not in use

**Eventbrite, Bandsintown, DICE, Memphis Flyer,** and the old **Google Sheet** were all
removed. The sheet was replaced by the admin UI; the rest were dropped for coverage or
reliability. Don't re-add one without a reason that isn't "we don't have it yet."
(The DICE source that was removed read the city-wide *browse* page, a JS shell. A single
promoter's page is server-rendered and is a different thing — see `dice_promoter` below.)

## Scraper notes

- `is_music_event()` is bypassed for venue scrapers. Mixed calendars filter some other way:
  `tribe_events` has per-venue opt-in filters (below), and `society` has its own stricter
  filter — see below.
- **`tribe_events` is the reusable win for WordPress venues.** The Events Calendar (the
  plugin formerly by Modern Tribe) publishes a paginated JSON API at
  `/wp-json/tribe/events/v1/events` — categories included, and it survives theme changes.
  Point `calendar_url` at any site running it. Spot it by `tribe-events` / `the-events-calendar`
  in the page source.
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

### Cloudflare proxy fallback — ScraperAPI (added 2026-10-28)

Four venues' sites answer 403 to every build because Cloudflare scores GitHub's runner IPs as
bots (and Render's, see below), while the identical request works from a home connection.
Asking each venue for a WAF allowlist needs a human at the venue, so instead
`http_utils.get_with_retry` re-fetches a **Cloudflare-blocked** response once through
[ScraperAPI](https://docs.scraperapi.com/), which fetches from residential IPs and returns the
target's body and status as-is. Rules, all in `src/http_utils.py`:

- **Only a response that looks like a Cloudflare block is proxied** — 403/429/503 with a
  `cf-mitigated` header, a `server: cloudflare` header, or a challenge-page body. A healthy
  page, an origin 403, Landers' 406, a 404 never spend a credit. `is_cloudflare_block()` is
  the gate; `scripts/test_cloudflare_fallback.py` pins it.
- **Our own headers are forwarded** (`keep_headers=true`). Pontotoc's WAF 403s a browser UA on
  `/wp-json/` and allows the plain self-identifying one, so the UA that works directly is the
  UA the proxy must present. Don't "improve" success rates by dropping that.
- **Budget:** `PROXY_BUDGET_PER_RUN = 40` fetches per build. The free plan is 1,000 credits a
  month and a plain fetch costs one; at ~5 builds a day a venue costs ~150–300 credits a month,
  so the budget exists to stop a site-wide outage burning the month in a day, not for normal
  use. Proxy hits print `[proxy] …` lines in the build log.
- **No key, no change:** with `SCRAPERAPI_KEY` unset the blocked response is returned
  untouched. A venue that *only* works through the proxy sets `"requires_proxy": True` in
  `VENUES`; `fetch_individual` then reports it as *skipped* (a build-log row with the reason,
  `success=True`) rather than failing the build. Hotel Pontotoc is the one such venue.
- The key lives in GitHub Secrets as `SCRAPERAPI_KEY` and is passed in `daily.yml`. Local
  `.env` may hold one too; without it Pontotoc is skipped locally, which is fine.
- `new_session()` sessions (Eventim) do **not** get the fallback — that host serves us; its
  problem is the waiting room, handled by polling (see the Eventim section).

Crosstown Arts, Growlers and Hernando's stay on their third-party sources (DICE, Eventim);
the fallback is there if those ever block too, since every venue fetch goes through
`get_with_retry`.

### Hotel Pontotoc — Cloudflare blocks the CI runner; read through the proxy

`manual_only` from 2026-09-01 to 2026-10-28, now `tribe_events` + `requires_proxy`. The
scraper itself is verified correct (25 found, 23 filtered, 2 real shows kept, run from a normal
connection; 17/15/2 on 2026-10-28). **Two independent blocks exist:**

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

Relaying the fetch through the Render backend was probed on 2026-10-27 and **does not work** —
Render's egress IP is challenged too (see the Growlers/Hernando's section). The proxy fallback
above is what re-enabled it: the direct `/wp-json/` request 403s from CI, `get_with_retry`
sees a Cloudflare block and refetches through ScraperAPI with `_TRIBE_HEADERS`. One or two
pages per build. Without `SCRAPERAPI_KEY` the venue is skipped and Pontotoc arrives via Slack
flyers, which is how its first five events got there.

### Crosstown Arts — Cloudflare blocks the runner, so it reads DICE instead

crosstownarts.org's own calendar worked until the 2026-09-07 build and has returned 403 on
every build since 2026-09-08. The HTML parser was replaced by `tribe_events` on 2026-10-26
(the API returns the whole six-month window where the list view is one page of 8) and the
result matrix is the Pontotoc one again:

| Origin | Request | Result |
|---|---|---|
| normal connection | HTML page, full Chrome UA (via `requests`) | 200 |
| normal connection | `/wp-json/tribe/events/v1/events`, `WYXR-Concert-Calendar/1.0` | 200 |
| normal connection, after ~6 probes in a few minutes | same API request | **403** challenge |
| GitHub Actions runner | HTML page (every build since 2026-09-08) | **403** |
| GitHub Actions runner | API, `WYXR-Concert-Calendar/1.0` (build 40405466930) | **403** |

The 403 body is Cloudflare's "Just a moment…" managed challenge, and a normal connection being
challenged after a short burst shows it is a **bot-score / IP-reputation rule, not a UA or path
rule** — the Memphis Listening Lab's identical `tribe_events` fetch succeeded in the same build.
The working `tribe_events` config (room categories to skip, a `\bfilm\b` title filter) is in
commit `28ec11a` should the block ever lift, or should Crosstown add a WAF skip rule for the
`WYXR-Concert-Calendar/1.0` user-agent.

**Since 2026-10-26 Crosstown Arts is scraped from its DICE promoter page instead**
(`dice_promoter`, `https://dice.fm/promoters/crosstown-arts-y56r`). How it works:

- The promoter page is a Next.js app that server-renders its entire upcoming list into the
  `__NEXT_DATA__` script: name, start time with zone, room (`The Green Room at Crosstown Arts`
  / `Crosstown Arts Theater`, both already aliases), square artwork and the event id. No JS
  needed, no pagination (`load_more` was false at 27 events).
- **The list carries no event type, and Crosstown sells its film series through the same
  promoter under bare titles** ("Creepshow", "The Holdovers", "Seconds") that no keyword
  filter can catch. Each event's own page has Schema.org JSON-LD whose `@type` is
  `ScreeningEvent` for a film and `MusicEvent` for a show, so the fetcher reads one detail page
  per in-window event and drops `ScreeningEvent` (`dice_skip_types` to override). That is
  ~25 requests a build; DICE served 27 in a row without a challenge. A failed detail fetch
  keeps the event — a stray film beats a silently missing concert.
- The detail fetch also upgrades the link to DICE's slugged canonical URL, which is the ticket
  link. Cancelled/postponed statuses are skipped.
- DICE lists ticketed shows only. The free recurring listings the WordPress calendar had
  ("The Mystic" monthly, Resident Artist Talks, Crafts & Drafts) are not on it — those were
  never concerts anyway.
- It sends the same plain self-identifying user-agent as `tribe_events`.

### Growlers + Hernando's Hideaway — Cloudflare blocks CI *and* Render, so they read Eventim

Both venues' own sites (901growlers.com's SeeTickets widget, Hernando's WordPress calendar)
worked in the 2026-10-07 11:36 UTC build and have 403'd on every build since 21:42 UTC that
day — the Pontotoc / Crosstown pattern again. On 2026-10-27 the fetch was probed from the
Render backend's own shell to test relaying CI fetches through it
([`spec-render-fetch-relay.md`](spec-render-fetch-relay.md)):

| Origin | Growlers | Hernando's | Pontotoc API | Crosstown API |
|---|---|---|---|---|
| normal connection | 200 | 200 | 200 | 200 → 403 after a burst |
| GitHub Actions runner | **403** | **403** | **403** | **403** |
| Render backend (`concert-calendar-api` shell) | **403** | **403** | **403** | **403** |

Render's outbound IPs are shared with other customers and score as badly as GitHub's, so
**the relay is dead — don't build it.** The Cloudflare proxy fallback (above) is the answer
that worked.

**Since 2026-10-27 both venues are scraped from their ticketing organizer pages instead**
(`eventim_whitelabel`): `wl.eventim.us/GrowlersMemphisTN` and `wl.eventim.us/HernandosHideAWay`.
SeeTickets US rebranded as Eventim; every `wl.seetickets.us` link 302s there, and the
`afflky=` key on a stored ticket link is the organizer slug. The host is Cloudflare-fronted
too, but serves the plain `WYXR-Concert-Calendar/1.0` UA. How it works (full notes on
`_fetch_eventim_whitelabel`):

- Page one holds 12 events. Further pages come from `wafform.aspx?…&AJAX=1&_lfv=<offset>`,
  which returns an **empty 200** without the session cookie page one sets — hence a private
  `http_utils.new_session()` per venue. `FetchSize` above 12 is ignored. The `ProfileID` the
  AJAX URL needs is read off page one's pager links.
- The year is only in the buy button's `aria-label` ("… on November 05 2026").
- No time on the cards. Each event page's JSON-LD `startDate` supplies it, but Eventim runs a
  Cloudflare **waiting room** ("You're in line!") during big on-sales — on 2026-10-27 every
  event page was queued, and on 2026-10-28 the *organizer* page was queued from a home
  connection too, after failing 2 of its first 3 CI builds. Since 2026-10-28 `_eventim_get`
  **polls through the queue**: the waiting room sets a `__cfwaitingroom` cookie and asks for a
  refresh, and a session that keeps re-requesting the same URL is admitted when its turn comes.
  One budget of `_EVENTIM_QUEUE_POLLS` (6) per venue, shared by the organizer page and the event
  pages, at the page's `Refresh` interval (capped at 30s) or 20s. A queue that outlasts the
  budget fails the organizer page loudly, as before, or stops the event-page lookups for the run
  with the event keeping its card data; the build's `COALESCE` keeps any time already stored.
- **Where the time is on an event page:** JSON-LD `startDate` on most pages, and the hero's
  `<time itemprop="startDate" datetime="…">` on all of them — `_eventim_start` reads either.
  A **recurring series page** (Hernando's weekly Open Jam Night) has no JSON-LD and a
  date-range hero whose datetime is `T00:00`; that midnight is a placeholder and is treated
  as no time. Until 2026-10-28 one such page switched off time lookups for every event after
  it, and since Hernando's first card *is* the weekly jam, no Hernando's or Growlers show
  ever got a time. Now only a queue page stops the lookups.
- **Titles come only from the cards, never the event page**, so they can't flip between
  builds. The old Growlers scraper used SeeTickets' headliner field ("Fika, EOS"); Eventim's
  billing is the full name ("Cohesion: Fika & EOS w/ …"), so 8 stored Growlers rows were
  retitled on the switch, paired with their new listing by the event id in `ticket_url`.
- Hernando's: 22 events on Eventim against ~33 on the venue's site — free/no-ticket nights
  that aren't sold through Eventim don't appear. Stored rows for those stay until they pass.
- The old `growlers` / `hernandos` HTML parsers are deleted; they're in git before this change.

### Memphis Listening Lab — `tribe_events` scraper live

Added 2026-10-24; scraper confirmed and activated 2026-10-24. The Lab (Crosstown Concourse,
Suite 269) is mostly WYXR Stereo Sessions and HiFi Friday listening sessions, which also
arrive as Slack flyers. Platform: WordPress + The Events Calendar REST API
(`/wp-json/tribe/events/v1/events`), confirmed via `x-tec-api-root` header and 8 real
upcoming events. No categories or venue fields, so no filtering options (`tribe_skip_categories`,
`tribe_own_venues`, `tribe_music_only`) are needed.

- **Alias `wyxr stereo sessions / mempho listening lab`** is load-bearing: seven Slack rows
  were filed under that name and never deduped against the Lab's own rows. It is in
  `src/config.py` and `_SEED_VENUES`, but the seed is skipped if a `Memphis Listening Lab` row
  already exists, so it must also be added through Admin → Venues, and then the
  `dedup_key` backfill re-run (`dev/database.md`). Most of those seven still differ from
  their twins by OCR title typos, so the alias alone will not merge them.
- **`is_music_event` would drop these listings** ("HiFi Friday", "Stereo Sessions: …" carry
  no genre word), so `MUSIC_KEYWORDS` now includes `stereo session`, `hifi friday`,
  `listening party` and `listening session`. Not needed by a `manual_only` venue, but needed by
  any scraper that applies the filter (e.g. `tribe_music_only`).
- **Crosstown Arts overlap: none so far.** None of the 71 `scraper:crosstown_arts` rows in the
  2026-10-24 snapshot matches a Listening Lab show on the same date. crosstownarts.org does
  have a `Memphis Listening Lab` event category, so the Crosstown Arts scraper skips it —
  otherwise a Lab show listed there would be double-sourced under the wrong venue.

### Memphis Symphony Orchestra — the one scraper that is not a venue

Added 2026-09-02. The symphony owns no hall, so it is the only source whose events are
**spread across venues**: a season plays the Cannon Center, Scheidt Family PAC, the Orpheum
and its Halloran Centre, GPAC's Grove, the Dixon's gardens, and three churches for *Handel's
Messiah*. It sits in `VENUES` only because that is what dispatches a scraper —
`_fetch_memphis_symphony` sets each event's venue from that listing's own
`location.addressTitle`, and `venue_info["name"]` supplies just the source tag and the
fallback venue.

**Filing it under one "Memphis Symphony Orchestra" pseudo-venue was rejected:** the venue is
the field a DJ acts on, and a show at the Cannon Center could then never dedup against that
venue's own scraper. Eight of the season's Cannon Center dates are absent from Ticketmaster
(the orchestra sells through its own box office), so excluding already-scraped halls was
rejected too — it would drop real shows.

- **Squarespace pattern, reusable.** Any Squarespace collection page returns its backing JSON
  with `?format=json`. An events collection splits it into `upcoming` / `past`; read only
  `upcoming`. `?offset=` pages *backwards* into past seasons, so there is no pagination to do.
- ⚠️ **Timestamps are epoch milliseconds and must be read in `America/Chicago`.** A 7:30 PM
  concert is 00:30 UTC, so a naive `fromtimestamp()` files the entire season one day late on
  the UTC GitHub Actions runner while looking correct on a Central laptop.
- **`is_music_event()` must NOT be applied** — it reads no music keyword in "TCHAIKOVSKY'S
  4TH" and would drop the real concerts. The noise here is the Memphis Symphony League's
  social calendar (luncheons at private clubs, a holiday tea at the Peabody), so
  `_MSO_EXCLUDE_KEYWORDS` names what to remove instead. Verified against all 57 published
  titles: it catches the two fundraisers and nothing else.
- **Three title normalizations, each load-bearing for dedup, not cosmetics:**
  `_smart_title_case` de-caps the season (`str.title()` cannot be reused — it yields
  "Handel'S Messiah", and the apostrophe is U+2019, not ASCII); `MSO` is expanded because
  GPAC bills the same show as "Memphis Symphony Big Band"; and `_strip_venue_restatement`
  drops a trailing "at <hall>" that only restates the venue column. Without the last one the
  intra-scrape fuzzy pass merges the pair, keeps the longer title, and the result no longer
  matches the row already stored — a permanent duplicate.
- **Aliases added for this source:** "The Grove - GPAC" → GPAC (the Grove is GPAC's outdoor
  lawn stage), in both `src/config.py` and `_SEED_VENUES`.

⚠️ **Known limitation, not a bug to fix here.** A matinee and an evening performance of the
same programme on one day (*Home Alone in Concert*, 2026-11-28, 1 PM and 6:30 PM) share one
`title|venue|date` dedup key and collapse to a single listing — the matinee wins. Widening
the key is a cross-cutting change to three call sites plus a backfill; see `dev/database.md`.

⚠️ The **Halloran Centre and Crosstown Theater each exist twice** in the data model — as their
own row in the DB `venues` table *and* as an alias of the Orpheum / Crosstown Arts in
`src/config.py`. This predates the symphony scraper and was deliberately left alone; a config
alias for the Halloran's full formal name was reverted during this work because the DB row
already claims that exact string. Resolve it before adding another scraper that books either.

### Museum of Science & History (MoSH) — homepage cards, laser shows and music films only

Added 2026-10-29, working from 2026-10-30. What DJs want from MoSH is the AutoZone Sharpe
Planetarium's laser concerts (Laser Rock, Laser Live, "Laser <band>") and any music film on the
giant screen; the rest of its calendar is science shows, camps and Lichterman/Coon Creek events.

- **The full calendar is a SiteWrench JS widget** (`/calendar/`, site 2920, page part 461399):
  the HTML holds no events, and the JSON API it calls needs the token embedded in the page.
  Lifting that token to call the API directly was **declined** (2026-10-30) — don't build
  on it. It is not WordPress's The Events Calendar either: the first version assumed so and
  404'd on `/wp-json/tribe/…` in its first build. Event detail links
  (`/mosh-calendar-page/event/<id>`) only 301 back into the widget.
- **The homepage server-renders ~10 upcoming events** as cards linking to
  `/mosh-calendar-page/event/<id>`, each with the room (`.preheader`), title
  (`.excerpt-title`) and `Oct 30, 2026 | 7PM - 8PM` (`.excerpt-date`). Five are a featured
  strip about two weeks deep — every laser show was in it on 2026-10-30 — and five are
  today's shows. `_parse_mosh` reads those; twice-daily builds pick each show up as it is
  featured. **Limitation:** a show more than ~2 weeks out, or one MoSH doesn't feature,
  won't appear until it does.
- **`include_patterns`** (shared with `tribe_events`) keeps only listings whose title or
  room matches a list of **whole-word** regexes (`laser`, `concert`, `music`, `jazz`, `elvis`,
  `stax`…). `is_music_event()` is unusable here: it matches substrings ("Rocket" → rock,
  "Museum Tour" → tour) and passes any title containing a venue alias.
  `scripts/test_mosh_scraper.py` pins the live strip of 2026-10-30 (3 kept, 7 dropped).
  A day where nothing matches reports `found=N, filtered=N` with no error, like Landers.
- **No bare `mosh` or `pink palace` alias**, for the same alias-in-title reason ("Mosh
  Madness" is a Growlers show).
- **`Pink Palace Giant Screen` is a separate DB `venues` row** (from a flyer import) and is
  deliberately not claimed as an alias — the Halloran/Crosstown double-row problem. Merge it in
  Admin → Venues if it should be MoSH, then re-run the `dedup_key` backfill.
- **Overton Park Shell also lists "MOSH Laser Live Concert Series"** (Shell on Wheels) on the
  same nights, so a Laser Live show appears under both venues; the venue differs, so dedup
  won't merge them.
- **Music documentaries billed by title alone** match no keyword and are missed. Add a
  pattern, or they arrive via Slack flyers.

### Society Memphis — Wix Events, filtered to music

Added 2026-09-30. Society is a skatepark + coffee shop at 583 Scott St whose calendar
(`societymemphis.com/event-list`) mixes shows with skate sessions, comedy, gaming tournaments,
cosplay, RC drifting and fingerboard jams. `_society_is_music` is a **denylist**, and it drops a
listing only when its title or Wix category:

1. hits `_SOCIETY_EXCLUDE_KEYWORDS` (markets, chess, wrestling, gaming, cosplay, drifting,
   fingerboard…);
2. contains the **whole word** "skate"/"skating". It's whole-word so that "Xavier Wulf Skatepark
   Popout" (a rapper's show) survives while "Saturday Skate School" does not;
3. hits a generic `EXCLUDE_KEYWORDS` word (comedy, trivia, yoga…) with no `MUSIC_KEYWORDS`
   word alongside.

⚠️ **Don't turn this back into "require a music word."** The first version did that, and
against the live calendar it dropped Encircled Throne, Phases Psych Fest, Xavier Wulf and
Zynical Presents. Society bills its shows by artist name alone, with empty descriptions, so a
positive test cannot see them. A new kind of non-music event means one new denylist word.
`scripts/test_society_scraper.py` pins every title that was on the live calendar that day.

The name is `Society Memphis Skatepark and Coffee` because the DB row that Slack uploads
already created uses it. Renaming it would orphan those rows' dedup keys.

- **Wix Events pattern, reusable.** `_wix_warmup_events()` reads the server-rendered
  `wix-warmup-data` blob under app id `140603ad-…` (shared by Flyway and Society);
  `_wix_event_start()` converts its UTC `startDate` to Central. Event pages live at
  `/event-details/<slug>` on a default Wix Events site (Flyway customized theirs to `/events/`).
- **Elfsight widget pattern** — a JSON API at `core.service.elfsight.com/p/boot/` returns
  structured events. Reusable across any Elfsight-backed site (Lafayette's, Nashoba).
  `_fetch_elfsight_venue` calls the API directly and **never fetches the venue page** — the
  widget id is in config and the page holds nothing else. Until 2026-10-28 the dispatcher
  fetched the page first anyway, and Cloudflare 403'd lafayettes.com in 8 of 40 builds while
  the API call that followed never failed.
- **Per-venue user-agent** — `"plain_user_agent": True` in `VENUES` sends `PLAIN_HEADERS` (the
  self-identifying `WYXR-Concert-Calendar/1.0` UA) instead of the Chrome `HEADERS`.
  landerscenter.com answers **406** to the Chrome UA and 200 to the plain one; nothing else in
  the header set matters (tested header by header 2026-10-28). That 406 hid behind "0 events
  parsed" for 27 of 40 builds. Landers' parser also now returns a non-music count, so an
  all-hockey month reports `found=12, filtered=12` with no error instead of a false
  "page structure may have changed".
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
