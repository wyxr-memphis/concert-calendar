"""Parse event artifacts (images, saved web pages) for event extraction.

This module scans the artifacts/ folder for:
  - Images (.png, .jpg, etc.) → processed via Claude vision API
  - Saved web pages (.mhtml, .html) → parsed directly with BeautifulSoup (free, instant)

Simple structure - just drop files in artifacts/:
artifacts/
  ├── bandsintown-memphis.mhtml    (Save As → "Webpage, Single File" in Chrome)
  ├── bside-2026-02-10.png
  ├── bar-dkdc-instagram.jpg
  └── any-concert-listing.html
"""

from typing import Optional, List, Tuple
import base64
import email
import io
import json
import re
from pathlib import Path
from datetime import datetime

from bs4 import BeautifulSoup

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

from ..models import Event, SourceResult
from ..config import START_DATE, END_DATE, normalize_venue_name
from ..date_utils import parse_date_text

SOURCE_NAME = "Artifacts (Vision-Extracted)"
ARTIFACTS_DIR = Path(__file__).parent.parent.parent / "artifacts"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
WEBPAGE_EXTENSIONS = {".mhtml", ".html", ".htm"}


def fetch() -> SourceResult:
    """Scan artifacts folder and extract events from all supported file types."""
    result = SourceResult(source_name=SOURCE_NAME)

    if not ARTIFACTS_DIR.exists():
        result.error_message = "No artifacts/ folder found"
        return result

    # Find all supported files
    artifact_files = []
    for ext in IMAGE_EXTENSIONS | WEBPAGE_EXTENSIONS:
        artifact_files.extend(ARTIFACTS_DIR.glob(f"*{ext}"))
        artifact_files.extend(ARTIFACTS_DIR.glob(f"*{ext.upper()}"))

    # Deduplicate (glob with upper/lower could overlap)
    artifact_files = sorted(set(artifact_files))

    if not artifact_files:
        result.error_message = "No artifacts found"
        return result

    for file_path in artifact_files:
        try:
            suffix = file_path.suffix.lower()
            if suffix in WEBPAGE_EXTENSIONS:
                events = _extract_events_from_webpage(file_path)
            else:
                events = _extract_events_from_image(file_path)

            result.events_found += len(events)

            for event in events:
                if START_DATE <= event.date <= END_DATE:
                    result.events.append(event)

        except Exception as e:
            print(f"  Error processing {file_path.name}: {str(e)[:80]}")
            continue

    return result


# ---------------------------------------------------------------------------
# Web page parsing (MHTML / HTML) — free, no API calls
# ---------------------------------------------------------------------------

def _extract_events_from_webpage(file_path: Path) -> List[Event]:
    """Extract events from a saved web page (MHTML or HTML)."""
    suffix = file_path.suffix.lower()

    if suffix == ".mhtml":
        html = _read_mhtml(file_path)
    else:
        html = file_path.read_text(encoding="utf-8", errors="replace")

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Try site-specific parsers first, then generic
    events = _parse_bandsintown_html(soup, file_path)
    if events:
        return events

    events = _parse_generic_event_html(soup, file_path)
    return events


def _read_mhtml(file_path: Path) -> str:
    """Extract the HTML content from an MHTML (web archive) file."""
    with open(file_path, "rb") as f:
        msg = email.message_from_bytes(f.read())

    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="replace")

    return ""


def _parse_bandsintown_html(soup: BeautifulSoup, source_path: Path) -> List[Event]:
    """Parse events from a Bandsintown city page (saved as MHTML/HTML).

    Bandsintown event cards are <a> tags linking to /e/ with child divs
    containing artist name, venue/event title, and date/time.
    """
    event_links = soup.find_all("a", href=lambda h: h and "/e/" in str(h))
    if not event_links:
        return []

    events = []
    for link in event_links:
        try:
            # Get the info container (first child div with children)
            card_div = link.find("div", recursive=False)
            if not card_div:
                continue

            # Find all top-level child divs — typically: [image_div, info_div]
            top_divs = card_div.find_all("div", recursive=False)

            # Extract text from the info div (usually the second one)
            info_div = None
            for div in top_divs:
                # The info div has text content (artist, venue, date)
                text = div.get_text(strip=True)
                if text and len(text) > 5:
                    info_div = div
                    break

            if not info_div:
                # Fallback: use full link text
                full_text = link.get_text(separator="|", strip=True)
                parts = [p.strip() for p in full_text.split("|") if p.strip()]
                if len(parts) < 3:
                    continue
                artist, venue_text, date_text = parts[0], parts[1], parts[2]
            else:
                # Get distinct text blocks from the info div's children
                text_blocks = []
                for child in info_div.find_all("div", recursive=False):
                    t = child.get_text(strip=True)
                    if t:
                        text_blocks.append(t)

                if len(text_blocks) < 2:
                    continue

                # First block typically contains "ArtistNameVenueName" concatenated
                # inside nested divs. Let's get them separately.
                first_block = info_div.find("div", recursive=False)
                if first_block:
                    inner_divs = first_block.find_all("div", recursive=False)
                    if len(inner_divs) >= 2:
                        artist = inner_divs[0].get_text(strip=True)
                        venue_text = inner_divs[1].get_text(strip=True)
                    elif len(inner_divs) == 1:
                        artist = inner_divs[0].get_text(strip=True)
                        venue_text = ""
                    else:
                        artist = first_block.get_text(strip=True)
                        venue_text = ""
                else:
                    artist = text_blocks[0]
                    venue_text = ""

                # Date is in a later block (contains month abbreviation and time)
                date_text = ""
                for block in text_blocks:
                    if re.search(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d', block):
                        date_text = block
                        break

            if not artist or not date_text:
                continue

            # Parse "Feb 11 - 6:00 PM" format
            event_date, time_str = _parse_bandsintown_date(date_text)
            if not event_date:
                continue

            # Get event URL
            url = link.get("href", "")
            if url and "?" in url:
                url = url.split("?")[0]  # Strip tracking params

            events.append(Event(
                artist=artist,
                venue=normalize_venue_name(venue_text) if venue_text else "Venue TBA",
                date=event_date,
                time=time_str,
                source=f"Artifacts (Bandsintown page)",
                url=url or None,
            ))

        except Exception:
            continue

    return events


def _parse_bandsintown_date(text: str) -> Tuple[Optional[datetime.date], Optional[str]]:
    """Parse 'Feb 11 - 6:00 PM' or 'Feb 11' into (date, time)."""
    text = text.strip()
    time_str = None

    # Split on " - " to separate date and time
    if " - " in text:
        date_part, time_str = text.split(" - ", 1)
        time_str = time_str.strip()
    else:
        date_part = text

    event_date = parse_date_text(date_part.strip())
    return event_date, time_str


def _parse_generic_event_html(soup: BeautifulSoup, source_path: Path) -> List[Event]:
    """Generic HTML event parser — tries JSON-LD, then common DOM patterns."""
    events = []

    # Strategy 1: JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in ("Event", "MusicEvent"):
                    event = _parse_jsonld_event(item, source_path)
                    if event:
                        events.append(event)
        except (json.JSONDecodeError, Exception):
            continue

    if events:
        return events

    # Strategy 2: Common event listing patterns
    selectors = [
        ".event-item", ".event-card", ".event-listing",
        "[class*='event-item']", "[class*='eventItem']",
        "article[class*='event']",
        ".tribe-events-list-event",
        ".eventlist-event",
    ]
    for selector in selectors:
        listings = soup.select(selector)
        if listings:
            for listing in listings:
                title_el = listing.select_one("h2, h3, h4, [class*='title']")
                date_el = listing.select_one("time, [class*='date']")
                venue_el = listing.select_one("[class*='venue'], [class*='location']")

                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                event_date = None
                if date_el:
                    dt_attr = date_el.get("datetime")
                    if dt_attr:
                        try:
                            event_date = datetime.fromisoformat(
                                dt_attr.replace("Z", "+00:00")
                            ).date()
                        except ValueError:
                            pass
                    if not event_date:
                        event_date = parse_date_text(date_el.get_text(strip=True))

                if not event_date:
                    continue

                venue = venue_el.get_text(strip=True) if venue_el else "Venue TBA"

                events.append(Event(
                    artist=title,
                    venue=normalize_venue_name(venue),
                    date=event_date,
                    source=f"Artifacts ({source_path.name})",
                ))
            if events:
                return events

    return events


def _parse_jsonld_event(data: dict, source_path: Path) -> Optional[Event]:
    """Parse a JSON-LD Event object."""
    name = data.get("name", "").strip()
    start_date = data.get("startDate", "")
    if not name or not start_date:
        return None

    try:
        dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        event_date = dt.date()
        time_str = dt.strftime("%-I:%M %p").replace(":00 ", " ")
    except ValueError:
        return None

    location = data.get("location", {})
    venue = location.get("name", "") if isinstance(location, dict) else ""
    url = data.get("url")

    return Event(
        artist=name,
        venue=normalize_venue_name(venue) if venue else "Venue TBA",
        date=event_date,
        time=time_str,
        source=f"Artifacts ({source_path.name})",
        url=url,
    )


# ---------------------------------------------------------------------------
# Image parsing — uses Claude vision API ($0.01/image)
# ---------------------------------------------------------------------------

def _extract_events_from_image(image_path: Path) -> List[Event]:
    """Use Claude vision to extract events from an image."""
    if not ANTHROPIC_AVAILABLE:
        print(f"  Skipping {image_path.name}: anthropic library not installed")
        return []

    # Optimize image if needed (resize/compress large images)
    image_bytes, media_type = _optimize_image(image_path)
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    client = anthropic.Anthropic()

    prompt = f"""Analyze this image and extract music/concert events for the week of {START_DATE} to {END_DATE}.

For EACH visible event, extract:
- artist/act name
- venue (venue name, Instagram handle, website, or "Bandsintown")
- date (in any format visible)
- time (if visible)

IMPORTANT: Focus on events in {START_DATE.strftime('%B %Y')} (this week/month).
Skip events from other months if visible.

Return ONLY a valid JSON array, no other text:
[
  {{
    "artist": "Artist Name",
    "venue": "Venue Name",
    "date": "2/15/2026",
    "time": "9 PM",
    "source_note": "Brief description - e.g. 'Instagram', 'Bandsintown', 'website'"
  }}
]

If no events found, return: []

Extract all visible events for the target week, even if text is small."""

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    response_text = message.content[0].text.strip()

    try:
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start >= 0 and end > start:
            events_data = json.loads(response_text[start:end])
        else:
            events_data = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"  Could not parse JSON from response: {response_text[:100]}")
        print(f"  Error: {str(e)[:80]}")
        return []

    events = []
    for item in events_data:
        try:
            event = _parse_vision_event(item, image_path)
            if event:
                events.append(event)
        except Exception:
            continue

    return events


def _parse_vision_event(data: dict, source_image: Path) -> Optional[Event]:
    """Convert Claude vision extracted event data to Event object."""
    artist = data.get("artist", "").strip()
    venue = data.get("venue", "").strip()
    date_str = data.get("date", "").strip()
    time_str = data.get("time", "").strip()
    source_note = data.get("source_note", "").strip()

    if not artist or not date_str:
        return None

    event_date = parse_date_text(date_str)
    if not event_date:
        return None

    return Event(
        artist=artist,
        venue=normalize_venue_name(venue) if venue else "Venue TBA",
        date=event_date,
        time=time_str if time_str else None,
        source=f"Artifacts ({source_note})" if source_note else SOURCE_NAME,
    )


def _optimize_image(image_path: Path) -> Tuple[bytes, str]:
    """Optimize image for Claude vision API by resizing if too large."""
    file_size_mb = image_path.stat().st_size / (1024 * 1024)

    if file_size_mb < 3:
        with open(image_path, "rb") as f:
            return f.read(), _get_media_type(image_path.suffix)

    if not PILLOW_AVAILABLE:
        print(f"    Warning: {image_path.name} is {file_size_mb:.1f}MB but PIL not available")
        with open(image_path, "rb") as f:
            return f.read(), _get_media_type(image_path.suffix)

    try:
        img = Image.open(image_path)
        original_size = img.size

        if img.width > 1024 or img.height > 2048:
            ratio = min(1024 / img.width, 2048 / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            print(f"    Resized {image_path.name} from {original_size} to {new_size}")

        output = io.BytesIO()
        img.convert("RGB").save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue(), "image/jpeg"

    except Exception as e:
        print(f"    Could not optimize {image_path.name}: {str(e)[:50]}")
        with open(image_path, "rb") as f:
            return f.read(), _get_media_type(image_path.suffix)


def _get_media_type(suffix: str) -> str:
    """Get media type from file suffix."""
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
    }.get(suffix.lower(), "image/jpeg")
