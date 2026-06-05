"""Data models for concert calendar events."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


@dataclass
class Event:
    """A single music event."""
    artist: str
    venue: str
    date: date
    time: Optional[str] = None  # e.g. "Doors 7 / Show 8" or "9 PM"
    source: str = ""  # Where we found this event
    url: Optional[str] = None  # Link to event page/tickets
    is_featured: bool = False  # Highlighted on calendar
    event_id: Optional[str] = None  # Stable ID from PostgreSQL

    @property
    def sort_key(self):
        """Sort by date, featured first within each date, then venue, then artist."""
        return (self.date, not self.is_featured, self.venue.lower(), self.artist.lower())

    @property
    def display_line(self) -> str:
        """Format as 'ARTIST — VENUE' or 'ARTIST — VENUE (TIME)'."""
        line = f"{self.artist} — {self.venue}"
        if self.time:
            line += f" ({self.time})"
        return line

    def normalized_key(self) -> str:
        """Key for deduplication: lowercase artist+venue+date."""
        return f"{_normalize(self.artist)}|{_normalize(self.venue)}|{self.date.isoformat()}"


@dataclass
class SourceResult:
    """Result from a single source fetch."""
    source_name: str
    events: List[Event] = field(default_factory=list)
    success: bool = True
    error_message: Optional[str] = None
    events_found: int = 0
    events_filtered: int = 0  # Non-music events removed
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def status_emoji(self) -> str:
        if not self.success:
            return "❌"
        if self.events_found == 0:
            return "⚠️"
        return "✅"

    @property
    def status_line(self) -> str:
        if not self.success:
            return f"{self.status_emoji} {self.source_name}: ERROR — {self.error_message}"
        msg = f"{self.status_emoji} {self.source_name}: {self.events_found} event(s) found"
        if self.events_filtered > 0:
            msg += f" ({self.events_filtered} filtered as non-music)"
        return msg


def normalize_text(text: str) -> str:
    """Normalize text for comparison.

    Canonical normalization used by both deduplication and Event.normalized_key().
    Strips prefixes ("the"), common suffixes ("live", "concert", etc.),
    punctuation, and collapses whitespace.
    """
    text = text.lower().strip()

    # Remove "the " prefix
    text = re.sub(r'^the\s+', '', text)

    # Remove bracketed content like [small room-downstairs], [big room-upstairs]
    text = re.sub(r'\s*\[([^\]]+)\]\s*', ' ', text)
    text = re.sub(r'\s*\(([^\)]+)\)\s*', ' ', text)

    # Remove common suffixes that don't help distinguish events (more aggressive)
    # Match anywhere in string, not just at end
    text = re.sub(r'\s*(live!?|concert|tour|show|presents?|featuring|feat\.?|ft\.?|ep release party?|release party?)\s*', ' ', text, flags=re.IGNORECASE)

    # Replace punctuation with spaces (fixes "Land/Divided" vs "Land / Divided")
    text = re.sub(r'[^\w\s]', ' ', text)

    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# Keep private alias for backward compat with normalized_key()
_normalize = normalize_text


def compute_dedup_key(title: str, venue: str, date_str: str) -> str:
    """Canonical deduplication key: normalized artist|venue|date.

    The single source of truth for how an event's identity is computed, shared
    by the build (src/main.py), the backend API (backend/db.py), and the
    persisted ``events.dedup_key`` column.

    Venue names are canonicalized via config.py's alias map first, so e.g.
    "Hi-Tone Cafe", "Hi Tone", "Hi-Tone" all produce the same key. Callers
    that have already canonicalized the venue against the DB ``venues`` table
    pass the canonical name; this re-canonicalization is idempotent for it.
    """
    # Imported lazily to avoid any import-order coupling with config.
    from .config import normalize_venue_name
    canonical_venue = normalize_venue_name(venue or "")
    return f"{normalize_text(title or '')}|{normalize_text(canonical_venue)}|{date_str}"
