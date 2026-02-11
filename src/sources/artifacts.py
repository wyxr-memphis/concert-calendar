"""Parse event artifacts (images, screenshots) using Claude vision API.

This module scans the artifacts/ folder for images (screenshots of Instagram posts,
venue websites, posters, etc.) and uses Claude's vision capabilities to extract
event information automatically.

Artifact structure:
artifacts/
  ├── bside/           # B-Side Memphis events (Instagram screenshots)
  ├── bar-dkdc/        # Bar DKDC events (Instagram screenshots)
  ├── histone/         # Hi Tone website screenshots
  ├── minglewood/      # Minglewood Hall website screenshots
  ├── lafayettes/      # Lafayette's website screenshots
  └── other/           # Other venues or sources
"""

from typing import Optional, List
import base64
import json
from pathlib import Path
from datetime import datetime
import anthropic

from ..models import Event, SourceResult
from ..config import START_DATE, END_DATE, normalize_venue_name

SOURCE_NAME = "Artifacts (Vision-Extracted)"
ARTIFACTS_DIR = Path(__file__).parent.parent.parent / "artifacts"


def fetch() -> SourceResult:
    """Scan artifacts folder and extract events from images using Claude vision."""
    result = SourceResult(source_name=SOURCE_NAME)

    if not ARTIFACTS_DIR.exists():
        result.error_message = "No artifacts/ folder found"
        return result

    # Find all image files
    image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    image_files = []

    for ext in image_extensions:
        image_files.extend(ARTIFACTS_DIR.glob(f"**/*{ext}"))
        image_files.extend(ARTIFACTS_DIR.glob(f"**/*{ext.upper()}"))

    if not image_files:
        result.error_message = "No image artifacts found"
        return result

    # Process each image
    for image_path in sorted(image_files):
        try:
            events = _extract_events_from_image(image_path)
            result.events_found += len(events)

            # Filter by date range
            for event in events:
                if START_DATE <= event.date <= END_DATE:
                    result.events.append(event)

        except Exception as e:
            # Continue on error, log it
            print(f"  Error processing {image_path.name}: {str(e)[:80]}")
            continue

    return result


def _extract_events_from_image(image_path: Path) -> List[Event]:
    """Use Claude vision to extract events from an image."""

    # Read and encode image
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    # Determine image type
    suffix = image_path.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(suffix, "image/jpeg")

    # Call Claude vision API
    client = anthropic.Anthropic()

    prompt = """Analyze this image and extract ANY music/concert events you can find.

For each event, extract:
- artist/act name
- venue (if visible)
- date (any format)
- time (if visible)
- source (what you see in image)

Return ONLY valid JSON array, no other text:
[
  {
    "artist": "Artist Name",
    "venue": "Venue Name",
    "date": "2/15/2026",
    "time": "9 PM",
    "source_note": "From Instagram post"
  }
]

If no events found, return: []

Be thorough - extract ALL events visible in the image."""

    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
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
                    {
                        "type": "text",
                        "text": prompt,
                    }
                ],
            }
        ],
    )

    # Parse response
    response_text = message.content[0].text.strip()

    # Extract JSON from response
    try:
        # Try to find JSON array in response
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            events_data = json.loads(json_str)
        else:
            events_data = json.loads(response_text)
    except json.JSONDecodeError:
        print(f"  Could not parse JSON from response: {response_text[:100]}")
        return []

    # Convert to Event objects
    events = []
    for item in events_data:
        try:
            event = _parse_extracted_event(item, image_path)
            if event:
                events.append(event)
        except Exception as e:
            continue

    return events


def _parse_extracted_event(data: dict, source_image: Path) -> Optional[Event]:
    """Convert extracted event data to Event object."""

    artist = data.get("artist", "").strip()
    venue = data.get("venue", "").strip()
    date_str = data.get("date", "").strip()
    time_str = data.get("time", "").strip()
    source_note = data.get("source_note", "").strip()

    if not artist or not date_str:
        return None

    # Parse date
    event_date = _parse_date_flexible(date_str)
    if not event_date:
        return None

    # Normalize venue
    if venue:
        venue = normalize_venue_name(venue)
    else:
        venue = "Venue TBA"

    source = SOURCE_NAME
    if source_note:
        source = f"Artifacts ({source_note})"

    return Event(
        artist=artist,
        venue=venue,
        date=event_date,
        time=time_str if time_str else None,
        source=source,
    )


def _parse_date_flexible(date_str: str) -> Optional[datetime.date]:
    """Parse date from various formats extracted by Claude."""
    import re

    date_formats = [
        "%m/%d/%Y", "%m/%d/%y",
        "%m-%d-%Y", "%m-%d-%y",
        "%Y-%m-%d",
        "%B %d, %Y", "%b %d, %Y",
        "%B %d", "%b %d",
        "%m/%d",
    ]

    date_str = date_str.strip()

    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.year < 2000:
                dt = dt.replace(year=START_DATE.year)
            return dt.date()
        except ValueError:
            continue

    # Try regex for "Feb 15", "February 15", etc.
    match = re.search(r'(\w{3,9})\s+(\d{1,2})(?:,?\s+(\d{4}))?', date_str)
    if match:
        month_str, day_str, year_str = match.groups()
        year = int(year_str) if year_str else START_DATE.year
        try:
            return datetime.strptime(f"{month_str} {day_str} {year}", "%b %d %Y").date()
        except ValueError:
            try:
                return datetime.strptime(f"{month_str} {day_str} {year}", "%B %d %Y").date()
            except ValueError:
                pass

    return None
