"""Event deduplication and normalization.

Handles merging events from multiple sources and removing duplicates.
Uses string similarity rather than Claude API — keeps costs at $0.
"""

import re
from .models import Event


def deduplicate(events: list[Event]) -> list[Event]:
    """Remove duplicate events, keeping the one with the most detail.
    
    Strategy: Group by date + normalized venue, then fuzzy match artist names.
    When duplicates found, keep the version with more info (time, URL, etc.)
    """
    if not events:
        return []

    # Group by date + venue
    groups: dict[str, list[Event]] = {}
    for event in events:
        key = f"{event.date.isoformat()}|{_normalize(event.venue)}"
        groups.setdefault(key, []).append(event)

    deduped = []
    for group_key, group_events in groups.items():
        if len(group_events) == 1:
            deduped.append(group_events[0])
            continue

        # Within same date+venue, check for artist name matches
        seen_artists = []
        for event in group_events:
            is_dup = False
            for i, seen in enumerate(seen_artists):
                if _artists_match(event.artist, seen.artist):
                    # Keep the more detailed one
                    seen_artists[i] = _pick_best(seen, event)
                    is_dup = True
                    break
            if not is_dup:
                seen_artists.append(event)

        deduped.extend(seen_artists)

    # Sort by date, then venue, then artist
    deduped.sort(key=lambda e: e.sort_key)
    return deduped


def _artists_match(a: str, b: str) -> bool:
    """Check if two artist names are likely the same act."""
    na = _normalize(a)
    nb = _normalize(b)

    # Exact match after normalization
    if na == nb:
        return True

    # One contains the other (handles "Lucero" vs "Lucero with special guests")
    if na in nb or nb in na:
        return True

    # High overlap of words (handles word order differences)
    words_a = set(na.split())
    words_b = set(nb.split())
    if not words_a or not words_b:
        return False

    intersection = words_a & words_b
    union = words_a | words_b
    jaccard = len(intersection) / len(union)

    # If >60% word overlap, likely same event
    if jaccard > 0.6:
        return True

    return False


def _normalize(text: str) -> str:
    """Normalize text for comparison."""
    text = text.lower().strip()
    # Remove "the " prefix
    text = re.sub(r'^the\s+', '', text)
    # Remove common suffixes
    text = re.sub(r'\s*(live|concert|tour|show|presents?|featuring|feat\.?|ft\.?)\s*$', '', text)
    # Remove punctuation
    text = re.sub(r'[^\w\s]', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _pick_best(a: Event, b: Event) -> Event:
    """Pick the event with more detail."""
    score_a = _detail_score(a)
    score_b = _detail_score(b)
    return a if score_a >= score_b else b


def _detail_score(event: Event) -> int:
    """Score how much detail an event has."""
    score = 0
    if event.time:
        score += 2
    if event.url:
        score += 1
    if len(event.artist) > 20:
        score += 1  # Longer names often have more context
    # Prefer certain sources
    preferred = ["Ticketmaster", "Venue:"]
    if any(p in event.source for p in preferred):
        score += 1
    return score
