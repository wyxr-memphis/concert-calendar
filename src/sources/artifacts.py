"""Parse event artifacts (images, screenshots) using Claude vision API.

This module scans the artifacts/ folder for images (screenshots of Instagram posts,
venue websites, posters, Bandsintown listings, etc.) and uses Claude's vision
capabilities to extract event information automatically.

Simple structure - just drop images in artifacts/:
artifacts/
  ├── bside-2026-02-10.png
  ├── bar-dkdc-instagram.jpg
  ├── histone-events.png
  ├── bandsintown-memphis.png
  └── any-concert-listing.jpg

Claude extracts artist, venue, date, time from each image.
"""

from typing import Optional, List, Tuple
import base64
import json
from pathlib import Path
from datetime import datetime
import anthropic

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

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

    # Find all image files in artifacts/ folder (top level only)
    image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    image_files = []

    for ext in image_extensions:
        image_files.extend(ARTIFACTS_DIR.glob(f"*{ext}"))
        image_files.extend(ARTIFACTS_DIR.glob(f"*{ext.upper()}"))

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


def _optimize_image(image_path: Path) -> Tuple[bytes, str]:
    """Optimize image for Claude vision API by resizing if too large.

    Returns: (image_bytes, media_type)
    """
    file_size_mb = image_path.stat().st_size / (1024 * 1024)

    # If image is small enough, use as-is
    if file_size_mb < 3:
        with open(image_path, "rb") as f:
            return f.read(), _get_media_type(image_path.suffix)

    # Need to optimize - try using PIL if available
    if not PILLOW_AVAILABLE:
        print(f"    Warning: Image {image_path.name} is {file_size_mb:.1f}MB but PIL not available. Trying anyway...")
        with open(image_path, "rb") as f:
            return f.read(), _get_media_type(image_path.suffix)

    try:
        # Open and check dimensions
        img = Image.open(image_path)
        original_size = img.size

        # Resize if width > 1024px or height > 2048px
        if img.width > 1024 or img.height > 2048:
            # Calculate new size maintaining aspect ratio
            ratio = min(1024 / img.width, 2048 / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            print(f"    Resized {image_path.name} from {original_size} to {new_size}")

        # Save as JPEG with quality reduction to reduce file size
        import io
        output = io.BytesIO()
        img.convert("RGB").save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue(), "image/jpeg"

    except Exception as e:
        print(f"    Could not optimize {image_path.name}: {str(e)[:50]}. Using original...")
        with open(image_path, "rb") as f:
            return f.read(), _get_media_type(image_path.suffix)


def _get_media_type(suffix: str) -> str:
    """Get media type from file suffix."""
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return media_type_map.get(suffix.lower(), "image/jpeg")


def _extract_events_from_image(image_path: Path) -> List[Event]:
    """Use Claude vision to extract events from an image."""

    # Optimize image if needed (resize/compress large images)
    image_bytes, media_type = _optimize_image(image_path)
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    # Call Claude vision API
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

    # Extract JSON from response (handle markdown code fences and plain JSON)
    try:
        # Find JSON array start and end
        start = response_text.find("[")
        end = response_text.rfind("]") + 1

        if start >= 0 and end > start:
            json_str = response_text[start:end]
            events_data = json.loads(json_str)
        else:
            # Try parsing as-is in case it's not wrapped
            events_data = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"  Could not parse JSON from response: {response_text[:100]}")
        print(f"  Error: {str(e)[:80]}")
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
        "%m.%d.%Y", "%m.%d.%y", "%m.%d",  # Period-separated (e.g., 2.13)
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
