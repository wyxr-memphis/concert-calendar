"""Event deduplication and normalization.

Handles merging events from multiple sources and removing duplicates.
Uses string similarity rather than Claude API — keeps costs at $0.
"""

from typing import Dict, List
from .models import Event


def deduplicate(events: List[Event]) -> List[Event]:
    """Remove duplicate events, keeping the one with the most detail.
    
    Strategy: Group by date + normalized venue, then fuzzy match artist names.
    When duplicates found, keep the version with more info (time, URL, etc.)
    """
    if not events:
        return []

    # Group by date + venue
    groups: Dict[str, List[Event]] = {}
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

    # Empty strings should not match
    if not na or not nb:
        return False

    # Check if removing all spaces makes them match (handles "slamhound" vs "slam hound")
    na_nospace = na.replace(' ', '')
    nb_nospace = nb.replace(' ', '')
    if na_nospace == nb_nospace and len(na_nospace) >= 5:
        return True

    # One contains the other (handles "Lucero" vs "Lucero with special guests")
    # But require significant length to avoid false positives
    if len(na) >= 5 and len(nb) >= 5:
        if na in nb or nb in na:
            return True

    # High overlap of words (handles word order differences)
    words_a = set(na.split())
    words_b = set(nb.split())
    if not words_a or not words_b:
        return False

    # Remove very short words that don't help (single letters, "w", "at", etc)
    words_a = {w for w in words_a if len(w) > 2}
    words_b = {w for w in words_b if len(w) > 2}

    if not words_a or not words_b:
        # If only short words remain, check if the original normalized strings are very similar
        return na == nb

    intersection = words_a & words_b
    union = words_a | words_b
    jaccard = len(intersection) / len(union)

    # If >70% word overlap, likely same event (increased from 60% for stricter matching)
    if jaccard > 0.7:
        return True

    # Special case: if all words from the shorter name are in the longer name
    # (e.g., "Demola" should match "Demola Live")
    shorter = words_a if len(words_a) <= len(words_b) else words_b
    longer = words_b if len(words_a) <= len(words_b) else words_a
    if len(shorter) > 0 and shorter.issubset(longer):
        return True

    return False


def _normalize(text: str) -> str:
    """Normalize text for comparison.

    Uses the shared normalize_text from models to ensure consistent
    normalization across deduplication and Event.normalized_key().
    """
    from .models import normalize_text
    return normalize_text(text)


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
