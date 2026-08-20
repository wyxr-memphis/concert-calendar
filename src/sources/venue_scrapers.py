"""Venue website scrapers.

Each venue with a web calendar gets a scraper function.
When a venue changes their site, you only fix that one function.
"""

from typing import List, Optional
import requests
import json
import re
from datetime import datetime, date
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from ..models import Event, SourceResult, first_image_url, best_ticketmaster_image
from ..http_utils import get_with_retry, fetch_ticketmaster_events
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

    try:
        response = get_with_retry(url, headers=HEADERS, timeout=15, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        scraper_type = venue_info.get("scraper", "generic")

        # Custom scrapers for specific venues
        if scraper_type == "hi_tone":
            events = _parse_hi_tone(soup, name)
        elif scraper_type == "minglewood":
            events = _parse_minglewood(soup, name)
        elif scraper_type == "hernandos":
            events = _parse_hernandos(soup, name)
        elif scraper_type == "growlers":
            events = _parse_growlers(soup, name)
        elif scraper_type == "graceland":
            events = _parse_graceland(soup, name)
        elif scraper_type == "elfsight":
            widget_id = venue_info.get("elfsight_widget_id", "")
            events = _parse_elfsight(name, url, widget_id)
        elif scraper_type == "orpheum":
            events = _parse_orpheum(soup, name)
        elif scraper_type == "overton_shell":
            events = _parse_overton_shell(soup, name)
        elif scraper_type == "south_main_sounds":
            events = _parse_south_main_sounds(soup, name)
        elif scraper_type == "landers":
            events = _parse_landers(soup, name)
        elif scraper_type == "crosstown_arts":
            events = _parse_crosstown_arts(soup, name)
        elif scraper_type == "flyway":
            events = _parse_flyway(soup, name)
        elif scraper_type == "bbkings":
            events = _parse_bbkings(soup, name)
        elif scraper_type == "crosstown_beer":
            events = _parse_crosstown_beer(soup, name)
        else:
            # Try JSON-LD first (many event sites embed structured data)
            events = _try_jsonld(soup, name)

            # If no JSON-LD, try generic DOM parsing
            if not events:
                events = _try_generic_parse(soup, name)

        result.events_found = len(events)
        for event in events:
            if not (START_DATE <= event.date <= SCRAPER_END_DATE):
                result.events_filtered += 1
            else:
                # Events from venue calendars are music events by definition —
                # skip is_music_event() check which false-negatives on artist names
                result.events.append(event)

        if result.events_found == 0:
            result.error_message = f"0 events parsed — page structure may have changed"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Request failed: {str(e)[:80]}"
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


def _parse_crosstown_arts(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Crosstown Arts events — WordPress with The Events Calendar v6+.

    Crosstown's calendar mixes music (The Green Room), film screenings, and
    gallery exhibitions. We filter by the WordPress category embedded in the
    article's class list rather than is_music_event() — artist-only titles like
    "An Intimate Night with Keia" carry no music keywords and would be rejected.
    """
    events = []

    for article in soup.select("article.tribe-events-calendar-list__event"):
        try:
            classes = article.get("class", [])
            if any(c in ("cat_gallery", "tribe_events_cat-gallery") for c in classes):
                continue

            title_el = article.select_one(".tribe-events-calendar-list__event-title-link")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title:
                continue
            # Crosstown's calendar includes film screenings — exclude them
            if re.search(r'\bfilm\b', title, re.I):
                continue

            date_el = article.select_one("time.tribe-events-calendar-list__event-datetime")
            if not date_el:
                continue
            dt_attr = date_el.get("datetime")
            event_date = None
            if dt_attr:
                try:
                    event_date = datetime.strptime(dt_attr[:10], "%Y-%m-%d").date()
                except ValueError:
                    pass
            if not event_date:
                event_date = parse_date_text(date_el.get_text(strip=True))
            if not event_date:
                continue

            time_str = None
            date_text = date_el.get_text(strip=True)
            time_match = re.search(r"@\s*(\d{1,2}:\d{2}\s*[ap]m)", date_text, re.I)
            if time_match:
                time_str = time_match.group(1).strip()

            url = title_el.get("href")

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


def _parse_hernandos(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Hernando's Hideaway events from .event-info-block cards."""
    events = []

    for card in soup.select(".event-info-block"):
        try:
            title_el = card.select_one(".title a, .title")
            date_el = card.select_one(".date")
            time_el = card.select_one(".see-showtime")
            link_el = card.select_one("a[href]")

            if not title_el or not date_el:
                continue

            title = title_el.get_text(strip=True)
            date_text = date_el.get_text(strip=True)

            event_date = parse_date_text(date_text)
            if not event_date:
                continue

            time_str = time_el.get_text(strip=True) if time_el else None
            url = link_el["href"] if link_el else None

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


def _parse_growlers(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Growlers events from SeeTickets widget on 901growlers.com."""
    events = []

    for card in soup.select("div.seetickets-list-event-container"):
        try:
            title_el = card.select_one("p.event-title a")
            date_el = card.select_one("p.event-date")
            showtime_el = card.select_one("span.see-showtime")
            doortime_el = card.select_one("span.see-doortime")

            if not title_el or not date_el:
                continue

            # Prefer headliners field for cleaner artist name
            headliner_el = card.select_one("p.headliners")
            title = headliner_el.get_text(strip=True) if headliner_el else title_el.get_text(strip=True)
            # Strip trailing "at Growlers" / "at Venue" from SeeTickets titles
            title = re.sub(r'\s+at\s+\S.*$', '', title, flags=re.IGNORECASE).strip()
            if not title:
                title = title_el.get_text(strip=True)
            date_text = date_el.get_text(strip=True)

            event_date = parse_date_text(date_text)
            if not event_date:
                continue

            time_str = None
            if showtime_el:
                time_str = showtime_el.get_text(strip=True)
            elif doortime_el:
                time_str = doortime_el.get_text(strip=True)

            url = title_el.get("href")

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=_venue_source_tag(venue_name),
                url=url,
                image_url=_img_src(card),
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


def _parse_landers(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Landers Center events - filter for music and concerts only.

    Events are in <div class="eventItem entry"> containers.
    Title is in <h3 class="title">, tagline in <h4 class="tagline">.
    Date is in <div class="date"> with month/day spans.
    """
    events = []

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
                continue

            # Only include if it has music keywords
            if not any(keyword in combined_text for keyword in music_keywords):
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

    return events


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


def _parse_bbkings(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse B.B. King's Blues Club events from Webflow CMS collection.

    Events are in div.event7_item cards with:
    - h3 for artist name
    - div.text-size-small for time
    - div[fs-cmsfilter-field="date"] for date (e.g. "Mar 19", no year)
    """
    events = []
    current_year = date.today().year

    for item in soup.select("div.event7_item"):
        try:
            title_el = item.select_one("h3")
            date_el = item.select_one("[fs-cmsfilter-field='date']")
            if not title_el or not date_el:
                continue

            title = title_el.get_text(strip=True)
            if not title:
                continue

            date_text = date_el.get_text(strip=True)
            event_date = parse_date_text(date_text)
            if not event_date:
                continue

            time_el = item.select_one(".event7_name-wrapper .text-size-small")
            time_str = time_el.get_text(strip=True) if time_el else None

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=_venue_source_tag(venue_name),
            ))
        except Exception:
            continue

    return events


def _parse_flyway(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Flyway Brewing events from Wix warmup data JSON blob."""
    events = []
    CENTRAL = ZoneInfo("America/Chicago")

    script_tag = soup.find("script", {"id": "wix-warmup-data"})
    if not script_tag or not script_tag.string:
        return events

    try:
        data = json.loads(script_tag.string)
    except (json.JSONDecodeError, ValueError):
        return events

    # Navigate to the events list; search all widget components for an 'events' list
    apps_data = data.get("appsWarmupData", {})
    wix_events_app = apps_data.get("140603ad-af8d-84a5-2c80-a0f60cb47351", {})

    # Pick the widget component with the most events (page may have multiple widgets)
    raw_events = []
    for widget_data in wix_events_app.values():
        if isinstance(widget_data, dict):
            nested = widget_data.get("events", {})
            if isinstance(nested, dict) and "events" in nested:
                candidate = nested["events"]
                if len(candidate) > len(raw_events):
                    raw_events = candidate

    for event in raw_events:
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

            start_date_str = (event.get("scheduling") or {}).get("config", {}).get("startDate")
            if not start_date_str:
                continue

            dt_utc = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone(CENTRAL)
            event_date = dt_local.date()

            time_str = format_event_time(dt_local)

            slug = event.get("slug", "")
            url = f"https://www.flywaybrewingmemphis.com/events/{slug}" if slug else None

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=_venue_source_tag(venue_name),
                url=url,
                image_url=first_image_url(event.get("mainImage")),
            ))
        except Exception:
            continue

    return events


def _parse_crosstown_beer(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Crosstown Brewing Co. events from Elementor toggle accordion.

    Each accordion item has a date in .elementor-tab-title and event lines in
    .elementor-tab-content. Example content: "4-6pm Live Music – Mark Allen"
    or "4-6pm Live Music – Mark Allen 7-9pm Trivia – Community".

    Only "Live Music" segments are captured; trivia, dog shows, etc. are skipped.
    """
    events = []
    today = date.today()

    # Matches "Wednesday, March 25th" in the toggle title
    DATE_RE = re.compile(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
        r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?",
        re.IGNORECASE,
    )
    # Time token: handles "6pm", "4-6pm", "12pm-9pm", "7:30pm-9pm"
    _T = (
        r"\d{1,2}"                                       # start hour
        r"(?:\s*-\s*\d{1,2})?"                          # optional range like "4-6"
        r"(?::\d{2})?"                                   # optional minutes
        r"(?:am|pm)"                                     # am/pm (must follow for end of range)
        r"(?:\s*-\s*\d{1,2}(?::\d{2})?(?:am|pm))?"     # optional explicit second half
    )
    # Matches an optional preceding time + "Live Music" + optional separator + artist name
    # Stops before the next time token or end of string
    LIVE_MUSIC_RE = re.compile(
        rf"(?:({_T})\s+)?Live Music\s*[–\-,]?\s*(.+?)(?=\s+{_T}|$)",
        re.IGNORECASE,
    )

    for item in soup.select(".elementor-toggle-item"):
        title_el = item.select_one(".elementor-tab-title")
        content_el = item.select_one(".elementor-tab-content")
        if not title_el or not content_el:
            continue

        title_text = title_el.get_text(" ", strip=True)
        content_text = content_el.get_text(" ", strip=True)

        if "live music" not in content_text.lower():
            continue

        date_match = DATE_RE.search(title_text)
        if not date_match:
            continue

        month_str = date_match.group(1)
        day_str = date_match.group(2)

        event_date = None
        for year in (today.year, today.year + 1):
            try:
                candidate = datetime.strptime(f"{month_str} {day_str} {year}", "%B %d %Y").date()
                if candidate >= today:
                    event_date = candidate
                    break
            except ValueError:
                continue

        if not event_date:
            continue

        for m in LIVE_MUSIC_RE.finditer(content_text):
            time_str = m.group(1)  # may be None
            artist = (m.group(2) or "").strip()
            if not artist:
                artist = "Live Music"

            events.append(Event(
                artist=artist,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=_venue_source_tag(venue_name),
                url="https://crosstownbeer.com/events/",
            ))

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
