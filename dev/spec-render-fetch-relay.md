# Spec: relay scraper fetches through Render for Cloudflare-blocked venues

**Status: abandoned 2026-10-27 — Step 0 failed.** All four probes returned 403 from the
Render backend's shell, so Render's egress IP is blocked like GitHub's and the relay would
not help. Growlers and Hernando's now scrape their Eventim ticketing pages instead (see
`dev/venues-and-scrapers.md`). Kept for the reasoning and the evidence; don't build it.

## Problem

Cloudflare serves GitHub Actions runners a managed challenge ("Just a moment…", HTTP 403) on
a growing set of venue sites. The same scraper code returns 200 from a residential connection
every time, so the sites and the parsers are fine — it is the runner's shared IP reputation.

| Venue | Site | Blocked since (build) | Current state |
|---|---|---|---|
| Hotel Pontotoc | hotelpontotoc.com | 2026-09-01 | `manual_only`; `tribe_events` config verified but idle |
| Crosstown Arts | crosstownarts.org | 2026-09-08 | worked around — scraped from DICE since 2026-10-26 |
| Growlers | 901growlers.com | 2026-10-07 21:42 UTC | **dark** — 30 events in the last good build |
| Hernando's Hideaway | hernandoshideawaymemphis.com | 2026-10-07 21:42 UTC (same build) | **dark** — 36 events in the last good build |

Growlers and Hernando's have no alternative source: Growlers is a SeeTickets embed on the
venue's own domain, Hernando's is its own WordPress theme. Both went dark in the same build,
and nobody noticed for three weeks (see "Follow-ups"). Any other Cloudflare-fronted venue can
flip the same way.

**Why it is IP reputation and not something we send** (details in
`dev/venues-and-scrapers.md`):

- Same code, same headers: runner 403, laptop 200 — for the HTML page *and* the
  `/wp-json/tribe/` API, with both the Chrome UA and the plain `WYXR-Concert-Calendar/1.0` UA.
- A laptop gets challenged too after ~6 requests in a few minutes, then recovers. That is a
  bot score, not a static rule.
- The Memphis Listening Lab's identical `tribe_events` fetch succeeds in the same builds.

## Goal

Fetches to an allow-listed set of hosts go out from an egress IP we control, transparently —
no parser changes, no per-scraper plumbing, nothing different in local development.

## Non-goals

- Not a general proxy, not browser automation, not challenge-solving. The only change is the
  IP the request comes from. If a site challenges *that* IP too, we stop.
- Not moving the whole build off GitHub Actions (see Option B).

## Options considered

| | Option | Verdict |
|---|---|---|
| **A** | **Fetch relay route on the Render backend; build calls it for listed hosts** | **Recommended.** Small, reuses the `HEALTH_CHECK_TOKEN` auth pattern, zero infra cost. |
| B | Move the entire build to a Render cron job | Too big: the build needs Ticketmaster + Anthropic keys, pushes `docs/` + `data/events.json` to GitHub, and the Slack image pipeline dispatches the workflow. Weeks of churn for one IP change. |
| C | Commercial residential proxy | Monthly cost, another secret, and "residential proxy to get past a bot check" is a greyer thing to be doing than sending from our own server. No. |
| D | Ask each venue for a Cloudflare WAF skip rule for our UA | Doesn't scale and depends on volunteers finding the Cloudflare dashboard. Still worth a single email to Crosstown Arts (WYXR is a Concourse tenant) — but not as the plan. |
| E | Self-hosted GitHub runner | WYXR has no always-on machine. |

## Step 0 — the probe (required before any code)

Render's outbound IPs are static per region but **shared with other Render customers**, so
their reputation is not guaranteed clean. Verify from the backend's own shell before building
anything:

```bash
# Render dashboard → concert-calendar-api → Shell   (or: render ssh <service>)
python3 - <<'PY'
import requests
UA_BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
UA_PLAIN = "WYXR-Concert-Calendar/1.0 (+https://concert-calendar.wyxr.org)"
probes = [
    ("https://901growlers.com/", UA_BROWSER, "seetickets-list-event-container"),
    ("https://hernandoshideawaymemphis.com/calendar/", UA_BROWSER, "event-info-block"),
    ("https://hotelpontotoc.com/wp-json/tribe/events/v1/events?per_page=1", UA_PLAIN, '"events"'),
    ("https://crosstownarts.org/wp-json/tribe/events/v1/events?per_page=1", UA_PLAIN, '"events"'),
]
for url, ua, marker in probes:
    r = requests.get(url, headers={"User-Agent": ua}, timeout=20)
    ok = r.status_code == 200 and marker in r.text and "Just a moment" not in r.text
    print("OK " if ok else "BAD", r.status_code, url)
PY
```

- **All four OK →** build Option A.
- **Any BAD →** record the matrix in `dev/venues-and-scrapers.md` and stop. The remaining
  moves are D (per-venue WAF rules) and, for Growlers specifically, checking whether
  SeeTickets exposes the same listing on a `seetickets.us` domain that is not Cloudflare-fronted.
  Don't build the relay for the hosts that passed if the two that matter failed.

Run the probe twice a few minutes apart — the laptop evidence shows a second burst is where a
bot score bites.

## Design — Option A

### Backend: `GET /api/internal/fetch`

Add to `backend/app.py`, next to the health-check route.

- **Auth:** a `require_relay_token` decorator cloned from the `HEALTH_CHECK_TOKEN` wrapper at
  `backend/app.py` ≈ line 2695: `Bearer` header, `secrets.compare_digest`, **503 if the env var
  is unset** (so a half-deployed relay fails loudly, not open). New Render env var
  `FETCH_RELAY_TOKEN` (32+ random bytes). Not `require_auth` — that is the admin JWT.
- **Query params:** `url` (required) and `ua` ∈ {`browser`, `plain`} (default `browser`).
  The server maps `ua` onto its own copies of `HEADERS` / `_TRIBE_HEADERS`; the client never
  supplies arbitrary headers.
- **Allow-list (the SSRF guard):** exact hostnames, `https` only, no userinfo, no IP literals,
  no port. Define `RELAY_HOSTS` once in `src/config.py` and import it in both the backend and
  `src/http_utils.py` (the backend already imports from `src/` — e.g. `compute_dedup_key`).
  Initial set: `901growlers.com`, `www.901growlers.com`, `hernandoshideawaymemphis.com`,
  `hotelpontotoc.com`, `crosstownarts.org`. Not `dice.fm` — it isn't blocked. Reject anything
  else with 400 before making any request. **After** the upstream fetch, re-check the host of
  `resp.url` (redirects could leave the list) and 400 if it did.
- **Upstream call:** `requests.get(url, headers=…, timeout=20, allow_redirects=True)`. Cap
  the body at 2 MB (the DICE page is 380 KB, the biggest we read). Return
  `{"status": <upstream status>, "url": <final url>, "content_type": …, "body": <text>}` with
  HTTP 200 from the relay itself; connection failures/timeouts → 502 with a short message.
  Upstream 403 is still a 200 from the relay with `status: 403` — the build decides.
- **Logging:** host + upstream status only, never the body. Nothing to Slack.
- **Worker budget — a real decision.** Render runs **one** gunicorn sync worker
  (`WEB_CONCURRENCY` defaults to 1 in `backend/gunicorn_conf.py`). A relayed fetch holds it
  for up to 20 s, and the build runs scrapers 8-wide, so unserialized relay calls would stall
  the public API during every build. Recommended: serialize relay calls on the **client**
  with a `threading.Lock` in `http_utils` (there are ~6 requests across the listed hosts per
  build, so serialization costs seconds). Alternative: `WEB_CONCURRENCY=2` on Render —
  Starter's 512 MB is enough with `preload_app`, but it is an infra change to verify
  separately.

### Build side: `src/http_utils.py`

`get_with_retry` is the single choke point — every venue scraper fetch goes through it (eight
call sites in `venue_scrapers.py`, plus Ticketmaster and the sheet; none use `requests.get`
directly). Add the relay there:

```python
def get_with_retry(url, **kwargs):
    if _relay_enabled() and urlparse(url).hostname in RELAY_HOSTS:
        return _relay_get(url, **kwargs)
    return _session.get(url, **kwargs)
```

- `_relay_enabled()`: both `FETCH_RELAY_URL` and `FETCH_RELAY_TOKEN` set. Unset locally and in
  tests → direct fetch, byte-for-byte today's behavior.
- `_relay_get` builds the final URL first (`requests.Request("GET", url, params=…).prepare().url`
  — the Ticketmaster path passes `params`), picks `ua=plain` when the caller's User-Agent starts
  with `WYXR-Concert-Calendar`, else `browser`, calls the relay through `_session` (so the
  existing retry policy covers a Render blip), then returns a **real `requests.Response`**
  assembled from the JSON: `status_code`, `_content` (encoded), `url`, `headers`,
  `encoding="utf-8"`. Callers only use `.text`, `.json()`, `.status_code`, `.url` and
  `.raise_for_status()`, and all of those work on a synthetic Response, so no scraper changes.
  A relay 5xx raises `RequestException` and lands in each scraper's existing `except`.
- `allow_redirects` is ignored (the relay always follows); nothing listed relies on not
  following.
- `.github/workflows/daily.yml`: add `FETCH_RELAY_URL: https://concert-calendar-api.onrender.com`
  and `FETCH_RELAY_TOKEN: ${{ secrets.FETCH_RELAY_TOKEN }}` to the "Run calendar update" env.
  The nightly health check does not scrape; leave it alone.

### Config once it works

- Hotel Pontotoc: `"scraper": "manual_only"` → `"tribe_events"` in `src/config.py`; the
  filters are still there.
- Crosstown Arts: **stay on DICE.** It carries artwork and ticket links the WordPress calendar
  doesn't, and the film filter is by Schema.org type rather than title. The host stays in
  `RELAY_HOSTS` only so the `tribe_events` config in commit `28ec11a` is a one-line revert.
- Growlers and Hernando's: no config change — they just start working.

### Tests

- **Backend** (new `scripts/test_fetch_relay.py`, wired into `test_before_push.sh`, expecting
  the count to go 22 → 23): missing token → 503, wrong token → 401, host not listed → 400,
  `http://` → 400, `https://901growlers.com@evil.example/` → 400, IP literal → 400, redirect
  landing off-list → 400, body over cap → truncated/413. Stub `requests.get` — nothing here may
  hit the network or mutate state (`dev/testing.md`).
- **Build side:** with the env set and the relay mocked, a listed host goes to the relay and an
  unlisted one goes direct; the synthetic Response round-trips `.text`, `.json()`,
  `.raise_for_status()` on a 404; `params` end up in the relayed URL.
- `scripts/test_security_headers.py` re-run — the route is JSON and touches no CSP, but it's
  cheap and the tripwire says so.
- **End to end:** `gh workflow run "Daily Concert Calendar Update"`, then in the log expect
  `✅ Venue: Growlers: ~30`, `✅ Venue: Hernando's Hideaway: ~36`, `✅ Venue: Hotel Pontotoc`
  (2 real shows of ~25 at last count), and the `Saved to PostgreSQL` line showing adds.

### Rollout order

1. Step 0 probe, twice. Record the matrix in `dev/venues-and-scrapers.md` either way.
2. Set `FETCH_RELAY_TOKEN` on Render **before** deploying the route (503 until then is fine).
3. Backend route + tests; `./test_before_push.sh` → 23/23; push; watch the Render deploy.
4. Add the same value as GitHub secret `FETCH_RELAY_TOKEN`.
5. Build-side relay + workflow env; push; trigger a build; check the three ✅ lines.
6. Re-enable Hotel Pontotoc; one more build.
7. Docs: `dev/venues-and-scrapers.md` (Pontotoc, Crosstown, Growlers/Hernando's notes),
   `dev/security.md` secrets table (`FETCH_RELAY_TOKEN` on Render + GitHub), `CLAUDE.md` file
   map (`src/http_utils.py` now has the relay). Flip this spec's status to "shipped".

### Follow-ups surfaced by this (separate, small)

- **Nobody noticed three venues go dark for 3–7 weeks.** The nightly health check
  (`.github/workflows/nightly-health-check.yml`) should flag a scraper that has errored N
  builds in a row (N=4 ≈ 2 days), posting to Slack via the existing `SLACK_WEBHOOK_URL`.
  Check `scripts/test_health_check.py` first — it pins what "incomplete" vs "broken" means.
- Email Crosstown Arts about a WAF rule anyway; it costs one message and makes the relay
  irrelevant for them.

## Evidence log (2026-10-26/27)

- Crosstown Arts: last good build 2026-09-07 10:00 UTC; 403 from 2026-09-08. Laptop: HTML 200
  (8 events), API 200 (37 events), then API 403 after a burst. Runner API 403 in build
  40405466930 while Listening Lab's identical fetch returned 8 events.
- Growlers + Hernando's: good in build 2026-10-07 11:36 UTC (30 / 36 events), 403 in
  2026-10-07 21:42 UTC and every build since (sampled through 2026-10-27 10:15 UTC). Laptop
  2026-10-27: Growlers 27 events, Hernando's 33, both `server: cloudflare`.
- DICE promoter page + 27 detail pages from a laptop: all 200, no challenge, 25 s.
