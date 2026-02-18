"""Events JSON source — reads from data/events.json.

This is the central event database. The daily build merges automated events
into this file, and the admin UI edits it directly via the GitHub API.
"""

import json
from datetime import date
from pathlib import Path
from typing import Optional

from ..models import Event, SourceResult
from ..config import START_DATE, END_DATE

SOURCE_NAME = "Events JSON"
EVENTS_JSON_PATH = Path(__file__).parent.parent.parent / "data" / "events.json"


def fetch() -> SourceResult:
    """Read active events from data/events.json within the date range."""
    result = SourceResult(source_name=SOURCE_NAME)

    if not EVENTS_JSON_PATH.exists():
        result.success = True
        result.error_message = "No events.json found"
        return result

    try:
        data = load_events_json()
        for entry in data.get("events", []):
            if not entry.get("is_active", True):
                continue
            event = _entry_to_event(entry)
            if event and START_DATE <= event.date <= END_DATE:
                result.events.append(event)
                result.events_found += 1

    except Exception as e:
        result.success = False
        result.error_message = f"Parse error: {str(e)[:100]}"

    return result


def load_events_json() -> dict:
    """Load and parse data/events.json."""
    with open(EVENTS_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_events_json(data: dict) -> None:
    """Write data/events.json."""
    EVENTS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _entry_to_event(entry: dict) -> Optional[Event]:
    """Convert a JSON entry to an Event dataclass."""
    try:
        event_date = date.fromisoformat(entry["date"])
    except (KeyError, ValueError):
        return None

    title = entry.get("title", "").strip()
    venue = entry.get("venue", "").strip()
    if not title or not venue:
        return None

    return Event(
        artist=title,
        venue=venue,
        date=event_date,
        time=entry.get("start_time"),
        source=entry.get("source", SOURCE_NAME),
        url=entry.get("ticket_url"),
        is_featured=entry.get("is_featured", False),
        event_id=entry.get("id"),
    )
