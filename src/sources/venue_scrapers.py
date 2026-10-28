"""Venue website scrapers.

Each venue with a web calendar gets a scraper function.
When a venue changes their site, you only fix that one function.
"""

from typing import List, Optional
import requests
import html as _html
import json
import re
import time
from datetime import datetime, date
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from ..models import Event, SourceResult, first_image_url, best_ticketmaster_image
from ..http_utils import get_with_retry, fetch_ticketmaster_events, new_session, proxy_configured
from ..config import (
    VENUES, START_DATE, END_DATE, SCRAPER_END_DATE,
    TICKETMASTER_API_KEY,
    normalize_venue_name, is_music_event, EXCLUDE_KEYWORDS, MUSIC_KEYWORDS,
    venue_source_tag as _venue_source_tag,
)
from ..date_utils import parse_date_text
from ..time_format import format_event_time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Some origins refuse the browser UA above and serve a plain self-identifying
# one: Landers Center answers 406 to the Chrome UA (and nothing else in HEADERS
# matters — verified header by header on 2026-10-28), which left it at "0
# events parsed" for 27 of 40 builds. A venue opts in with `plain_user_agent`.
PLAIN_HEADERS = {
    "User-Agent": "WYXR-Concert-Calendar/1.0 (+https://concert-calendar.wyxr.org)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _img_src(el) -> Optional[str]:
    """Return the first http(s) <img> source within a BeautifulSoup element.

    Tolerates lazy-loading attributes (data-src etc.) common on Wix/SeeTickets.
    """
    if el is None:
        return None
    img = el if getattr(el, "name", None) == "img" else el.select_one("img")
    if img is None:
        return None
    for attr in ("src", "data-src", "data-lazy-src", "data-original", "data-image"):
        val = img.get(attr)
        if val and val.startswith(("http://", "https://")):
            return val
    return None


def fetch() -> SourceResult:
    """Fetch events from all configured venue websites."""
    result = SourceResult(source_name="Venue Websites")
    sub_results = []

    for venue_key, venue_info in VENUES.items():
        url = venue_info.get("calendar_url")
        scraper_type = venue_info.get("scraper", "generic")

        # Skip venues without web calendars (manual-only)
        if not url or scraper_type == "manual_only":
            continue

        venue_result = _scrape_venue(venue_key, venue_info)
        sub_results.append(venue_result)

        result.events_found += venue_result.events_found
        result.events.extend(venue_result.events)
        result.events_filtered += venue_result.events_filtered

    # Compile status from sub-results
    failures = [r for r in sub_results if not r.success]
    successes = [r for r in sub_results if r.success]

    if failures:
        fail_names = ", ".join(r.source_name for r in failures)
        result.error_message = f"Some venues failed: {fail_names}"

    # Overall success if at least some venues worked
    result.success = len(successes) > 0 or len(failures) == 0

    return result


def fetch_individual() -> List[SourceResult]:
    """Fetch events from each venue separately (for detailed logging).

    Scrapes all venues in parallel using a thread pool (max 8 workers)
    since each scraper is independent with no shared state.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # API-based scrapers are keyed by an id, not a calendar_url — don't require
    # a URL for them (ticketmaster_venue uses ticketmaster_venue_id). Requiring
    # calendar_url here silently dropped url-less TM venues (Grind City,
    # Bluesville, Snowden Grove) from every build.
    API_SCRAPERS = {"ticketmaster_venue"}
    venues_to_scrape = [
        (venue_key, venue_info)
        for venue_key, venue_info in VENUES.items()
        if venue_info.get("scraper", "generic") != "manual_only"
        and (venue_info.get("calendar_url") or venue_info.get("scraper") in API_SCRAPERS)
    ]

    results = []

    # A venue whose site Cloudflare-blocks the runner can only be read through
    # the proxy (http_utils). Without a key it would 403 on every build and
    # flag the whole run "partial", so it is reported as skipped instead —
    # still a row in the build log, so the health check sees it, but honest
    # about why it has nothing.
    if not proxy_configured():
        for venue_key, venue_info in venues_to_scrape:
            if venue_info.get("requires_proxy"):
                skipped = SourceResult(source_name=f"Venue: {venue_info['name']}")
                skipped.error_message = ("Skipped — Cloudflare blocks the runner and "
                                         "SCRAPERAPI_KEY is not set")
                results.append(skipped)
        venues_to_scrape = [(k, v) for k, v in venues_to_scrape if not v.get("requires_proxy")]

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_venue = {
            executor.submit(_scrape_venue, venue_key, venue_info): venue_key
            for venue_key, venue_info in venues_to_scrape
        }
        for future in as_completed(future_to_venue):
            results.append(future.result())

    return results


def _scrape_venue(venue_key: str, venue_info: dict) -> SourceResult:
    """Scrape a single venue's calendar page."""
    name = venue_info["name"]
    url = venue_info["calendar_url"]
    result = SourceResult(source_name=f"Venue: {name}")
    scraper_type = venue_info.get("scraper", "generic")

    # Ticketmaster venue scraper — queries TM API by venue ID, no webpage fetch
    if scraper_type == "ticketmaster_venue":
        return _fetch_ticketmaster_venue(venue_info)

    # SiteWrench calendar API — JSON, no webpage fetch
    if scraper_type == "sitewrench":
        return _fetch_sitewrench_venue(venue_info)

    # Blues City Cafe — month-per-page HTML calendar, fetches multiple pages
    if scraper_type == "blues_city_cafe":
        return _fetch_blues_city_cafe(venue_info)

    # The Events Calendar (WordPress) JSON API — no webpage fetch
    if scraper_type == "tribe_events":
        return _fetch_tribe_events(venue_info)

    # DICE promoter page — server-rendered Next.js data plus one detail
    # fetch per event for its Schema.org type
    if scraper_type == "dice_promoter":
        return _fetch_dice_promoter(venue_info)

    # Eventim (formerly SeeTickets) white-label listing — the venue's own site
    # is Cloudflare-blocked from CI; the ticketing host is not
    if scraper_type == "eventim_whitelabel":
        return _fetch_eventim_whitelabel(venue_info)

    # Memphis Symphony — Squarespace JSON API, and the one source whose events
    # are spread across many venues rather than held at one
    if scraper_type == "memphis_symphony":
        return _fetch_memphis_symphony(venue_info)

    # Elfsight widget — JSON API keyed by the widget id in config; the venue
    # page itself holds nothing we need
    if scraper_type == "elfsight":
        return _fetch_elfsight_venue(venue_info)

    headers = PLAIN_HEADERS if venue_info.get("plain_user_agent") else HEADERS
    non_music = 0  # listings a mixed-use venue's parser dropped as not concerts

    try:
        response = get_with_retry(url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        scraper_type = venue_info.get("scraper", "generic")

        # Custom scrapers for specific venues
        if scraper_type == "hi_tone":
            events = _parse_hi_tone(soup, name)
        elif scraper_type == "minglewood":
            events = _parse_minglewood(soup, name)
        elif scraper_type == "graceland":
            events = _parse_graceland(soup, name)
        elif scraper_type == "orpheum":
            events = _parse_orpheum(soup, name)
        elif scraper_type == "overton_shell":
            events = _parse_overton_shell(soup, name)
        elif scraper_type == "south_main_sounds":
            events = _parse_south_main_sounds(soup, name)
        elif scraper_type == "landers":
            events, non_music = _parse_landers(soup, name)
        elif scraper_type == "flyway":
            events = _parse_flyway(soup, name)
        elif scraper_type == "society":
            events = _parse_society(soup, name)
        else:
            # Try JSON-LD first (many event sites embed structured data)
            events = _try_jsonld(soup, name)

            # If no JSON-LD, try generic DOM parsing
            if not events:
                events = _try_generic_parse(soup, name)

        _collect_in_window(result, events, "0 events parsed — page structure may have changed")
        if non_music:
            # An arena calendar that is all hockey and cheer this month parsed
            # fine — say so instead of "page structure may have changed".
            result.events_found += non_music
            result.events_filtered += non_music
            if not events:
                result.error_message = None

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Request failed: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"

    return result


def _collect_in_window(result: SourceResult, events: List[Event], empty_message: str) -> None:
    """File parsed events into `result`, keeping those inside the scrape window.

    Events from venue calendars are music events by definition, so there is no
    is_music_event() check here — it false-negatives on artist names.
    """
    result.events_found = len(events)
    for event in events:
        if not (START_DATE <= event.date <= SCRAPER_END_DATE):
            result.events_filtered += 1
        else:
            result.events.append(event)
    if result.events_found == 0:
        result.error_message = empty_message


def _fetch_elfsight_venue(venue_info: dict) -> SourceResult:
    """Elfsight Event Calendar widget — read its JSON API, not the venue page.

    The venue page only hosts the widget; the events live at
    core.service.elfsight.com and the widget id is in config. Fetching the page
    first was pure overhead, and on lafayettes.com Cloudflare 403'd that fetch
    in 8 of 40 October builds while the API call that followed never failed —
    Lafayette's dropped out of the calendar one build in five for nothing.
    """
    name = venue_info["name"]
    result = SourceResult(source_name=f"Venue: {name}")
    try:
        events = _parse_elfsight(name, venue_info.get("calendar_url", ""),
                                 venue_info.get("elfsight_widget_id", ""))
        _collect_in_window(result, events, "0 events from the Elfsight API — widget id may have changed")
    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Elfsight API error: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"
    return result


# Ticketmaster lists casino "ticket + hotel" upsells as separate events that
# duplicate the real show (same venue + date, different title) — e.g. Horseshoe
# Casino's Bluesville shows each appear twice: "CLUTCH: US Fall Tour" and
# "Clutch | Official Caesars Ticket + Hotel Packages".
_PACKAGE_MARKERS = (
    "official caesars ticket",
    "ticket + hotel",
    "hotel package",
    "vip package",
)


def _is_package_listing(title: str) -> bool:
    """True if a title is a ticket/hotel/VIP package upsell, not a distinct show."""
    t = (title or "").lower()
    return any(m in t for m in _PACKAGE_MARKERS)


def _drop_package_duplicates(events):
    """Drop package-upsell listings when the real show is also listed.

    Grouped by (venue, date): if any non-package listing exists that day, the
    package variants are removed; a package-only date is left untouched so a
    show is never lost.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for e in events:
        groups[(e.venue, e.date)].append(e)
    out = []
    for group in groups.values():
        non_pkg = [e for e in group if not _is_package_listing(e.artist)]
        out.extend(non_pkg if non_pkg else group)
    return out


def _fetch_ticketmaster_venue(venue_info: dict) -> SourceResult:
    """Fetch events from Ticketmaster API by venue ID."""
    name = venue_info["name"]
    venue_id = venue_info.get("ticketmaster_venue_id", "")
    result = SourceResult(source_name=f"Venue: {name}")

    if not TICKETMASTER_API_KEY or not venue_id:
        result.success = False
        result.error_message = "Missing TICKETMASTER_API_KEY or ticketmaster_venue_id"
        return result

    try:
        params = {
            "apikey": TICKETMASTER_API_KEY,
            "venueId": venue_id,
            "classificationName": "music",
            "startDateTime": f"{START_DATE.isoformat()}T00:00:00Z",
            "endDateTime": f"{SCRAPER_END_DATE.isoformat()}T23:59:59Z",
            "size": 50,
            "sort": "date,asc",
        }
        events_data, truncated = fetch_ticketmaster_events(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            params,
        )
        result.events_found = len(events_data)
        if truncated:
            result.error_message = (
                "Ticketmaster returned more events than the API will page through; "
                "the tail of the window is missing"
            )

        for event_data in events_data:
            try:
                dates = event_data.get("dates", {}).get("start", {})
                date_str = dates.get("localDate")
                if not date_str:
                    continue
                event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if not (START_DATE <= event_date <= SCRAPER_END_DATE):
                    result.events_filtered += 1
                    continue

                time_str = None
                local_time = dates.get("localTime")
                if local_time:
                    try:
                        t = datetime.strptime(local_time, "%H:%M:%S")
                        time_str = format_event_time(t)
                    except ValueError:
                        pass

                result.events.append(Event(
                    artist=event_data.get("name", "").strip(),
                    venue=name,
                    date=event_date,
                    time=time_str,
                    source=_venue_source_tag(name),
                    url=event_data.get("url"),
                    image_url=best_ticketmaster_image(event_data.get("images")),
                ))
            except Exception:
                continue

        # Collapse casino ticket+hotel package upsells that duplicate a show.
        result.events = _drop_package_duplicates(result.events)

        if result.events_found == 0:
            result.error_message = "0 events from Ticketmaster for this venue"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Ticketmaster API error: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"

    return result


def _fetch_sitewrench_venue(venue_info: dict) -> SourceResult:
    """Fetch events from a SiteWrench calendar API (e.g. Huey's)."""
    name = venue_info["name"]
    result = SourceResult(source_name=f"Venue: {name}")

    api_token = venue_info.get("sitewrench_api_token", "")
    site_id = venue_info.get("sitewrench_site_id", "")
    page_part_id = venue_info.get("sitewrench_page_part_id", "")

    if not api_token or not page_part_id:
        result.success = False
        result.error_message = "Missing sitewrench_api_token or sitewrench_page_part_id"
        return result

    try:
        url = (f"https://api.sitewrench.com/pageparts/calendars/{page_part_id}/events"
               f"?key={api_token}&token={api_token}&siteId={site_id}")

        resp = get_with_retry(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        result.events_found = 0
        for item in data:
            if not item.get("IsActive", True):
                continue
            title = item.get("Subject", "").strip()
            if not title:
                continue

            start_str = item.get("StartDateTimeInTimeZone", "")
            if not start_str:
                continue

            dt = datetime.fromisoformat(start_str)
            event_date = dt.date()
            time_str = format_event_time(dt)

            # Build venue display name: "Huey's (Midtown)"
            location = item.get("Location", "").strip()
            display_venue = f"{name} ({location})" if location else name

            result.events_found += 1

            if not (START_DATE <= event_date <= SCRAPER_END_DATE):
                result.events_filtered += 1
            else:
                result.events.append(Event(
                    artist=title,
                    venue=display_venue,
                    date=event_date,
                    time=time_str,
                    source=_venue_source_tag(name),
                ))

        if result.events_found == 0:
            result.error_message = "0 events from SiteWrench API"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"SiteWrench API error: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"

    return result


# The Events Calendar (the WordPress plugin formerly by Modern Tribe) publishes a
# JSON REST API at /wp-json/tribe/events/v1/events. Read that instead of parsing
# the rendered calendar: it is paginated, carries categories, and survives theme
# changes. The plugin is common enough that this scraper is worth keeping generic
# — point `calendar_url` at any site running it.
_TRIBE_API_PATH = "/wp-json/tribe/events/v1/events"
_TRIBE_MAX_PAGES = 10

# Deliberately NOT the shared browser-spoofing HEADERS. Hotel Pontotoc sits
# behind a WAF that 403s the full Chrome user-agent on /wp-json/ requests —
# presumably because a real Chrome would also send sec-ch-* and cookies. A
# plain self-identifying agent is allowed, and is the honest thing to send to
# a public JSON API anyway.
_TRIBE_HEADERS = {
    "User-Agent": "WYXR-Concert-Calendar/1.0 (+https://concert-calendar.wyxr.org)",
    "Accept": "application/json",
}


# "Live Music: Spaceman's Dead Friends" — the label is redundant on a music
# calendar and, left in place, it is what a DJ reads in the listing. Strip it so
# the act stands alone, the way the old Crosstown Brewing parser pulled the
# artist out of "Live Music - Mark Allen". Only this one generic label, and only when a
# name survives: a bare "Live Music" listing keeps its title, since normalize.py
# relies on that exact string being a recognised placeholder.
_TRIBE_LABEL_RE = re.compile(r"^\s*live\s+music\s*[:\u2013\u2014-]\s*", re.I)


def _strip_billing_label(title: str) -> str:
    """Drop a leading "Live Music:" label when a real act name follows."""
    stripped = _TRIBE_LABEL_RE.sub("", title).strip()
    return stripped or title


def _tribe_site_origin(calendar_url: str) -> str:
    """Scheme + host for a venue's Events Calendar page, or '' if unparseable."""
    m = re.match(r"(https?://[^/]+)", calendar_url or "")
    return m.group(1) if m else ""


def _fetch_tribe_events(venue_info: dict) -> SourceResult:
    """Fetch events from a WordPress "The Events Calendar" REST API.

    Three filters, all opt-in per venue, because a hotel/bar calendar is not the
    pure music feed most venue scrapers read:

    - ``tribe_skip_categories`` drops whole categories. Hotel Pontotoc tags its
      buyouts "Private" — 7 of 25 upcoming entries when this was written, and a
      private buyout must never reach a public calendar.
    - ``tribe_own_venues`` drops events held somewhere else. The same calendar
      lists football watch parties *at stadiums the venue does not own*; without
      this they publish under the venue's own name. An empty venue field is
      allowed, since many entries simply omit it.
    - ``tribe_music_only`` applies ``is_music_event()``. The dispatcher trusts
      venue scrapers to be all-music and skips that check, which is wrong here
      for the same reason it is wrong for Crosstown Arts.
    """
    name = venue_info["name"]
    result = SourceResult(source_name=f"Venue: {name}")

    origin = _tribe_site_origin(venue_info.get("calendar_url", ""))
    if not origin:
        result.success = False
        result.error_message = "Could not derive site origin from calendar_url"
        return result

    skip_cats = {c.lower() for c in venue_info.get("tribe_skip_categories", [])}
    own_venues = {v.lower() for v in venue_info.get("tribe_own_venues", [])}
    music_only = bool(venue_info.get("tribe_music_only", False))

    try:
        page = 1
        while page <= _TRIBE_MAX_PAGES:
            url = (f"{origin}{_TRIBE_API_PATH}?per_page=50&page={page}"
                   f"&start_date={START_DATE.isoformat()}"
                   f"&end_date={SCRAPER_END_DATE.isoformat()}")
            resp = get_with_retry(url, headers=_TRIBE_HEADERS, timeout=15)
            # The plugin 404s past the last page rather than returning an empty
            # list, so treat that as the end instead of a scraper failure.
            if resp.status_code == 404 and page > 1:
                break
            resp.raise_for_status()
            data = resp.json()

            items = data.get("events") or []
            if not items:
                break

            for item in items:
                raw_title = _html.unescape((item.get("title") or "").strip())
                if not raw_title:
                    continue
                # Classify on the RAW title, display the stripped one. The
                # "Live Music:" label is precisely the signal is_music_event()
                # needs — strip it first and an artist-only name like
                # "Spaceman's Dead Friends" is read as a non-music event and
                # silently dropped.
                title = _strip_billing_label(raw_title)
                result.events_found += 1

                cats = {(c.get("name") or "").lower() for c in (item.get("categories") or [])}
                if skip_cats & cats:
                    result.events_filtered += 1
                    continue

                tribe_venue = _html.unescape(
                    ((item.get("venue") or {}).get("venue") or "").strip())
                if own_venues and tribe_venue and tribe_venue.lower() not in own_venues:
                    result.events_filtered += 1
                    continue

                try:
                    dt = datetime.fromisoformat(item.get("start_date") or "")
                except ValueError:
                    result.events_filtered += 1
                    continue

                if not (START_DATE <= dt.date() <= SCRAPER_END_DATE):
                    result.events_filtered += 1
                    continue

                if music_only and not is_music_event(raw_title):
                    result.events_filtered += 1
                    continue

                result.events.append(Event(
                    artist=title,
                    venue=name,
                    date=dt.date(),
                    time=None if item.get("all_day") else format_event_time(dt),
                    source=_venue_source_tag(name),
                    url=item.get("url") or None,
                ))

            total_pages = data.get("total_pages") or 1
            if page >= total_pages:
                break
            page += 1

        if result.events_found == 0:
            result.error_message = "0 events returned — Events Calendar API may have moved"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Events Calendar API error: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"

    return result


# A DICE promoter page (dice.fm/promoters/<slug>) is a Next.js app that
# server-renders its whole upcoming list into the `__NEXT_DATA__` script —
# name, start time with zone, room, artwork and the event id — so no JS is
# needed. Only the city-wide browse page was ever a JS shell; that is the DICE
# source that was removed in February 2026, and this is not it.
#
# What the list does NOT carry is any kind of type, and Crosstown Arts sells
# its film series through the same promoter under bare titles ("Creepshow",
# "The Holdovers") that no keyword filter can catch. Each event's own page has
# Schema.org JSON-LD whose @type is `ScreeningEvent` for a film and
# `MusicEvent` for a show, so the fetcher reads one detail page per in-window
# event. That is ~25 requests a build; DICE served 27 in a row without a
# challenge when this was written. If the detail fetch fails the event is kept
# — a stray film beats a silently missing concert.
_DICE_HEADERS = {
    "User-Agent": "WYXR-Concert-Calendar/1.0 (+https://concert-calendar.wyxr.org)",
    "Accept": "text/html",
}
_DICE_EVENT_URL = "https://dice.fm/event/{id}"
_DICE_SKIP_TYPES = {"ScreeningEvent"}
_DICE_SKIP_STATUSES = {"cancelled", "canceled", "postponed"}
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_LDJSON_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _dice_event_type(html_text: str) -> Optional[str]:
    """The Schema.org @type of the Event on a DICE event page, if any."""
    for block in _LDJSON_RE.findall(html_text):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in (data if isinstance(data, list) else [data]):
            t = item.get("@type") if isinstance(item, dict) else None
            if isinstance(t, str) and t.endswith("Event"):
                return t
    return None


def _fetch_dice_promoter(venue_info: dict) -> SourceResult:
    """Fetch a venue's events from its DICE promoter page."""
    name = venue_info["name"]
    result = SourceResult(source_name=f"Venue: {name}")
    skip_types = {t for t in venue_info.get("dice_skip_types", _DICE_SKIP_TYPES)}

    try:
        resp = get_with_retry(venue_info["calendar_url"], headers=_DICE_HEADERS, timeout=15)
        resp.raise_for_status()
        m = _NEXT_DATA_RE.search(resp.text)
        if not m:
            result.success = False
            result.error_message = "No __NEXT_DATA__ on page — DICE may have changed its markup"
            return result

        sections = (json.loads(m.group(1)).get("props", {}).get("pageProps", {})
                    .get("profile", {}).get("sections") or [])
        items = [ev for sec in sections for ev in (sec.get("events") or [])]

        for item in items:
            title = (item.get("name") or "").strip()
            event_id = item.get("id")
            if not title or not event_id:
                continue
            result.events_found += 1

            if (item.get("status") or "").lower() in _DICE_SKIP_STATUSES:
                result.events_filtered += 1
                continue

            try:
                dt = datetime.fromisoformat((item.get("dates") or {}).get("event_start_date") or "")
            except ValueError:
                result.events_filtered += 1
                continue
            if not (START_DATE <= dt.date() <= SCRAPER_END_DATE):
                result.events_filtered += 1
                continue

            url = _DICE_EVENT_URL.format(id=event_id)
            try:
                detail = get_with_retry(url, headers=_DICE_HEADERS, timeout=15)
                detail.raise_for_status()
                if detail.url:
                    url = detail.url  # the slugged canonical link
                if _dice_event_type(detail.text) in skip_types:
                    result.events_filtered += 1
                    continue
            except requests.exceptions.RequestException:
                pass  # keep the event; see the note above

            result.events.append(Event(
                artist=title,
                venue=name,
                date=dt.date(),
                time=format_event_time(dt),
                source=_venue_source_tag(name),
                url=url,
                image_url=first_image_url(list((item.get("images") or {}).values())),
            ))

        if result.events_found == 0:
            result.error_message = "0 events on promoter page — DICE may have changed its data shape"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"DICE request failed: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"

    return result


# Growlers and Hernando's Hideaway both sell through Eventim's white-label
# ticketing (wl.eventim.us — SeeTickets US before the rebrand; the old
# wl.seetickets.us links redirect there). Both venues' own sites have
# Cloudflare-challenged every CI build since 2026-10-07, and the Render backend's
# egress IP is challenged too, but the ticketing host serves the plain
# WYXR user-agent. calendar_url is the organizer page, wl.eventim.us/<key>.
#
# - The organizer page holds the first 12 events. Later pages come from an AJAX
#   endpoint that answers with an EMPTY body unless the request carries the
#   session cookie the organizer page set, so all of one venue's requests go
#   through one private session (not the shared one — see new_session()). The
#   AJAX URL needs the organizer's numeric ProfileID, read off page one's own
#   pager links rather than configured.
# - A card has the title, the date with its year (only in the buy button's
#   aria-label), the ticket link and the artwork — but no time. The time comes
#   from each event page's Schema.org startDate, one request per event.
# - The title is always the card's billing, minus "at <venue> - Memphis, TN".
#   Never take it from the event page (its .talent-list has a cleaner
#   headliner field): event pages are best-effort, so the title would flip
#   between builds with and without them, and dedup matches on title — every
#   flip would be a new row. Growlers' old venue-site scraper used that
#   headliner field, so on the switch (2026-10-27) eight of its stored rows were
#   retitled by hand rather than left as duplicates.
# - Eventim runs a Cloudflare waiting room ("You're in line!") during heavy
#   on-sales. Detail pages are therefore best-effort: the first page with no
#   startDate stops detail fetches for the rest of the run and every remaining
#   event keeps its card data, without a time. A listing page that is a queue
#   page fails the source loudly instead of reporting 0 events as success.
_EVENTIM_HEADERS = {
    "User-Agent": "WYXR-Concert-Calendar/1.0 (+https://concert-calendar.wyxr.org)",
    "Accept": "text/html",
}
_EVENTIM_BASE = "https://wl.eventim.us"
_EVENTIM_PAGE_SIZE = 12  # the endpoint ignores larger FetchSize values
_EVENTIM_MAX_PAGES = 15
_EVENTIM_AJAX = (
    _EVENTIM_BASE + "/wafform.aspx?_act=Search&_tab=Event&_sea=WhiteLabelEventSearchNdV3"
    "&_sft=0&ProfileID={pid}&WhiteLabelKey={key}&IsProfilePage=1&IsWhiteLabelPage=1"
    "&CurrentTab=all&FetchSize={size}&_lfv={offset}&AJAX=1"
)
_EVENTIM_PROFILE_RE = re.compile(r"ProfileID=(\d+)")
_EVENTIM_LABEL_RE = re.compile(r"^Buy tickets for .* on (\w+ \d{1,2} \d{4})$")
_EVENTIM_START_RE = re.compile(r'"startDate"\s*:\s*"([^"]+)"')
_EVENTIM_QUEUE_MARKER = "You're in line"
# Cloudflare's waiting room sets a __cfwaitingroom cookie and asks the browser
# to refresh; a session that keeps polling the same URL is admitted when its
# turn comes. Before this the first queued page ended the venue for the build,
# and Hernando's organizer page was queued in 2 of its first 3 Eventim builds.
# One poll budget per venue, shared by the organizer page and the event pages,
# so a long queue costs a few minutes of one worker thread and no more.
_EVENTIM_QUEUE_POLLS = 6
_EVENTIM_QUEUE_INTERVAL = 20   # seconds between polls unless the page says otherwise
_EVENTIM_QUEUE_MAX_WAIT = 30   # cap on a Refresh header's own interval
# "The Faint at Growlers - Memphis,TN", "Jon Spencer at Hernando's Hide-A-Way -
# Memphis,TN", 'Yheti x Toadface "Sleight of Sound Tour" Memphis, TN'
_EVENTIM_CITY_SUFFIX = re.compile(r"[\s,\-–|]*\bMemphis,\s*TN\s*$", re.IGNORECASE)


def _eventim_strip_venue(title: str, venue_name: str) -> str:
    """Drop a trailing "- Memphis, TN" and "at <this venue>" from a billing."""
    title = _EVENTIM_CITY_SUFFIX.sub("", title).strip()
    match = re.search(r"\s+at\s+(.+)$", title, re.IGNORECASE)
    if match and normalize_venue_name(match.group(1).strip()) == venue_name:
        title = title[: match.start()].strip()
    return title


def _eventim_cards(html_text: str) -> list:
    return BeautifulSoup(html_text, "html.parser").select("div.search-event")


def _eventim_get(session: requests.Session, url: str, polls: dict) -> requests.Response:
    """GET `url`, waiting out Cloudflare's waiting room while `polls["left"]` lasts.

    Returns the final response either way; the caller checks for the queue
    marker to learn whether it got through. The queue page's own Refresh
    header sets the interval when present (capped), else a fixed one.
    """
    resp = session.get(url, timeout=15)
    while _EVENTIM_QUEUE_MARKER in resp.text and polls["left"] > 0:
        polls["left"] -= 1
        delay = _EVENTIM_QUEUE_INTERVAL
        refresh = (resp.headers.get("Refresh") or "").split(";")[0].strip()
        if refresh.isdigit():
            delay = min(max(int(refresh), 1), _EVENTIM_QUEUE_MAX_WAIT)
        time.sleep(delay)
        resp = session.get(url, timeout=15)
    return resp


def _fetch_eventim_whitelabel(venue_info: dict) -> SourceResult:
    """Fetch a venue's events from its Eventim white-label organizer page."""
    name = venue_info["name"]
    url = venue_info["calendar_url"]
    result = SourceResult(source_name=f"Venue: {name}")
    key = url.rstrip("/").rsplit("/", 1)[-1]
    session = new_session()
    session.headers.update(_EVENTIM_HEADERS)

    polls = {"left": _EVENTIM_QUEUE_POLLS}

    try:
        resp = _eventim_get(session, url, polls)
        resp.raise_for_status()
        if _EVENTIM_QUEUE_MARKER in resp.text:
            result.success = False
            result.error_message = (f"Eventim waiting room on the organizer page after "
                                    f"{_EVENTIM_QUEUE_POLLS} polls — retry next build")
            return result
        cards = _eventim_cards(resp.text)

        pid = _EVENTIM_PROFILE_RE.search(resp.text)
        offset = _EVENTIM_PAGE_SIZE
        while pid and len(cards) == offset and offset < _EVENTIM_PAGE_SIZE * _EVENTIM_MAX_PAGES:
            page = session.get(_EVENTIM_AJAX.format(
                pid=pid.group(1), key=key, size=_EVENTIM_PAGE_SIZE, offset=offset), timeout=15)
            page.raise_for_status()
            cards += _eventim_cards(page.text)
            offset += _EVENTIM_PAGE_SIZE

        details_ok = True
        seen = set()
        for card in cards:
            buy = card.select_one('a[aria-label^="Buy tickets for "]')
            name_el = card.select_one(".event-name")
            if not buy or not name_el or card.get("id") in seen:
                continue
            seen.add(card.get("id"))
            result.events_found += 1

            m = _EVENTIM_LABEL_RE.match(buy["aria-label"].strip())
            try:
                event_date = datetime.strptime(m.group(1), "%B %d %Y").date() if m else None
            except ValueError:
                event_date = None
            if not event_date or not (START_DATE <= event_date <= SCRAPER_END_DATE):
                result.events_filtered += 1
                continue

            title = _eventim_strip_venue(name_el.get_text(" ", strip=True), name)
            event_url = _EVENTIM_BASE + buy["href"] if buy["href"].startswith("/") else buy["href"]
            time_str = None

            if details_ok:
                try:
                    detail = _eventim_get(session, event_url, polls)
                    detail.raise_for_status()
                    start = _EVENTIM_START_RE.search(detail.text)
                    if not start:
                        details_ok = False  # queue outlasted the polls, or new markup; stop asking
                    else:
                        dt = datetime.fromisoformat(start.group(1))
                        if dt.date() == event_date:
                            time_str = format_event_time(dt)
                except (requests.exceptions.RequestException, ValueError):
                    pass  # keep the card's data

            result.events.append(Event(
                artist=title,
                venue=name,
                date=event_date,
                time=time_str,
                source=_venue_source_tag(name),
                url=event_url,
                image_url=_img_src(card),
            ))

        if result.events_found == 0:
            result.error_message = "0 events on Eventim organizer page — markup may have changed"
        elif not details_ok:
            result.error_message = "Eventim event pages unavailable mid-run — some show times missing"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Eventim request failed: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"

    return result


# The Memphis Symphony runs on Squarespace, whose every collection page will
# return its own backing JSON with ?format=json appended. An events collection
# splits that JSON into "upcoming" and "past"; only "upcoming" is ever read
# here. Paging (?offset=) walks *backwards* into past seasons, so one request
# holds the whole forward schedule and there is no pagination to do.
_MSO_JSON_SUFFIX = "?format=json"

# Squarespace timestamps are epoch MILLISECONDS at UTC, and the symphony's site
# is set to America/Chicago. Reading them in the runner's zone instead of this
# one moves every evening concert to the following day: a 7:30 PM show is
# 00:30 UTC, so the nightly GitHub Actions build (UTC) would file the entire
# season one date late. Never replace this with a naive fromtimestamp().
_MSO_TZ = ZoneInfo("America/Chicago")

# The orchestra's calendar is not a pure concert feed — the Memphis Symphony
# League's fundraising social calendar shares it ("Annual Luncheon: Stars,
# Stripes and Strings" at Memphis Country Club, "Holiday Tea" at the Peabody's
# Chez Philippe). Those are member events at private clubs, not shows a DJ can
# send a listener to. is_music_event() cannot make this call: it reads no music
# keyword in "TCHAIKOVSKY'S 4TH" and would drop the real concerts instead, so
# the filter has to name what to remove rather than what to keep.
_MSO_EXCLUDE_KEYWORDS = (
    "luncheon", "holiday tea", "annual tea", "gala", "fundraiser",
    "auction", "annual meeting", "board meeting", "donor",
    "masterclass", "master class", "audition", "golf",
)

# The orchestra bills some shows with its internal initialism ("MSO BIG BAND AT
# THE GROVE"), which reads as nothing at all to someone scanning a public
# calendar. Expanding it is also what lets the listing merge with the same show
# as GPAC's own scraper files it ("Memphis Symphony Big Band") — dedup compares
# words, and with "MSO" left in place the two titles share only two of seven.
_MSO_INITIALISM = re.compile(r"\bMSO\b", re.IGNORECASE)

# The symphony bills most of its season in caps ("HANDEL'S MESSIAH"), which
# shouts next to every other listing on the calendar. The Graceland scraper
# already de-caps the same way, but with str.title(), which cannot be reused
# here: it capitalizes the letter after any non-letter, so an apostrophe or a
# digit corrupts the word — "HANDEL'S MESSIAH" becomes "Handel'S Messiah" and
# "TCHAIKOVSKY'S 4TH" becomes "Tchaikovsky'S 4Th". Nearly every concert title
# the orchestra publishes contains one or the other.
# The apostrophe class must include U+2019 — the symphony's titles use the
# curly form, and an ASCII-only class yields "Handel’S Messiah".
_MSO_WORD_START = re.compile(r"(?<![\w'’‘])([a-z])")


def _smart_title_case(text: str) -> str:
    """Title-case an all-caps string without breaking "Handel's" or "4th"."""
    return _MSO_WORD_START.sub(lambda m: m.group(1).upper(), text.lower())


# "MSO BIG BAND AT THE GROVE", "Sunset Symphony at the Overton Park Shell" —
# the orchestra often bills the hall inside the title, which the venue column
# already says.
_MSO_TRAILING_VENUE = re.compile(r"\s+at\s+(.+)$", re.IGNORECASE)

# Below this, what remains is too thin to be a show name — "Live at the
# Orpheum" must not become "Live".
_MSO_MIN_TITLE_LEN = 6


def _strip_venue_restatement(title: str, venue: str) -> str:
    """Drop a trailing "at <hall>" when <hall> IS this event's venue.

    Guarded on the tail resolving to the same canonical venue, so a title where
    "at" means something else is left alone. This is not cosmetic: dedup against
    events already stored compares titles exactly, so "Memphis Symphony Big Band
    At The Grove" would sit next to GPAC's own "Memphis Symphony Big Band"
    forever — the intra-scrape fuzzy pass merges the two, then keeps the longer
    title, which no longer matches the row already in the database.
    """
    match = _MSO_TRAILING_VENUE.search(title)
    if not match:
        return title
    if normalize_venue_name(match.group(1).strip()) != venue:
        return title
    stripped = title[: match.start()].strip()
    return stripped if len(stripped) >= _MSO_MIN_TITLE_LEN else title


def _fetch_memphis_symphony(venue_info: dict) -> SourceResult:
    """Fetch Memphis Symphony Orchestra concerts from its Squarespace JSON.

    ⚠️ This is the only scraper whose events do NOT all belong to the venue in
    its ``VENUES`` entry. The symphony owns no hall; a single season plays the
    Cannon Center, Scheidt Family PAC, the Orpheum and its Halloran Centre,
    GPAC's Grove, the Dixon's gardens and three churches for Handel's Messiah.
    Each event therefore takes its venue from that listing's own
    ``location.addressTitle``, canonicalized through ``normalize_venue_name``,
    and ``venue_info["name"]`` is used only for the source tag and as the
    fallback when a listing names no location at all.

    Filing these under a single "Memphis Symphony Orchestra" pseudo-venue was
    the alternative and is worse twice over: the venue is the one field a DJ
    acts on, and it would also guarantee permanent duplicates, since a show at
    the Cannon Center or the Orpheum can never dedup against those venues' own
    scrapers unless it is stored under the same venue name.
    """
    name = venue_info["name"]
    source_tag = _venue_source_tag(name)
    result = SourceResult(source_name=f"Venue: {name}")

    calendar_url = venue_info.get("calendar_url", "")
    origin = _tribe_site_origin(calendar_url)
    if not origin:
        result.success = False
        result.error_message = "Could not derive site origin from calendar_url"
        return result

    try:
        resp = get_with_retry(
            f"{calendar_url}{_MSO_JSON_SUFFIX}", headers=HEADERS, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        # "upcoming" is what an events collection populates. Fall back to the
        # plain item list for a layout that doesn't split them, but never to
        # "past" — that would republish finished seasons.
        items = data.get("upcoming") or data.get("items") or []

        for item in items:
            # A dangling "Orchestra Unplugged:" ships on the real calendar
            # where the subtitle was never filled in; the colon is an authoring
            # artifact, not part of the name.
            title = _html.unescape((item.get("title") or "").strip()).rstrip(" :-–—")
            # De-caps before expanding, so the guard still sees a caps title.
            if title == title.upper() and len(title) > 3:
                title = _smart_title_case(title)
            title = _MSO_INITIALISM.sub("Memphis Symphony", title)
            start_ms = item.get("startDate")
            if not title or not isinstance(start_ms, (int, float)):
                continue
            result.events_found += 1

            lowered = title.lower()
            if any(kw in lowered for kw in _MSO_EXCLUDE_KEYWORDS):
                result.events_filtered += 1
                continue

            dt = datetime.fromtimestamp(start_ms / 1000, _MSO_TZ)
            if not (START_DATE <= dt.date() <= SCRAPER_END_DATE):
                result.events_filtered += 1
                continue

            # The hall this particular concert plays, not the orchestra.
            location = item.get("location") or {}
            raw_venue = _html.unescape((location.get("addressTitle") or "").strip())
            event_venue = normalize_venue_name(raw_venue) if raw_venue else name

            title = _strip_venue_restatement(title, event_venue)

            full_url = item.get("fullUrl") or ""
            if full_url.startswith("/"):
                full_url = f"{origin}{full_url}"

            result.events.append(Event(
                artist=title,
                venue=event_venue,
                date=dt.date(),
                time=format_event_time(dt),
                # Tagged to the symphony, never to the hall — the source tag is
                # what the nightly health check counts, and borrowing e.g.
                # scraper:orpheum_theatre here would credit this run to the
                # Orpheum's own scraper and mask it going dark.
                source=source_tag,
                url=full_url or None,
                image_url=first_image_url(item.get("assetUrl")),
            ))

        if result.events_found == 0:
            result.error_message = "0 events parsed — Squarespace JSON may have moved"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Request failed: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"

    return result



def _try_jsonld(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Extract events from JSON-LD structured data (Schema.org Event)."""
    events = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]

            for item in items:
                if item.get("@type") in ("Event", "MusicEvent"):
                    event = _jsonld_to_event(item, venue_name)
                    if event:
                        events.append(event)
                # Handle @graph arrays
                elif "@graph" in item:
                    for graph_item in item["@graph"]:
                        if graph_item.get("@type") in ("Event", "MusicEvent"):
                            event = _jsonld_to_event(graph_item, venue_name)
                            if event:
                                events.append(event)
        except (json.JSONDecodeError, Exception):
            continue

    return events


def _jsonld_to_event(data: dict, default_venue: str) -> Optional[Event]:
    """Convert a JSON-LD Event to our Event model."""
    name = data.get("name", "").strip()
    if not name:
        return None

    # Date
    start_date = data.get("startDate", "")
    if not start_date:
        return None
    try:
        if "T" in start_date:
            dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(start_date, "%Y-%m-%d")
        event_date = dt.date()
        time_str = format_event_time(dt) if "T" in start_date else None
    except ValueError:
        return None

    # Venue — prefer embedded, fall back to the venue we're scraping
    venue = default_venue
    location = data.get("location", {})
    if isinstance(location, dict):
        loc_name = location.get("name", "")
        if loc_name:
            venue = normalize_venue_name(loc_name)

    url = data.get("url")

    return Event(
        artist=name,
        venue=venue,
        date=event_date,
        time=time_str,
        source=_venue_source_tag(default_venue),
        url=url,
        image_url=first_image_url(data.get("image")),
    )


def _try_generic_parse(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Generic DOM parser — tries common event listing patterns.
    
    Many venue sites use WordPress with events plugins (The Events Calendar,
    EventOn, etc.) or Squarespace event collections. This tries to handle
    the most common patterns.
    """
    events = []

    # Common selectors for event listings across CMS platforms
    selectors = [
        # WordPress: The Events Calendar plugin
        ".tribe-events-list .tribe-events-list-event",
        ".type-tribe_events",
        # WordPress: EventOn
        ".eventon_list_event a",
        # Squarespace
        ".eventlist-event",
        ".summary-item",
        # Generic patterns
        ".event-item", ".event-listing", ".event-card",
        "[class*='event-item']", "[class*='eventItem']",
        "article[class*='event']",
        # Table-based calendars
        "table.events tr",
    ]

    listings = []
    for selector in selectors:
        listings = soup.select(selector)
        if listings:
            break

    for listing in listings:
        try:
            # Title — precise selectors only (avoid [class*=] which can match <body>)
            title_el = listing.select_one(
                "h1 a, h2 a, h3 a, h1, h2, h3, "
                ".tribe-events-list-event-title a, "
                ".eventlist-title a, .eventlist-title-link, "
                ".summary-title a"
            )
            title = title_el.get_text(strip=True) if title_el else ""

            # Date — precise selectors only
            date_el = listing.select_one(
                "time[datetime], .tribe-event-schedule-details abbr, "
                ".eventlist-meta-date, "
                ".summary-metadata-item--date"
            )

            event_date = None
            if date_el:
                # Try datetime attribute first
                dt_attr = date_el.get("datetime")
                if dt_attr:
                    try:
                        event_date = datetime.fromisoformat(
                            dt_attr.replace("Z", "+00:00")
                        ).date()
                    except ValueError:
                        pass
                # Fall back to text parsing
                if not event_date:
                    event_date = parse_date_text(date_el.get_text(strip=True))

            # Time — try specific start-time selectors before containers
            time_el = (
                listing.select_one("time.event-time-localized-start") or
                listing.select_one(".tribe-event-time") or
                listing.select_one(".eventlist-meta-time")
            )
            time_str = time_el.get_text(strip=True) if time_el else None

            if not title or not event_date:
                continue

            # URL
            url = None
            if title_el and title_el.name == "a":
                url = title_el.get("href")
            if url and not url.startswith("http"):
                url = None  # Skip relative URLs for now

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=_venue_source_tag(venue_name),
                url=url,
            ))
        except Exception:
            continue

    return events


def _parse_hi_tone(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Hi Tone events from hitonecafe.com .eventWrapper cards."""
    events = []

    for card in soup.select(".eventWrapper"):
        try:
            date_el = card.select_one("[class*='eventMonth']")
            title_el = card.select_one("h2, h3")
            link_el = card.select_one("a[href*='/event/']")

            if not date_el or not title_el:
                continue

            title = title_el.get_text(strip=True)
            date_text = date_el.get_text(strip=True)

            event_date = parse_date_text(date_text)
            if not event_date:
                continue

            url = link_el["href"] if link_el else None

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                source=_venue_source_tag(venue_name),
                url=url,
            ))
        except Exception:
            continue

    return events


def _parse_minglewood(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Minglewood Hall events from .tw-name / .tw-date-time cards."""
    events = []

    for card in soup.select(".seven.columns"):
        try:
            name_el = card.select_one(".tw-name")
            date_el = card.select_one(".tw-date-time")
            link_el = card.select_one("a[href*='/event/']")

            if not name_el or not date_el:
                continue

            title = name_el.get_text(strip=True)
            date_text = date_el.get_text(strip=True)

            event_date = parse_date_text(date_text)
            if not event_date:
                continue

            url = link_el["href"] if link_el else None

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                source=_venue_source_tag(venue_name),
                url=url,
            ))
        except Exception:
            continue

    return events


def _parse_graceland(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Graceland Live shows from Wix section-based layout."""
    events = []

    for section in soup.select('section[data-block-level-container="ClassicSection"]'):
        try:
            # Each event section has an h1 with the artist name
            h1 = section.select_one("h1.font_0")
            if not h1:
                continue

            title = h1.get_text(strip=True)
            if not title:
                continue

            # Graceland titles are ALL CAPS — convert to title case
            if title == title.upper() and len(title) > 3:
                title = title.title()

            # Date is in h5 elements — find one that looks like a date
            event_date = None
            for h5 in section.select("h5.font_5"):
                h5_text = h5.get_text(strip=True)
                # Skip support acts ("with ...") and sale info ("ON SALE ...")
                if h5_text.lower().startswith("with ") or "on sale" in h5_text.lower():
                    continue
                event_date = parse_date_text(h5_text)
                if event_date:
                    break

            if not event_date:
                continue

            # Ticket URL from the TICKETS button
            url = None
            ticket_link = section.select_one('a[aria-label="TICKETS"]')
            if ticket_link:
                href = ticket_link.get("href", "")
                if href.startswith("http"):
                    url = href
                elif href.startswith("/"):
                    url = "https://www.gracelandlive.com" + href

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                source=_venue_source_tag(venue_name),
                url=url,
                image_url=_img_src(section),
            ))
        except Exception:
            continue

    return events


def _parse_elfsight(venue_name: str, page_url: str, widget_id: str) -> List[Event]:
    """Parse events from an Elfsight Event Calendar widget via its JSON API."""
    from urllib.parse import quote
    events = []

    api_url = (
        f"https://core.service.elfsight.com/p/boot/"
        f"?page={quote(page_url, safe='')}&w={widget_id}"
    )

    resp = get_with_retry(api_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    # Navigate to the events list in the nested JSON
    widgets = data.get("data", {}).get("widgets", {})
    widget = widgets.get(widget_id, {})
    settings = widget.get("data", {}).get("settings", {})
    event_list = settings.get("events", [])

    for item in event_list:
        try:
            name = item.get("name", "").strip()
            if not name:
                continue

            start = item.get("start", {})
            date_str = start.get("date", "")
            time_str_raw = start.get("time", "")

            if not date_str:
                continue

            event_date = datetime.strptime(date_str, "%Y-%m-%d").date()

            # Convert 24h time to 12h format
            time_str = None
            if time_str_raw:
                try:
                    t = datetime.strptime(time_str_raw, "%H:%M")
                    time_str = format_event_time(t)
                except ValueError:
                    time_str = time_str_raw

            # Ticket URL
            url = None
            btn_link = item.get("buttonLink", {})
            if isinstance(btn_link, dict):
                link_val = btn_link.get("value", "")
                if link_val and link_val.startswith("http"):
                    url = link_val

            # Cover art — Elfsight uses varied keys across widget versions.
            image_url = None
            for key in ("image", "cover", "poster", "photo", "picture"):
                image_url = first_image_url(item.get(key))
                if image_url:
                    break

            events.append(Event(
                artist=name,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=_venue_source_tag(venue_name),
                url=url,
                image_url=image_url,
            ))
        except Exception:
            continue

    return events


def _parse_landers(soup: BeautifulSoup, venue_name: str) -> tuple:
    """Parse Landers Center events - filter for music and concerts only.

    Returns (events, non_music): the arena's calendar is mostly hockey,
    G-League basketball and cheer competitions, and a month with no concert
    is normal — the count lets the dispatcher report that honestly rather
    than as "page structure may have changed".

    Events are in <div class="eventItem entry"> containers.
    Title is in <h3 class="title">, tagline in <h4 class="tagline">.
    Date is in <div class="date"> with month/day spans.
    """
    events = []
    non_music = 0

    # Music/concert keywords for filtering
    music_keywords = [
        "concert", "tour", "live", "music", "band", "artist",
        "singer", "gospel", "worship", "christian", "jam",
        "tribute", "rock", "country", "blues", "jazz", "soul",
        "hip hop", "r&b", "rap", "dj", "festival"
    ]

    # Non-music events to exclude
    exclude_keywords = [
        "comedy", "comedian", "stand-up", "stand up",
        "rodeo", "circus", "monster jam", "monster truck",
        "harlem globetrotters", "globetrotter",
        "disney on ice", "ice show", "skating",
        "blippi", "kid show", "children", "family show",
        "wrestling", "wwe", "basketball", "hockey", "game", "hustle"
    ]

    # Find event items specifically - <div class="eventItem entry ...">
    event_items = soup.find_all("div", class_=lambda x: x and "eventItem" in x)

    for item in event_items:
        try:
            # Extract event title from <h3 class="title">
            title_elem = item.find("h3", class_="title")
            if not title_elem:
                continue

            # Get title text (inside the <a> tag)
            title_link = title_elem.find("a")
            if not title_link:
                continue

            title = title_link.get_text(strip=True)
            url = title_link.get("href", "")

            # Make URL absolute if needed
            if url and not url.startswith("http"):
                url = f"https://www.landerscenter.com{url}"

            # Check for tagline (subtitle with performer names)
            tagline_elem = item.find("h4", class_="tagline")
            tagline = tagline_elem.get_text(strip=True) if tagline_elem else ""

            # Combine title and tagline for filtering
            combined_text = f"{title} {tagline}".lower()

            # Skip non-music events
            if any(keyword in combined_text for keyword in exclude_keywords):
                non_music += 1
                continue

            # Only include if it has music keywords
            if not any(keyword in combined_text for keyword in music_keywords):
                non_music += 1
                continue

            # Extract date from <div class="date">
            date_elem = item.find("div", class_="date")
            if not date_elem:
                continue

            # Date is in format: <span class="m-date__month">Mar</span><span class="m-date__day">13</span>
            month_span = date_elem.find("span", class_=lambda x: x and "month" in str(x).lower())
            day_span = date_elem.find("span", class_=lambda x: x and "day" in str(x).lower())

            if not month_span or not day_span:
                continue

            date_str = f"{month_span.get_text(strip=True)} {day_span.get_text(strip=True)}"

            # Parse date using shared utility
            event_date = parse_date_text(date_str)
            if not event_date:
                continue

            # Extract time from <h5 class="time">
            time_elem = item.find("h5", class_="time")
            time_str = None
            if time_elem:
                start_span = time_elem.find("span", class_="start")
                if start_span:
                    time_str = start_span.get_text(strip=True)

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=_venue_source_tag(venue_name),
                url=url,
            ))

        except Exception:
            continue

    return events, non_music

def _parse_orpheum(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Orpheum Theatre events from orpheum-memphis.com.
    
    Events are in h1 elements with links to /events/[slug].
    Dates are in sibling <p class="font-medium"> elements.
    """
    events = []
    
    # Find all h1 elements (event titles)
    for h1 in soup.find_all('h1'):
        try:
            # Look for link to event detail page
            link = h1.find('a', href=lambda x: x and '/events/' in str(x))
            if not link:
                continue
            
            title = link.get_text(strip=True)
            url = link.get('href')
            
            # Make URL absolute if needed
            if url and not url.startswith('http'):
                url = f"https://www.orpheum-memphis.com{url}"
            
            # Find the parent container and look for date
            container = h1.parent
            date_elem = None
            
            # Walk up the tree looking for the date element
            for _ in range(10):  # Limit depth to avoid infinite loop
                if not container:
                    break
                date_elem = container.find('p', class_='font-medium')
                if date_elem:
                    break
                container = container.parent
            
            if not date_elem:
                continue
            
            date_text = date_elem.get_text(strip=True)
            
            # Parse date using shared utility
            event_date = parse_date_text(date_text)
            if not event_date:
                continue
            
            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                source=_venue_source_tag(venue_name),
                url=url,
            ))
            
        except Exception:
            continue
    
    return events


def _parse_overton_shell(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Overton Park Shell events from Squarespace event list.

    Upcoming events are in <article class="eventlist-event--upcoming">.
    Date is in <time class="event-date" datetime="YYYY-MM-DD">.
    Title is in <h1 class="eventlist-title">.
    """
    events = []

    for article in soup.select("article.eventlist-event--upcoming"):
        try:
            # Title
            title_link = article.select_one("a.eventlist-title-link")
            if not title_link:
                continue

            title = title_link.get_text(strip=True)
            url = title_link.get("href", "")
            if url and not url.startswith("http"):
                url = f"https://overtonparkshell.org{url}"

            # Date from <time class="event-date" datetime="YYYY-MM-DD">
            date_elem = article.select_one("time.event-date")
            if not date_elem:
                continue

            date_attr = date_elem.get("datetime", "")
            if not date_attr:
                continue

            event_date = date.fromisoformat(date_attr)

            # Start time
            time_elem = article.select_one("time.event-time-localized-start")
            time_str = time_elem.get_text(strip=True) if time_elem else None

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=_venue_source_tag(venue_name),
                url=url,
            ))

        except Exception:
            continue

    return events


def _parse_south_main_sounds(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse South Main Sounds events from Bandzoogle table.

    Events are in <table> rows: <tr class="border-accent">.
    Title in td.event-name, date in td.event-date .date-long time.from .date.
    Dates have no year — infer from current date.
    """
    events = []
    current_year = date.today().year

    for row in soup.select("table.table-style tr.border-accent"):
        try:
            # Title — first span.text without text-tertiary class
            title_elem = row.select_one("td.event-name span.text:not(.text-tertiary)")
            if not title_elem:
                continue

            title = title_elem.get_text(strip=True)

            # Strip "at South Main Sounds" suffix from title
            for suffix in [" at South Main Sounds!", " at South Main Sounds"]:
                if title.endswith(suffix):
                    title = title[:-len(suffix)]
                    break

            # Link
            link_elem = row.select_one("td.event-name a.event_details")
            url = ""
            if link_elem:
                url = link_elem.get("href", "")
                if url and not url.startswith("http"):
                    url = f"https://southmainsounds.com{url}"

            # Date — "Saturday, March 7" (no year)
            date_elem = row.select_one("td.event-date .date-long time.from .date")
            if not date_elem:
                continue

            date_text = date_elem.get_text(strip=True)

            # Parse date — format: "Saturday, March 7"
            event_date = None
            try:
                # Remove day-of-week prefix
                parts = date_text.split(", ", 1)
                if len(parts) == 2:
                    date_text = parts[1]

                parsed = datetime.strptime(f"{date_text} {current_year}", "%B %d %Y")
                event_date = parsed.date()

                # If date is in the past, assume next year
                if event_date < date.today():
                    event_date = event_date.replace(year=current_year + 1)
            except ValueError:
                continue

            if not event_date:
                continue

            # Start time — "7:00PM"
            time_elem = row.select_one("td.event-date .date-long time.from .time")
            time_str = time_elem.get_text(strip=True) if time_elem else None

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=_venue_source_tag(venue_name),
                url=url,
            ))

        except Exception:
            continue

    return events


# Wix Events app id — its widgets' server-rendered data lives under this key
# in the page's `wix-warmup-data` script tag.
_WIX_EVENTS_APP_ID = "140603ad-af8d-84a5-2c80-a0f60cb47351"


def _wix_warmup_events(soup: BeautifulSoup) -> list:
    """Raw event dicts from a Wix Events page's warmup-data JSON blob.

    Shared by every Wix Events venue (Flyway, Society). A page can carry more
    than one events widget, so the one holding the most events wins.
    """
    script_tag = soup.find("script", {"id": "wix-warmup-data"})
    if not script_tag or not script_tag.string:
        return []

    try:
        data = json.loads(script_tag.string)
    except (json.JSONDecodeError, ValueError):
        return []

    wix_events_app = data.get("appsWarmupData", {}).get(_WIX_EVENTS_APP_ID, {})

    raw_events = []
    for widget_data in wix_events_app.values():
        if isinstance(widget_data, dict):
            nested = widget_data.get("events", {})
            if isinstance(nested, dict) and isinstance(nested.get("events"), list):
                candidate = nested["events"]
                if len(candidate) > len(raw_events):
                    raw_events = candidate
    return raw_events


def _wix_event_start(event: dict):
    """A Wix event's start as a Central-time datetime, or None.

    Wix stores UTC ("2026-10-04T00:30:00Z"); converting to America/Chicago is
    what keeps a 7:30 PM show on the right day on the UTC Actions runner.
    """
    start_date_str = ((event.get("scheduling") or {}).get("config") or {}).get("startDate")
    if not start_date_str:
        return None
    dt_utc = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
    return dt_utc.astimezone(ZoneInfo("America/Chicago"))


def _parse_flyway(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Flyway Brewing events from Wix warmup data JSON blob."""
    events = []

    for event in _wix_warmup_events(soup):
        try:
            title = event.get("title", "").strip()
            if not title:
                continue

            # Exclude clearly non-music events (comedy, lectures, markets).
            # Don't require music keywords — artist-name-only titles won't match them.
            text = title.lower()
            if any(kw in text for kw in EXCLUDE_KEYWORDS):
                if not any(mk in text for mk in MUSIC_KEYWORDS):
                    continue

            dt_local = _wix_event_start(event)
            if not dt_local:
                continue

            slug = event.get("slug", "")
            url = f"https://www.flywaybrewingmemphis.com/events/{slug}" if slug else None

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=dt_local.date(),
                time=format_event_time(dt_local),
                source=_venue_source_tag(venue_name),
                url=url,
                image_url=first_image_url(event.get("mainImage")),
            ))
        except Exception:
            continue

    return events


# Society Memphis is a skatepark + coffee shop, so much of its calendar is not
# music. Its shows, though, are billed by artist name alone ("Encircled
# Throne", "Phases Psych Fest") with no description, so a positive music-word
# test drops most of them — verified against the live calendar 2026-09-30.
# The filter is therefore a denylist of Society's recurring non-music
# programming, which is a small and recognizable set.
_SOCIETY_EXCLUDE_KEYWORDS = (
    "market", "chess", "wrestling", "thursdays are rad",
    "fingerboard", "tech deck",  # mini-skateboard meetups, billed as "jams"
    "cosplay", "gaming", "tournament", "fight night", "drifting", "rc car",
    "private event", "private party", "closed for", "rental",
    "workshop", "swap meet", "pop-up shop", "popup shop", "flea",
)

# Skate sessions, skate school, "Cookout and Skate". Matched as a whole word so
# a show *at* the skatepark ("Xavier Wulf Skatepark Popout") is kept.
_SOCIETY_SKATE_WORDS = ("skate", "skating", "skateboarding")


def _has_word(text: str, phrases) -> bool:
    """Whole-word/phrase match (a trailing plural "s" allowed). A substring
    test would read "skate" into "Skatepark" and "play" into "Playboi"."""
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(p.strip()) + r"s?(?![a-z0-9])", text)
        for p in phrases if p.strip()
    )


def _society_is_music(title: str, categories: List[str]) -> bool:
    """Whether a Society Memphis listing is a music event.

    Dropped: Society's own non-music programming (_SOCIETY_EXCLUDE_KEYWORDS,
    skate sessions), and generic non-music (comedy, trivia, yoga...) unless the
    title also carries a music keyword. Everything else is kept, because an
    artist-only title is the normal shape of a show here.
    """
    head = f"{title} {' '.join(categories)}".lower()
    if any(kw in head for kw in _SOCIETY_EXCLUDE_KEYWORDS):
        return False
    if _has_word(head, _SOCIETY_SKATE_WORDS):
        return False
    if _has_word(head, EXCLUDE_KEYWORDS) and not _has_word(head, MUSIC_KEYWORDS):
        return False
    return True


def _parse_society(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Society Memphis (Wix Events) and keep only music events."""
    events = []

    for event in _wix_warmup_events(soup):
        try:
            title = (event.get("title") or "").strip()
            if not title:
                continue

            categories = [
                (c.get("name") or "") if isinstance(c, dict) else str(c)
                for c in (event.get("categories") or [])
            ]
            if not _society_is_music(title, categories):
                continue

            dt_local = _wix_event_start(event)
            if not dt_local:
                continue

            slug = event.get("slug", "")
            url = f"https://www.societymemphis.com/event-details/{slug}" if slug else None

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=dt_local.date(),
                time=format_event_time(dt_local),
                source=_venue_source_tag(venue_name),
                url=url,
                image_url=first_image_url(event.get("mainImage")),
            ))
        except Exception:
            continue

    return events


def _fetch_blues_city_cafe(venue_info: dict) -> SourceResult:
    """Fetch events from Blues City Cafe's month-per-page WordPress calendar.

    URL pattern: /music/?calendar_month=jan&calendar_yr=2026
    Cells with events use td.day-with-date or td.current-day; cells with no
    events carry an additional no-events class and are skipped.
    """
    name = venue_info["name"]
    base_url = venue_info["calendar_url"]
    result = SourceResult(source_name=f"Venue: {name}")

    today = date.today()

    # Build list of (year, month) pairs covering today → SCRAPER_END_DATE
    months = []
    cursor = today.replace(day=1)
    while cursor <= SCRAPER_END_DATE:
        months.append((cursor.year, cursor.month))
        cursor = date(cursor.year + (cursor.month // 12), cursor.month % 12 + 1, 1)

    try:
        for year, month in months:
            mon_abbr = datetime(year, month, 1).strftime("%b").lower()
            url = f"{base_url}?calendar_month={mon_abbr}&calendar_yr={year}"

            resp = get_with_retry(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            for cell in soup.select("td.day-with-date, td.current-day"):
                if "no-events" in (cell.get("class") or []):
                    continue

                day_span = cell.find("span", recursive=False)
                if not day_span:
                    continue
                day_text = day_span.get_text(strip=True)
                if not day_text.isdigit():
                    continue

                # event-title span holds the band name (same text as the direct <a> node)
                event_title_el = cell.find("span", class_="event-title")
                title = event_title_el.get_text(strip=True) if event_title_el else ""
                if not title:
                    continue

                # Time is the text node immediately after <strong>Time:</strong>
                strong = cell.find("strong")
                time_str = None
                if strong and strong.next_sibling:
                    raw = str(strong.next_sibling).strip()
                    if raw:
                        time_str = raw

                try:
                    event_date = date(year, month, int(day_text))
                except ValueError:
                    continue

                result.events_found += 1
                if not (START_DATE <= event_date <= SCRAPER_END_DATE):
                    result.events_filtered += 1
                else:
                    result.events.append(Event(
                        artist=title,
                        venue=name,
                        date=event_date,
                        time=time_str,
                        source=_venue_source_tag(name),
                        url=base_url,
                    ))

        if result.events_found == 0:
            result.error_message = "0 events parsed — page structure may have changed"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Request failed: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"

    return result

    return events
