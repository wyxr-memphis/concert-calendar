"""Server-rendered event permalink pages (``/e/<id>``).

Why this exists: ``docs/index.html`` is client-rendered, so a link to a single
show has no per-event metadata for Slack, iMessage, Facebook or a search
crawler to read — every share unfurls with the same generic site card, and no
event is individually indexable. These pages are rendered from the database on
request, so they are always current (an admin edit shows immediately, with no
build) and they carry real ``og:*`` tags plus ``MusicEvent`` structured data.

Vercel proxies ``concert-calendar.wyxr.org/e/<id>`` here (see ``rewrites`` in
``vercel.json``) so the shareable URL stays on the public domain.

**Everything interpolated here is untrusted.** Titles, venues and descriptions
come from venue scrapers, from Claude Vision OCR of uploaded flyers and from
the unauthenticated ``/submit`` form; image and ticket URLs come from the same
places. Text goes through ``esc()`` (which quotes too, so it is safe in
attributes), URLs additionally through ``safe_http_url()`` — escaping alone
does not stop a ``javascript:`` href. The JSON-LD block is serialized with
``json.dumps`` and then has ``<``/``>``/``&`` unicode-escaped, because a
``</script>`` inside any string value would otherwise close the block and turn
the rest into markup.
"""

import json
import re
from datetime import date, datetime, timedelta
from html import escape as _html_escape
from typing import Optional
from zoneinfo import ZoneInfo

from src.time_format import (
    DEFAULT_DURATION_HOURS,
    parse_start_time,
    strftime_nopad,
)

CENTRAL = ZoneInfo("America/Chicago")

DEFAULT_SITE_BASE = "https://concert-calendar.wyxr.org"
DEFAULT_OG_IMAGE = "/wyxr-wtmm-header.png"

BADGE_PICK = "WYXR Pick"
BADGE_PRESENTS = "WYXR Presents"

# Only a plain amount becomes structured-data price. Real values include
# "Free", "$15-25", "$20 ADV / $25 DOS" — inventing a single number from those
# would put a wrong price in a search result.
_SIMPLE_PRICE = re.compile(r"^\$?\s*(\d+(?:\.\d{1,2})?)$")


def esc(value) -> str:
    """HTML-escape for text *and* quoted attributes (quotes included)."""
    return _html_escape("" if value is None else str(value), quote=True)


def safe_http_url(value) -> str:
    """Return the URL only if it is http(s); otherwise "".

    Deliberately stricter than the frontend's ``safeUrl``: this page has no
    need for ``mailto:``/``tel:``, and every URL it renders (ticket link, image)
    should be absolute.
    """
    raw = ("" if value is None else str(value)).strip()
    if not raw:
        return ""
    # Control characters and whitespace can smuggle a scheme past a plain
    # prefix test ("java\tscript:").
    probe = re.sub(r"[\x00-\x20]", "", raw).lower()
    if probe.startswith("http://") or probe.startswith("https://"):
        return raw
    return ""


def absolute_image_url(value, site_base: str) -> str:
    """Absolutise an image URL for ``og:image``, which requires one.

    Three shapes exist in the database (see ``cldImg`` in ``docs/index.html``):
    Cloudinary URLs, legacy ``docs/event-images/`` paths still served by Vercel,
    and remote scraper URLs. Only the middle one is relative.
    """
    raw = ("" if value is None else str(value)).strip()
    if not raw:
        return ""
    if safe_http_url(raw):
        return raw
    if raw.startswith("//") or ":" in raw.split("/")[0]:
        # Protocol-relative, or some other scheme — not usable.
        return ""
    return f"{site_base}/{raw.lstrip('/')}"


def render_event_page(event: dict, site_base: str = DEFAULT_SITE_BASE) -> str:
    """Render the permalink page for one event row."""
    site_base = site_base.rstrip("/")

    event_id = str(event.get("id") or "")
    title = (event.get("title") or "Live Music").strip()
    venue = (event.get("venue") or "").strip()
    neighborhood = (event.get("neighborhood") or "").strip()
    description = (event.get("description") or "").strip()

    permalink = f"{site_base}/e/{event_id}"
    calendar_link = f"{site_base}/#event={event_id}"
    ticket_url = safe_http_url(event.get("ticket_url"))
    image_url = absolute_image_url(event.get("image_url"), site_base)
    og_image = image_url or f"{site_base}{DEFAULT_OG_IMAGE}"

    event_date = _parse_date(event.get("date"))
    date_long = strftime_nopad(event_date, "%A, %B %-d, %Y") if event_date else ""

    time_bits = []
    if event.get("doors_time"):
        time_bits.append(f"Doors {event['doors_time']}")
    if event.get("start_time"):
        time_bits.append(f"Show {event['start_time']}")
    time_line = " / ".join(time_bits)

    meta_bits = [b for b in (event.get("genre"), event.get("ticket_price")) if b]
    meta_line = " · ".join(str(b) for b in meta_bits)

    # Page title and description: what a search result and an unfurl show.
    headline = f"{title} — {venue}" if venue else title
    page_title = f"{headline} | Memphis Concert Calendar"
    summary_bits = [b for b in (date_long, venue, event.get("start_time")) if b]
    social_description = (
        " · ".join(str(b) for b in summary_bits)
        or "Live music in Memphis, TN — from WYXR 91.7 FM."
    )

    badges = ""
    if event.get("is_wyxr_presents"):
        badges += f'<span class="badge badge-presents">{esc(BADGE_PRESENTS)}</span>'
    if event.get("is_featured"):
        badges += f'<span class="badge badge-pick">{esc(BADGE_PICK)}</span>'

    image_block = ""
    if image_url:
        image_block = (
            f'<img class="event-img" src="{esc(image_url)}" '
            f'alt="{esc(title)}" loading="eager">'
        )

    detail_rows = ""
    if date_long:
        detail_rows += _row("Date", date_long)
    if time_line:
        detail_rows += _row("Time", time_line)
    if venue:
        venue_text = f"{venue} · {neighborhood}" if neighborhood else venue
        detail_rows += _row("Venue", venue_text)
    if meta_line:
        detail_rows += _row("Details", meta_line)

    description_block = (
        f'<p class="event-desc">{esc(description)}</p>' if description else ""
    )

    ticket_block = ""
    if ticket_url:
        ticket_block = (
            f'<a class="btn btn-primary" href="{esc(ticket_url)}" '
            'target="_blank" rel="noopener noreferrer">Buy Tickets &rarr;</a>'
        )

    jsonld = _event_jsonld(
        event, title=title, venue=venue, permalink=permalink,
        image_url=image_url, ticket_url=ticket_url, event_date=event_date,
        description=description,
    )

    return _PAGE_TEMPLATE.format(
        page_title=esc(page_title),
        social_title=esc(headline),
        social_description=esc(social_description),
        permalink=esc(permalink),
        og_image=esc(og_image),
        jsonld=jsonld,
        styles=_STYLES,
        badges=badges,
        image_block=image_block,
        headline=esc(title),
        detail_rows=detail_rows,
        description_block=description_block,
        ticket_block=ticket_block,
        calendar_link=esc(calendar_link),
        site_base=esc(site_base),
    )


def render_missing_page(
    site_base: str = DEFAULT_SITE_BASE,
    heading: str = "Event not found",
    message: str = "This show may have been removed or the link may be incomplete.",
) -> str:
    """The body for an id that is unknown, deleted or malformed.

    Also serves the transient database-unavailable case — Render Postgres
    connections time out occasionally — with different wording, so a reader is
    not told a show was deleted when the query simply failed.
    """
    site_base = site_base.rstrip("/")
    return _MISSING_TEMPLATE.format(
        styles=_STYLES,
        site_base=esc(site_base),
        heading=esc(heading),
        message=esc(message),
    )


# ---------------------------------------------------------------------------
# Structured data
# ---------------------------------------------------------------------------

def _event_jsonld(
    event: dict, *, title: str, venue: str, permalink: str, image_url: str,
    ticket_url: str, event_date: Optional[date], description: str,
) -> str:
    """A schema.org MusicEvent block, ready to drop inside a <script> tag."""
    data = {
        "@context": "https://schema.org",
        "@type": "MusicEvent",
        "name": title,
        "url": permalink,
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {
            "@type": "MusicVenue" if venue else "Place",
            "name": venue or "Memphis, TN",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Memphis",
                "addressRegion": "TN",
                "addressCountry": "US",
            },
        },
        "performer": {"@type": "MusicGroup", "name": title},
        "organizer": {
            "@type": "Organization",
            "name": "WYXR 91.7 FM",
            "url": "https://wyxr.org",
        },
    }

    if event_date:
        hour, minute = parse_start_time(event.get("start_time"))
        start = datetime(
            event_date.year, event_date.month, event_date.day, hour, minute,
            tzinfo=CENTRAL,
        )
        data["startDate"] = start.isoformat()
        data["endDate"] = (start + timedelta(hours=DEFAULT_DURATION_HOURS)).isoformat()

    if image_url:
        data["image"] = [image_url]
    if description:
        data["description"] = description

    if ticket_url or event.get("ticket_price"):
        offer = {"@type": "Offer", "availability": "https://schema.org/InStock"}
        if ticket_url:
            offer["url"] = ticket_url
        price = _structured_price(event.get("ticket_price"))
        if price is not None:
            offer["price"] = price
            offer["priceCurrency"] = "USD"
        data["offers"] = offer

    return _json_for_script(data)


def _structured_price(value) -> Optional[str]:
    """"$15" -> "15", "Free" -> "0". Anything ambiguous returns None."""
    raw = ("" if value is None else str(value)).strip()
    if not raw:
        return None
    if raw.lower() in {"free", "free!", "no cover", "free admission"}:
        return "0"
    m = _SIMPLE_PRICE.match(raw)
    return m.group(1) if m else None


def _json_for_script(data: dict) -> str:
    """Serialize for embedding in a <script> tag.

    ``json.dumps`` will happily emit a literal ``</script>`` from inside a
    string value, which ends the block early and hands the remainder to the
    HTML parser. Unicode-escaping the three characters that matter keeps the
    JSON valid and inert.
    """
    return (
        json.dumps(data, ensure_ascii=False, indent=None)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


# ---------------------------------------------------------------------------
# Helpers and templates
# ---------------------------------------------------------------------------

def _parse_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _row(label: str, value) -> str:
    return (
        '<div class="detail-row">'
        f'<span class="detail-label">{esc(label)}</span>'
        f'<span class="detail-value">{esc(value)}</span>'
        "</div>"
    )


# Palette matches docs/index.html (the slate palette adopted 2026-07-24).
_STYLES = """
        :root {
            --wyxr-yellow: #FFD64A;
            --wyxr-black: #2A2E35;
            --wyxr-white: #F6F8FB;
            --wyxr-charcoal: #353A44;
            --wyxr-gray: #AFB5C1;
            --wyxr-dim: #8B93A1;
            --wyxr-border: #464C58;
            --wyxr-presents: #5BBCE4;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            max-width: 640px;
            margin: 0 auto;
            padding: 24px 16px 48px;
            background: var(--wyxr-black);
            color: var(--wyxr-white);
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }
        a { color: var(--wyxr-yellow); }
        .topbar {
            display: flex; align-items: center; justify-content: space-between;
            gap: 12px; margin-bottom: 20px; padding-bottom: 14px;
            border-bottom: 1px solid var(--wyxr-border);
        }
        .topbar a { text-decoration: none; font-size: 0.85em; font-weight: 600; }
        .topbar .brand { color: var(--wyxr-gray); }
        .card {
            background: var(--wyxr-charcoal);
            border: 1px solid var(--wyxr-border);
            border-radius: 12px;
            overflow: hidden;
        }
        /* Flyers are often tall portraits. Capping the height keeps the
           show's details above the fold instead of pushing them a full screen
           down; width:auto + max-width means it scales rather than crops. */
        .event-img {
            display: block;
            width: auto;
            max-width: 100%;
            max-height: 60vh;
            height: auto;
            margin: 0 auto;
        }
        .card-body { padding: 20px; }
        .badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
        .badge {
            font-size: 0.7em; font-weight: 700; letter-spacing: 0.04em;
            text-transform: uppercase; padding: 3px 9px; border-radius: 3px;
        }
        .badge-pick { background: var(--wyxr-yellow); color: var(--wyxr-black); }
        .badge-presents { background: var(--wyxr-presents); color: var(--wyxr-black); }
        h1 {
            font-family: 'Anybody', 'Inter', sans-serif;
            font-size: 1.6em; font-weight: 800; line-height: 1.2;
            margin-bottom: 14px;
        }
        .detail-row {
            display: flex; gap: 12px; padding: 8px 0;
            border-top: 1px solid var(--wyxr-border); font-size: 0.95em;
        }
        .detail-label {
            flex: 0 0 76px; color: var(--wyxr-dim); font-size: 0.85em;
            text-transform: uppercase; letter-spacing: 0.04em; padding-top: 2px;
        }
        .detail-value { flex: 1; }
        .event-desc {
            margin-top: 16px; padding-top: 14px;
            border-top: 1px solid var(--wyxr-border);
            color: var(--wyxr-gray); font-size: 0.95em;
        }
        .actions { display: flex; flex-direction: column; gap: 10px; margin-top: 20px; }
        .btn {
            display: block; text-align: center; padding: 12px 16px;
            border-radius: 8px; text-decoration: none; font-weight: 700;
            font-size: 0.95em;
        }
        .btn-primary { background: var(--wyxr-yellow); color: var(--wyxr-black); }
        .btn-secondary {
            background: transparent; color: var(--wyxr-white);
            border: 1px solid var(--wyxr-border);
        }
        footer {
            margin-top: 28px; text-align: center; font-size: 0.8em;
            color: var(--wyxr-dim);
        }
        footer a { color: var(--wyxr-dim); }
        .missing { text-align: center; padding: 48px 0; }
        .missing h1 { margin-bottom: 12px; }
"""


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <meta name="description" content="{social_description}">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="{permalink}">
    <link rel="icon" type="image/svg+xml" href="{site_base}/favicon.svg">
    <meta property="og:title" content="{social_title}">
    <meta property="og:description" content="{social_description}">
    <meta property="og:type" content="article">
    <meta property="og:url" content="{permalink}">
    <meta property="og:site_name" content="WYXR 91.7 FM Concert Calendar">
    <meta property="og:image" content="{og_image}">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{social_title}">
    <meta name="twitter:description" content="{social_description}">
    <meta name="twitter:image" content="{og_image}">
    <link rel="alternate" type="application/rss+xml" title="WYXR Memphis Concert Calendar" href="{site_base}/feed.xml">
    <link rel="alternate" type="text/calendar" title="Memphis Live Music calendar feed" href="{site_base}/calendar.ics">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Anybody:wght@600;700;800&amp;family=Inter:wght@400;500;600&amp;display=swap" rel="stylesheet">
    <script type="application/ld+json">{jsonld}</script>
    <style>{styles}</style>
</head>
<body>
    <div class="topbar">
        <a class="brand" href="{site_base}/">&larr; Memphis Concert Calendar</a>
        <a href="{site_base}/">WYXR 91.7 FM</a>
    </div>

    <article class="card">
        {image_block}
        <div class="card-body">
            <div class="badges">{badges}</div>
            <h1>{headline}</h1>
            {detail_rows}
            {description_block}
            <div class="actions">
                {ticket_block}
                <a class="btn btn-secondary" href="{calendar_link}">See it on the calendar</a>
            </div>
        </div>
    </article>

    <footer>
        Compiled for WYXR 91.7 FM &middot; Community Radio for Memphis<br>
        <a href="{site_base}/">Full calendar</a> &middot;
        <a href="{site_base}/calendar.ics">Subscribe (iCal)</a> &middot;
        <a href="{site_base}/feed.xml">RSS</a>
    </footer>
</body>
</html>
"""


_MISSING_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{heading} | Memphis Concert Calendar</title>
    <meta name="robots" content="noindex, follow">
    <link rel="icon" type="image/svg+xml" href="{site_base}/favicon.svg">
    <style>{styles}</style>
</head>
<body>
    <div class="missing">
        <h1>{heading}</h1>
        <p>{message}</p>
        <div class="actions">
            <a class="btn btn-primary" href="{site_base}/">See what's on in Memphis</a>
        </div>
    </div>
</body>
</html>
"""
