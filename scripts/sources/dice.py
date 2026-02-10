"""
DICE Memphis browse page scraper.
Target: https://dice.fm/browse/Memphis:35.149844:-90.049566

DICE uses heavy JavaScript rendering, so we try to extract from
any JSON-LD or embedded JSON data in the initial HTML response.
"""

import json
import logging
import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

from scripts.sources import Event, normalize_venue

logger = logging.getLogger("concert-calendar.dice")

MEMPHIS_TZ = ZoneInfo("America/Chicago")
DICE_URL = "https://dice.fm/browse/Memphis:35.149844:-90.049566"


def fetch_dice(start_date: datetime, end_date: datetime) -> list[Event]:
    """Fetch Memphis music events from DICE."""
    events = []

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }
        response = requests.get(DICE_URL, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Strategy 1: Look for JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        event = _parse_dice_jsonld(item, start_date, end_date)
                        if event:
                            events.append(event)
                elif isinstance(data, dict):
                    event = _parse_dice_jsonld(data, start_date, end_date)
                    if event:
                        events.append(event)
            except (json.JSONDecodeError, TypeError):
                continue

        # Strategy 2: Look for __NEXT_DATA__ or similar embedded JSON
        for script in soup.find_all("script"):
            if script.string and "__NEXT_DATA__" in (script.string or ""):
                try:
                    match = re.search(r'__NEXT_DATA__\s*=\s*({.*?})\s*;?\s*</script>',
                                      response.text, re.DOTALL)
                    if match:
                        next_data = json.loads(match.group(1))
                        events.extend(_parse_dice_next_data(next_data, start_date, end_date))
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug(f"Failed to parse DICE __NEXT_DATA__: {e}")

        # Strategy 3: Parse HTML event cards if above methods found nothing
        if not events:
            event_elements = soup.select("[class*='event'], [class*='Event'], a[href*='/event/']")
            for el in event_elements:
                try:
                    title = el.get_text(strip=True)
                    link = el.get("href", "")
                    if link and not link.startswith("http"):
                        link = f"https://dice.fm{link}"

                    if title and len(title) < 200:  # Sanity check
                        events.append(Event(
                            artist=title.strip(),
                            venue="See DICE listing",
                            date=start_date,  # We don't have specific date from card
                            source="DICE",
                            url=link or None,
                            raw_title=title,
                        ))
                except Exception:
                    continue

        if not events:
            logger.warning("DICE: no events parsed — page may require JavaScript rendering")

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"DICE fetch error: {e}")

    return events


def _parse_dice_jsonld(data: dict, start_date: datetime, end_date: datetime) -> Event | None:
    """Parse a JSON-LD Event from DICE."""
    if data.get("@type") not in ("Event", "MusicEvent"):
        return None

    name = data.get("name", "")
    if not name:
        return None

    start_str = data.get("startDate", "")
    event_dt = None
    if start_str:
        try:
            event_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            event_dt = event_dt.astimezone(MEMPHIS_TZ)
        except ValueError:
            return None

    if not event_dt:
        return None

    if event_dt.date() < start_date.date() or event_dt.date() >= end_date.date():
        return None

    location = data.get("location", {})
    venue = location.get("name", "") if isinstance(location, dict) else ""

    display_time = None
    if event_dt.hour != 0:
        display_time = event_dt.strftime("%-I:%M %p").lstrip("0")

    return Event(
        artist=name.strip(),
        venue=normalize_venue(venue) if venue else "See DICE listing",
        date=event_dt,
        time=display_time,
        source="DICE",
        url=data.get("url"),
        raw_title=name,
    )


def _parse_dice_next_data(data: dict, start_date: datetime, end_date: datetime) -> list[Event]:
    """Attempt to extract events from DICE's Next.js page data."""
    events = []

    # Navigate the Next.js data structure (this is fragile and may need updating)
    try:
        props = data.get("props", {}).get("pageProps", {})
        event_list = props.get("events", props.get("initialEvents", []))

        for item in event_list:
            name = item.get("name", item.get("title", ""))
            venue_name = item.get("venue", {}).get("name", "") if isinstance(item.get("venue"), dict) else ""
            date_str = item.get("date", item.get("startDate", ""))

            if not name:
                continue

            event_dt = None
            if date_str:
                try:
                    event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    event_dt = event_dt.astimezone(MEMPHIS_TZ)
                except ValueError:
                    continue

            if not event_dt:
                continue

            if event_dt.date() < start_date.date() or event_dt.date() >= end_date.date():
                continue

            display_time = None
            if event_dt.hour != 0:
                display_time = event_dt.strftime("%-I:%M %p").lstrip("0")

            events.append(Event(
                artist=name.strip(),
                venue=normalize_venue(venue_name) if venue_name else "See DICE listing",
                date=event_dt,
                time=display_time,
                source="DICE",
                url=item.get("url"),
                raw_title=name,
            ))
    except (KeyError, TypeError, AttributeError) as e:
        logger.debug(f"DICE Next.js data parsing failed: {e}")

    return events
