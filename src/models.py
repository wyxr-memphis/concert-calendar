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

    @property
    def sort_key(self):
        """Sort by date, then venue, then artist."""
        return (self.date, self.venue.lower(), self.artist.lower())

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


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, strip common prefixes, punctuation."""
    text = text.lower().strip()
    # Remove "the " prefix
    text = re.sub(r'^the\s+', '', text)
    # Remove punctuation and extra whitespace
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
