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
from ..models import Event, SourceResult
from ..http_utils import get_with_retry
from ..config import (
    VENUES, START_DATE, END_DATE, SCRAPER_END_DATE,
    TICKETMASTER_API_KEY,
    normalize_venue_name, is_music_event,
)
from ..date_utils import parse_date_text

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


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
    """Fetch events from each venue separately (for detailed logging)."""
    results = []

    for venue_key, venue_info in VENUES.items():
        url = venue_info.get("calendar_url")
        scraper_type = venue_info.get("scraper", "generic")

        if not url or scraper_type == "manual_only":
            continue

        venue_result = _scrape_venue(venue_key, venue_info)
        results.append(venue_result)

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
        response = get_with_retry(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        events_data = data.get("_embedded", {}).get("events", [])
        result.events_found = len(events_data)

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
                        time_str = t.strftime("%-I:%M %p").replace(":00 ", " ")
                    except ValueError:
                        pass

                result.events.append(Event(
                    artist=event_data.get("name", "").strip(),
                    venue=name,
                    date=event_date,
                    time=time_str,
                    source=f"Venue: {name}",
                    url=event_data.get("url"),
                ))
            except Exception:
                continue

        if result.events_found == 0:
            result.error_message = "0 events from Ticketmaster for this venue"

    except requests.exceptions.RequestException as e:
        result.success = False
        result.error_message = f"Ticketmaster API error: {str(e)[:80]}"
    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:80]}"

    return result


def _parse_crosstown_arts(soup: BeautifulSoup, venue_name: str) -> List[Event]:
    """Parse Crosstown Arts events — WordPress with The Events Calendar v6+.

    The Events Calendar v6 uses new class names vs legacy v5. We also apply
    is_music_event() because Crosstown's calendar mixes music and gallery events.
    """
    events = []

    for article in soup.select("article.tribe-events-calendar-list__event"):
        try:
            title_el = article.select_one(".tribe-events-calendar-list__event-title-link")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title or not is_music_event(title, ""):
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
                source=f"Venue: {venue_name}",
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
        time_str = dt.strftime("%-I:%M %p").replace(":00 ", " ") if "T" in start_date else None
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
        source=f"Venue: {default_venue}",
        url=url,
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
                source=f"Venue: {venue_name}",
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
                source=f"Venue: {venue_name}",
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
                source=f"Venue: {venue_name}",
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
                source=f"Venue: {venue_name}",
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
                source=f"Venue: {venue_name}",
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
                source=f"Venue: {venue_name}",
                url=url,
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
                    time_str = t.strftime("%-I:%M %p").replace(":00 ", " ")
                except ValueError:
                    time_str = time_str_raw

            # Ticket URL
            url = None
            btn_link = item.get("buttonLink", {})
            if isinstance(btn_link, dict):
                link_val = btn_link.get("value", "")
                if link_val and link_val.startswith("http"):
                    url = link_val

            events.append(Event(
                artist=name,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=f"Venue: {venue_name}",
                url=url,
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
                source=f"Venue: {venue_name}",
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
                source=f"Venue: {venue_name}",
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
                source=f"Venue: {venue_name}",
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
                source=f"Venue: {venue_name}",
                url=url,
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

    raw_events = []
    for widget_data in wix_events_app.values():
        if isinstance(widget_data, dict):
            nested = widget_data.get("events", {})
            if isinstance(nested, dict) and "events" in nested:
                raw_events = nested["events"]
                break

    for event in raw_events:
        try:
            title = event.get("title", "").strip()
            if not title:
                continue

            # Apply music filter — Flyway hosts non-music events (e.g. lectures)
            if not is_music_event(title):
                continue

            start_date_str = (event.get("scheduling") or {}).get("config", {}).get("startDate")
            if not start_date_str:
                continue

            dt_utc = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone(CENTRAL)
            event_date = dt_local.date()

            time_str = dt_local.strftime("%-I:%M %p").replace(":00 ", " ")

            slug = event.get("slug", "")
            url = f"https://www.flywaybrewingmemphis.com/events/{slug}" if slug else None

            events.append(Event(
                artist=title,
                venue=venue_name,
                date=event_date,
                time=time_str,
                source=f"Venue: {venue_name}",
                url=url,
            ))
        except Exception:
            continue

    return events
