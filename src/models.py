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
    image_url: Optional[str] = None  # Promo artwork URL from the source, if any
    # Set only by Vision extraction: the acts on the bill and the show's own
    # name, before they were joined into `artist`. Not persisted — the Slack
    # pipeline uses them to warn about a per-act duplicate.
    lineup: Optional[List[str]] = None
    event_name: Optional[str] = None

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


def first_image_url(val) -> Optional[str]:
    """Return the first usable http(s) image URL from a varied source shape.

    Accepts a plain string, a list (of strings/dicts), or a Schema.org-style
    ``ImageObject`` dict ({'url': ...}). Anything that isn't ultimately an
    http(s) URL (e.g. relative paths or Wix ``wix:image://`` media refs) yields
    ``None`` so we never store an unusable value.
    """
    if isinstance(val, dict):
        val = val.get("url")
    if isinstance(val, list):
        for item in val:
            found = first_image_url(item)
            if found:
                return found
        return None
    if isinstance(val, str) and val.startswith(("http://", "https://")):
        return val
    return None


def best_ticketmaster_image(images) -> Optional[str]:
    """Pick the widest non-fallback image URL from a Ticketmaster images array.

    Each entry looks like ``{"url", "width", "height", "ratio", "fallback"}``.
    Prefers real (non-``fallback``) art; falls back to any image if all are
    flagged fallback.
    """
    if not isinstance(images, list):
        return None
    candidates = [i for i in images if isinstance(i, dict) and i.get("url")]
    if not candidates:
        return None
    real = [i for i in candidates if not i.get("fallback")] or candidates
    best = max(real, key=lambda i: i.get("width") or 0)
    return first_image_url(best.get("url"))


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

    # Remove common noise words that don't help distinguish events.
    #
    # These must only match WHOLE words. Without the boundary guards below the
    # pattern ate the insides of real names — "Tourist" became "ist",
    # "Showcase Showdown" became "case down", "Olive Branch Boys" became
    # "o branch boys" — and because this feeds compute_dedup_key() those
    # mangled strings became the persisted identity of the event.
    #
    # (?<!\w) / (?!\w) are used instead of \b because several alternatives end
    # in an optional "." — after "feat." a trailing \b would sit between two
    # non-word characters and fail to match.
    stripped = re.sub(
        r'(?<!\w)(live!?|concert|tour|show|presents?|featuring|feat\.?|ft\.?|ep release party?|release party?)(?!\w)',
        ' ',
        text,
        flags=re.IGNORECASE,
    )
    # Never let the noise strip consume the entire title — an event actually
    # called "Live" must not normalize to the empty string, which would collide
    # with every other title that did the same.
    if stripped.strip():
        text = stripped

    # Replace punctuation with spaces (fixes "Land/Divided" vs "Land / Divided")
    text = re.sub(r'[^\w\s]', ' ', text)

    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# Keep private alias for backward compat with normalized_key()
_normalize = normalize_text


def split_title_acts(title: str) -> List[str]:
    """Invert ``compose_show_title``: the acts named in a calendar title.

    ``"Name: A, B, C"`` → ``[A, B, C]``; ``"A w/ B, C"`` → ``[A, B, C]``;
    ``"A"`` → ``[A]``. The show name before the first ":" is dropped — it is
    what differs between a venue's schedule ("The Rescued Pack Benefit
    Concert: …") and the show's own poster ("Paws & Tunes: A Benefit for The
    Rescued Pack: …"), while the bill is what they share. Only the LAST ":"
    splits, so a show name containing a colon keeps its acts.
    """
    text = (title or "").strip()
    if not text:
        return []
    if ":" in text:
        text = text.rsplit(":", 1)[1]
    # Only the separators compose_show_title writes (plus "+", which flyers
    # use the same way). Not "&"/"and" — those sit inside band names
    # ("Dale Watson & His Lone Stars") far more often than between acts.
    parts = re.split(r'\s+w/\s+|\s*,\s*|\s+\+\s+', text)
    acts = []
    seen = set()
    for part in parts:
        part = part.strip()
        if len(part) < 2:
            continue
        if part.lower() in seen:
            continue
        seen.add(part.lower())
        acts.append(part)
    return acts


def clean_venue_text(venue: str) -> str:
    """Strip address debris Vision reads into a venue name.

    A flyer prints "38104 Bar DKDC" or "Bar DKDC 964 S Cooper St" and the
    model copies it, so the row lands under a venue string no alias knows and
    no fuzzy check reaches ("bar dkdc" vs "38104 bar dkdc" scores 0.73 against
    a 0.8 bar). Removes a leading 5-digit zip, a trailing zip, a trailing
    ", Memphis, TN 38104"-style tail and a trailing street address. Never
    empties a venue — if the strip would leave nothing, the original is
    returned.
    """
    text = (venue or "").strip()
    if not text:
        return text
    # Zip codes only (5 digits) — "1884 Lounge" is a real venue name.
    cleaned = re.sub(r'^\s*\d{5}(-\d{4})?\s+', '', text)                # "38104 Bar DKDC"
    cleaned = re.sub(r'\s*,\s*memphis\b.*$', '', cleaned, flags=re.I)  # ", Memphis, TN 38104"
    cleaned = re.sub(r'\s+\d{5}(-\d{4})?\s*$', '', cleaned)             # trailing zip
    cleaned = re.sub(r'\s*\d+\s+[NSEW]\.?\s+\w+\s+(st|ave|rd|blvd|dr|ln)\.?\s*$', '',
                     cleaned, flags=re.I)                               # "964 S Cooper St"
    cleaned = cleaned.strip(" ,-")
    return cleaned or text


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
