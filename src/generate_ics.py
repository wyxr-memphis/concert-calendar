"""Generate an iCalendar (RFC 5545) subscribe feed for the concert calendar.

Published as ``docs/calendar.ics`` and advertised as
``webcal://concert-calendar.wyxr.org/calendar.ics`` so anyone can subscribe to
the whole calendar in Apple Calendar, Google Calendar or Outlook and have it
refresh itself.

Two deliberate choices worth knowing before editing:

**Times are emitted as UTC instants, not floating local times with a VTIMEZONE.**
Shipping a correct VTIMEZONE block means hand-maintaining DST rules; converting
Central to UTC with ``zoneinfo`` gets the same result from the system tz
database and cannot drift. ``DTSTART:20260821T010000Z`` is unambiguous
everywhere.

**UIDs match the per-event ``.ics`` download** produced client-side by
``_buildCalendarData`` in ``docs/index.html``
(``wyxr-event-<id>@concert-calendar.wyxr.org``). A user who grabbed a single
show and later subscribes to the feed gets one entry, not two — calendar apps
key on UID.
"""

from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from .time_format import (
    DEFAULT_DURATION_HOURS,
    DEFAULT_START_HOUR,
    parse_start_time,
)

CENTRAL = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")

SITE_BASE = "https://concert-calendar.wyxr.org"
PRODID = "-//WYXR 91.7 FM//Memphis Concert Calendar//EN"

# Matches the client-side per-event export so a show downloaded from the modal
# and the same show from this feed are the same calendar entry.
UID_DOMAIN = "concert-calendar.wyxr.org"

BADGE_PICK = "WYXR Pick"
BADGE_PRESENTS = "WYXR Presents"

# How often subscribed clients should re-poll. The build runs twice daily.
REFRESH_DURATION = "PT12H"


def generate_ics(events: List[dict], build_date: datetime) -> str:
    """Render event dicts as a single VCALENDAR document.

    ``events`` are DB-shaped dicts (the same ones ``generate_rss`` takes).
    Events whose ``date`` will not parse are skipped rather than emitted with a
    broken DTSTART, which some clients reject for the whole file.
    """
    dtstamp = _utc_stamp(build_date)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Memphis Live Music — WYXR 91.7 FM",
        "X-WR-CALDESC:Live music in Memphis, TN — curated by WYXR 91.7 FM",
        "X-WR-TIMEZONE:America/Chicago",
        f"REFRESH-INTERVAL;VALUE=DURATION:{REFRESH_DURATION}",
        f"X-PUBLISHED-TTL:{REFRESH_DURATION}",
    ]

    for event in events:
        vevent = _render_vevent(event, dtstamp)
        if vevent:
            lines.extend(vevent)

    lines.append("END:VCALENDAR")

    # RFC 5545 requires CRLF line endings.
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _render_vevent(event: dict, dtstamp: str) -> Optional[List[str]]:
    """Render one event as the lines of a VEVENT, or None if it has no date."""
    event_date = _parse_date(event.get("date"))
    if event_date is None:
        return None

    hour, minute = parse_start_time(event.get("start_time"))
    start_local = datetime(
        event_date.year, event_date.month, event_date.day, hour, minute,
        tzinfo=CENTRAL,
    )
    end_local = start_local + timedelta(hours=DEFAULT_DURATION_HOURS)

    title = (event.get("title") or "").strip()
    venue = (event.get("venue") or "").strip()
    event_id = str(event.get("id") or "")

    # "Artist — Venue", matching the RSS item title. A subscribed month grid
    # shows only the summary, so the venue has to be in it to be useful.
    summary = f"{title} \u2014 {venue}" if title and venue else (title or venue)

    permalink = f"{SITE_BASE}/e/{event_id}" if event_id else SITE_BASE
    ticket_url = _http_url(event.get("ticket_url"))

    lines = [
        "BEGIN:VEVENT",
        f"UID:{_uid(event_id, summary, event_date)}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{_utc_stamp(start_local)}",
        f"DTEND:{_utc_stamp(end_local)}",
        f"SUMMARY:{_esc(summary)}",
    ]

    location = f"{venue}, Memphis, TN" if venue else "Memphis, TN"
    lines.append(f"LOCATION:{_esc(location)}")

    description = _build_description(event, permalink, ticket_url)
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")

    lines.append(f"URL:{ticket_url or permalink}")

    categories = []
    if event.get("is_wyxr_presents"):
        categories.append(BADGE_PRESENTS)
    if event.get("is_featured"):
        categories.append(BADGE_PICK)
    if event.get("genre"):
        categories.append(str(event["genre"]).strip())
    if categories:
        lines.append("CATEGORIES:" + ",".join(_esc(c) for c in categories))

    last_modified = _utc_stamp_maybe(event.get("updated_at"))
    if last_modified:
        lines.append(f"LAST-MODIFIED:{last_modified}")

    lines.append("STATUS:CONFIRMED")
    lines.append("TRANSP:TRANSPARENT")
    lines.append("END:VEVENT")
    return lines


def _build_description(event: dict, permalink: str, ticket_url: str) -> str:
    """Plain-text body: the details a calendar entry can't show structurally."""
    parts = []

    times = []
    if event.get("doors_time"):
        times.append(f"Doors {event['doors_time']}")
    if event.get("start_time"):
        times.append(f"Show {event['start_time']}")
    if times:
        parts.append(" / ".join(times))

    if event.get("ticket_price"):
        parts.append(str(event["ticket_price"]))
    if event.get("genre"):
        parts.append(str(event["genre"]))

    header = " \u00b7 ".join(parts)

    body = []
    if header:
        body.append(header)
    if event.get("description"):
        body.append(str(event["description"]).strip())
    if ticket_url:
        body.append(f"Tickets: {ticket_url}")
    body.append(permalink)

    return "\n".join(p for p in body if p)


def _uid(event_id: str, summary: str, event_date: date) -> str:
    """Stable UID, matching the client-side single-event export.

    Falls back to a summary+date key only for events with no database id, which
    in practice means a local run against events.json.
    """
    if event_id:
        return f"wyxr-event-{event_id}@{UID_DOMAIN}"
    slug = "".join(c if c.isalnum() else "-" for c in summary.lower())[:60].strip("-")
    return f"wyxr-{event_date.isoformat()}-{slug}@{UID_DOMAIN}"


def _parse_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _utc_stamp(value: datetime) -> str:
    """Format a datetime as an RFC 5545 UTC instant (YYYYMMDDTHHMMSSZ)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _utc_stamp_maybe(value) -> Optional[str]:
    if isinstance(value, datetime):
        return _utc_stamp(value)
    if not value:
        return None
    try:
        return _utc_stamp(datetime.fromisoformat(str(value)))
    except (ValueError, TypeError):
        return None


def _http_url(value) -> str:
    """Return the URL only if it is http(s); otherwise "".

    Ticket URLs come from scrapers and from OCR of uploaded flyers. A
    "javascript:" value in a calendar entry is inert in most clients, but some
    render descriptions as HTML — so the same rule the frontend applies to
    hrefs applies here.
    """
    raw = ("" if value is None else str(value)).strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return raw
    return ""


def _esc(text) -> str:
    """Escape a value for an iCalendar property (RFC 5545 §3.3.11).

    Backslash first — escaping it after the others would double-escape the
    backslashes they introduce. Control characters are dropped: they are not
    representable and a stray one invalidates the file for strict parsers.
    """
    s = "" if text is None else str(text)
    s = s.replace("\\", "\\\\")
    s = s.replace(";", "\\;").replace(",", "\\,")
    s = s.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return "".join(c for c in s if c == "\\" or ord(c) >= 0x20)


def _fold(line: str) -> str:
    """Fold a content line to 75 octets, per RFC 5545 §3.1.

    Folding counts *octets*, not characters, and a multi-byte character must
    not be split across the fold — an em dash cut in half is mojibake in every
    client. So the split point is found on the encoded bytes at a character
    boundary.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line

    chunks = []
    remaining = encoded
    limit = 75
    while len(remaining) > limit:
        cut = limit
        # Back off until `cut` lands on a UTF-8 character boundary (a byte that
        # is not a 10xxxxxx continuation byte).
        while cut > 0 and (remaining[cut] & 0xC0) == 0x80:
            cut -= 1
        if cut == 0:
            cut = limit
        chunks.append(remaining[:cut].decode("utf-8", errors="ignore"))
        remaining = remaining[cut:]
        # Continuation lines are prefixed with a single space, which counts
        # toward the 75.
        limit = 74
    chunks.append(remaining.decode("utf-8", errors="ignore"))

    return ("\r\n ".join(chunks))
