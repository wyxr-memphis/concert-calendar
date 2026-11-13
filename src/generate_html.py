"""Generate the static HTML page for Memphis concert calendar."""

import json
import re
from datetime import date, datetime, timedelta
from typing import Dict, List
from collections import defaultdict
from zoneinfo import ZoneInfo
from .models import Event, SourceResult
from .time_format import (
    DEFAULT_DURATION_HOURS,
    parse_start_time,
    strftime_nopad,
)

SITE_BASE = "https://concert-calendar.wyxr.org"
CENTRAL = ZoneInfo("America/Chicago")


def _events_jsonld(events: List[Event]) -> str:
    """schema.org ItemList of the week's events, ready for a <script> tag.

    This page is the *server-rendered* one, so unlike the interactive calendar
    (whose events arrive over the API after load) its structured data is visible
    to a crawler that does not run JavaScript. That makes this the page that
    actually gets Memphis shows into search results.

    ``json.dumps`` will happily emit a literal closing script tag from inside a
    string value, ending the block early and handing the rest to the HTML
    parser. Unicode-escaping the three characters that matter keeps the JSON
    valid and inert — titles here come from scrapers and from OCR of uploaded
    flyers.
    """
    items = []
    for i, event in enumerate(events):
        item = {
            "@type": "MusicEvent",
            "name": event.artist,
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "location": {
                "@type": "MusicVenue" if event.venue else "Place",
                "name": event.venue or "Memphis, TN",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Memphis",
                    "addressRegion": "TN",
                    "addressCountry": "US",
                },
            },
        }

        hour, minute = parse_start_time(event.time)
        start = datetime(
            event.date.year, event.date.month, event.date.day, hour, minute,
            tzinfo=CENTRAL,
        )
        item["startDate"] = start.isoformat()
        item["endDate"] = (start + timedelta(hours=DEFAULT_DURATION_HOURS)).isoformat()

        if event.event_id:
            item["url"] = f"{SITE_BASE}/e/{event.event_id}"
        elif event.url:
            item["url"] = event.url
        if event.image_url:
            item["image"] = [event.image_url]
        if event.url:
            item["offers"] = {
                "@type": "Offer",
                "url": event.url,
                "availability": "https://schema.org/InStock",
            }

        items.append({"@type": "ListItem", "position": i + 1, "item": item})

    payload = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "Live music in Memphis — next 8 days",
        "numberOfItems": len(items),
        "itemListElement": items,
    }
    return (
        json.dumps(payload, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def generate_html(
    events: List[Event],
    source_results: List[SourceResult],
    run_timestamp: datetime,
) -> str:
    """Generate a clean, minimal HTML page organized by date."""

    # Group events by date
    by_date: Dict[date, List[Event]] = defaultdict(list)
    for event in events:
        by_date[event.date].append(event)

    # Sort dates
    sorted_dates = sorted(by_date.keys())

    # Build event sections
    event_sections = ""
    for d in sorted_dates:
        day_events = by_date[d]
        weekday = strftime_nopad(d, "%A")
        month_day = strftime_nopad(d, "%B %-d")
        tally = f"{len(day_events)} show{'s' if len(day_events) != 1 else ''}"

        # WYXR picks first, each its own marigold block (a pick is never folded
        # into a venue group, or it would drag the group to the top of the day).
        # Everything else is grouped by venue, case-insensitively, in the order
        # Event.sort_key already gave us.
        picks = [e for e in day_events if e.is_featured]
        others = [e for e in day_events if not e.is_featured]

        venue_groups: Dict[str, List[Event]] = {}
        venue_order: List[str] = []
        for event in others:
            key = event.venue.strip().lower()
            if key not in venue_groups:
                venue_groups[key] = []
                venue_order.append(key)
            venue_groups[key].append(event)

        event_lines = ""
        for event in picks:
            event_lines += (
                '<li class="event event--featured">'
                '<span class="featured-badge">WYXR Pick</span>'
                f'{_row(event, _time_cell(event.time), show_venue=True)}</li>\n'
            )

        for venue_key in venue_order:
            venue_events = venue_groups[venue_key]

            if len(venue_events) == 1 or not venue_key:
                # One show at this venue (or no venue named): a plain row.
                for event in venue_events:
                    event_lines += (
                        f'<li class="event">{_row(event, _time_cell(event.time), show_venue=True)}</li>\n'
                    )
                continue

            # Several shows at one venue: name it once, above them. A time they
            # all share is stated once, in the venue's own time column.
            times = [e.time for e in venue_events]
            shared_time = times[0] if len(set(times)) == 1 else None
            head_time = _time_cell(shared_time) if shared_time else '<span class="row-time"></span>'

            artist_items = ""
            for event in venue_events:
                cell = '<span class="row-time"></span>' if shared_time else _time_cell(event.time)
                artist_items += f'<li class="event">{_row(event, cell, show_venue=False)}</li>\n'

            event_lines += (
                '<li class="venue-group">'
                f'<div class="venue-head">{head_time}<span class="venue">{_esc(venue_events[0].venue)}</span></div>'
                f'<ul class="venue-artists">\n{artist_items}</ul></li>\n'
            )

        event_sections += f"""
        <div class="day-section">
            <div class="day-head">
                <h2><span class="day-weekday">{_esc(weekday)}</span> <span class="day-date">{_esc(month_day)}</span></h2>
                <p class="day-count">{tally}</p>
            </div>
            <ul class="day-list">{event_lines}</ul>
        </div>
        """

    if not events:
        event_sections = '<p class="no-events">No events found for the upcoming week.</p>'

    # Convert UTC timestamp to Central Time
    central_tz = ZoneInfo("America/Chicago")
    run_time_central = run_timestamp.astimezone(central_tz)
    run_time_str = strftime_nopad(run_time_central, "%B %-d, %Y at %-I:%M %p %Z")
    total_events = len(events)
    events_jsonld = _events_jsonld(events)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <!-- Google tag (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-9866JXK4ND"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', 'G-9866JXK4ND');
    </script>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Memphis Live Music — Next 8 Days</title>
    <meta name="theme-color" content="#FCE2B6">
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <link rel="icon" type="image/png" sizes="32x32" href="/brand/favicon-32.png">
    <link rel="apple-touch-icon" href="/brand/apple-touch-icon.png">
    <meta name="description" content="What's happening in Memphis this week? Live music listings for the next 8 days. From WYXR 91.7 FM.">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="https://concert-calendar.wyxr.org/thisweek">
    <meta property="og:title" content="Memphis Live Music — Next 8 Days">
    <meta property="og:description" content="What's happening in Memphis this week? Live music listings for the next 8 days.">
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://concert-calendar.wyxr.org/thisweek">
    <meta property="og:site_name" content="WYXR 91.7 FM Concert Calendar">
    <meta property="og:image" content="https://concert-calendar.wyxr.org/brand/og-image.png">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="Memphis Live Music — Next 8 Days">
    <meta name="twitter:description" content="What's happening in Memphis this week? Live music listings for the next 8 days.">
    <meta name="twitter:image" content="https://concert-calendar.wyxr.org/brand/og-image.png">
    <link rel="alternate" type="application/rss+xml" title="WYXR Memphis Concert Calendar" href="/feed.xml">
    <link rel="alternate" type="application/rss+xml" title="WYXR Picks — Memphis Concert Calendar" href="/picks.xml">
    <link rel="alternate" type="text/calendar" title="Memphis Live Music calendar feed" href="/calendar.ics">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Anybody:wdth,wght@50..100,600..800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="preconnect" href="https://use.typekit.net" crossorigin>
    <link rel="stylesheet" href="https://use.typekit.net/sis1dug.css">
    <script type="application/ld+json">{events_jsonld}</script>
    <style>
        /* Same inks and roles as docs/index.html; see "Style framework" in
           dev/frontend.md. This page is a plain printed program: no JS, one
           column, the week read top to bottom. */
        :root {{
            color-scheme: light;
            --ink-cream: #FCE2B6;
            --ink-paper: #FFF8EA;
            --ink-white: #FFFFFF;
            --ink-red: #D53727;
            --ink-brick: #B02A1C;
            --ink-marigold: #FCB91A;
            --ink-oxblood: #3A1510;
            --ink-umber: #6B3A2E;

            --ground: var(--ink-cream);
            --surface: var(--ink-paper);
            --text: var(--ink-oxblood);
            --text-soft: var(--ink-umber);
            --accent: var(--ink-red);
            --accent-text: var(--ink-brick);
            --on-accent: var(--ink-white);
            --lit: var(--ink-marigold);
            --on-lit: var(--ink-oxblood);
            --line: var(--ink-red);
            --rule: rgb(213 55 39 / 0.28);
            --focus: var(--ink-oxblood);
            --font-display: "irregardless-variable", "Anybody", sans-serif;
            --font-head: "Anybody", "Inter", system-ui, sans-serif;
            --font-body: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
            --head-narrow: 82%;

            --s-1: 4px; --s-2: 8px; --s-3: 12px; --s-4: 16px;
            --s-5: 24px; --s-6: 32px; --s-7: 48px; --s-8: 64px;
            --r-s: 8px; --r-m: 12px;
            --keyline: 2px;
            --tap: 44px;
            --rail-w: 320px;
            --leaf-col: 120px;
            --time-col: 3.25rem;
        }}
        *, *::before, *::after {{ box-sizing: border-box; }}
        * {{ margin: 0; padding: 0; }}
        body {{
            font-family: var(--font-body);
            background: var(--ground);
            color: var(--text);
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }}
        .page {{ max-width: 720px; margin: 0 auto; padding: var(--s-4) var(--s-4) 56px; }}
        ::selection {{ background: var(--lit); color: var(--on-lit); }}
        a {{ color: inherit; text-underline-offset: 0.18em; }}
        :focus-visible {{ outline: 3px solid var(--focus); outline-offset: 2px; }}

        /* ---- Masthead: the flower and the lockup set in type on a phone,
           the whole logo in the left rail on a desktop ---- */
        header {{ margin-bottom: 28px; }}
        .masthead {{
            display: grid;
            grid-template-columns: clamp(84px, 24vw, 94px) minmax(0, 1fr);
            align-items: center;
            column-gap: 12px;
            max-width: 358px;
            color: var(--accent);
            text-decoration: none;
        }}
        .masthead img {{ display: block; width: 100%; height: auto; }}
        .masthead-script {{ width: 48%; min-width: 92px; margin: 0 0 6px 2px; transform: rotate(-3deg); transform-origin: left bottom; }}
        .masthead-words {{
            display: block;
            max-width: 100%;
            overflow: hidden;
            font-family: var(--font-display);
            font-stretch: 50%;
            font-weight: 800;
            font-size: clamp(2.5rem, 14.2vw, 3.45rem);
            line-height: 0.92;
            text-transform: uppercase;
            white-space: nowrap;
        }}
        .header-tagline {{ margin-top: 16px; font-size: 0.9375rem; color: var(--text-soft); }}
        .header-meta {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 14px;
            padding-top: 12px;
            border-top: var(--keyline) solid var(--line);
        }}
        .meta-badge {{
            display: inline-block;
            padding: 5px 12px;
            border-radius: 999px;
            background: var(--accent);
            color: var(--on-accent);
            font-family: var(--font-head);
            font-stretch: var(--head-narrow);
            font-size: 0.75rem;
            font-weight: 800;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .updated {{ font-size: 0.8125rem; color: var(--text-soft); }}
        .rail-link {{ display: none; }}

        /* ---- Days ---- */
        .day-section {{ margin-bottom: var(--s-6); }}
        .day-head {{
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: var(--s-3);
            padding-bottom: 6px;
            border-bottom: var(--keyline) solid var(--line);
        }}
        h2 {{
            font-family: var(--font-display);
            font-stretch: 50%;
            font-size: 2.125rem;
            font-weight: 700;
            line-height: 1;
            letter-spacing: 0.02em;
            text-transform: uppercase;
            color: var(--accent);
        }}
        .day-weekday::after {{ content: ","; }}
        .day-count {{
            font-size: 0.75rem;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
            color: var(--text-soft);
        }}
        ul {{ list-style: none; }}

        /* ---- Event rows: time column, then the act over its venue ---- */
        .event {{ border-bottom: 1px solid var(--rule); }}
        .day-list > .event:last-child, .day-list > .venue-group:last-child {{ border-bottom: 0; }}
        .row {{
            display: flex;
            align-items: flex-start;
            gap: var(--s-3);
            min-height: 56px;
            padding: 10px var(--s-2);
            color: inherit;
            text-decoration: none;
            border-radius: var(--r-s);
        }}
        a.row:hover {{ background: var(--surface); }}
        a.row:hover .artist {{ text-decoration: underline; }}
        a.row:focus-visible {{ outline-offset: -3px; }}
        .row-time {{
            flex: 0 0 var(--time-col);
            padding-top: 1px;
            font-size: 0.9375rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            line-height: 1.25;
            text-align: right;
            white-space: nowrap;
            color: var(--accent-text);
        }}
        .row-ampm {{
            margin-left: 1px;
            font-size: 0.6875rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}
        .row-time--words {{
            font-size: 0.6875rem;
            font-weight: 600;
            letter-spacing: 0.03em;
            line-height: 1.2;
            text-transform: uppercase;
            white-space: normal;
            overflow-wrap: anywhere;
        }}
        .row-text {{ flex: 1 1 auto; display: flex; flex-direction: column; gap: 2px; min-width: 0; }}
        .artist {{
            font-family: var(--font-head);
            font-stretch: var(--head-narrow);
            font-weight: 700;
            font-size: 1rem;
            line-height: 1.22;
            letter-spacing: 0.01em;
            text-transform: uppercase;
            overflow-wrap: anywhere;
        }}
        .venue {{ font-size: 0.8125rem; font-weight: 600; line-height: 1.35; color: var(--text-soft); }}

        /* Several acts at one venue: the venue is named once, above them, and a
           time they all share sits in its own time column. */
        .venue-group {{ border-bottom: 1px solid var(--rule); }}
        .venue-head {{ display: flex; align-items: baseline; gap: var(--s-3); padding: 10px var(--s-2) 0; }}
        .venue-head .venue {{ font-size: 0.875rem; font-weight: 700; color: var(--text); }}
        .venue-artists .event {{ border-bottom: 0; }}
        .venue-artists .row {{ min-height: var(--tap); padding-block: var(--s-2); }}

        /* WYXR Picks: a plain marigold block, in the one colour reserved for
           things that are lit. */
        .event--featured {{
            margin: 6px 0;
            padding-bottom: 2px;
            border-bottom: 0;
            border-radius: var(--r-m);
            background: var(--lit);
            color: var(--on-lit);
        }}
        .featured-badge {{
            display: block;
            padding: 10px var(--s-3) 0 calc(var(--s-3) + var(--time-col) + var(--s-3));
            font-family: var(--font-head);
            font-stretch: var(--head-narrow);
            font-size: 0.6875rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        .event--featured .row {{ min-height: 0; padding: 4px var(--s-3) 10px; }}
        .event--featured .row-time {{ color: var(--on-lit); }}
        .event--featured a.row:hover {{ background: rgb(255 255 255 / 0.4); }}
        .no-events {{ padding: 32px 0; color: var(--text-soft); }}

        footer {{ margin-top: 48px; font-size: 0.875rem; text-align: center; color: var(--text-soft); }}
        footer .signoff {{ display: block; width: min(100%, 300px); height: auto; margin: 0 auto 14px; }}
        footer a {{ color: var(--text); font-weight: 500; }}
        footer a:hover {{ color: var(--accent-text); }}
        .footer-feeds {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 4px 18px; margin-top: 10px; }}
        .footer-feeds a {{ display: inline-flex; align-items: center; min-height: 32px; }}
        .sr-only {{
            position: absolute;
            width: 1px; height: 1px;
            padding: 0; margin: -1px;
            overflow: hidden;
            clip: rect(0, 0, 0, 0);
            white-space: nowrap;
            border: 0;
        }}

        /* ---- Desktop: the rail takes the logo; the list keeps its measure and
           each day gets a column of its own for the date. Same breakpoint and
           widths as docs/index.html. ---- */
        @media (min-width: 1024px) {{
            :root {{ --time-col: 4rem; }}
            .page {{
                display: grid;
                grid-template-columns: var(--rail-w) minmax(0, 1fr);
                column-gap: clamp(32px, 4vw, 64px);
                align-items: start;
                max-width: 1280px;
                padding: var(--s-6) var(--s-6) var(--s-8);
            }}
            header {{
                position: sticky;
                top: var(--s-5);
                max-height: calc(100vh - var(--s-6));
                margin-bottom: 0;
                overflow-y: auto;
                scrollbar-width: thin;
            }}
            main {{ max-width: 880px; }}
            footer {{ grid-column: 1 / -1; }}

            .masthead {{ display: block; max-width: none; text-align: center; }}
            .masthead img {{ max-width: 300px; margin: 0 auto; }}
            .lockup {{ display: none; }}
            .header-meta {{ flex-direction: column; align-items: flex-start; gap: var(--s-3); }}
            .rail-link {{
                display: inline-flex;
                align-items: center;
                min-height: var(--tap);
                margin-top: var(--s-4);
                padding: 0 18px;
                border: var(--keyline) solid var(--line);
                border-radius: 999px;
                background: var(--surface);
                color: var(--accent-text);
                font-family: var(--font-head);
                font-stretch: var(--head-narrow);
                font-size: 0.875rem;
                font-weight: 700;
                letter-spacing: 0.04em;
                text-decoration: none;
                text-transform: uppercase;
            }}
            .rail-link:hover {{ background: var(--accent); color: var(--on-accent); }}

            .day-section {{
                display: grid;
                grid-template-columns: var(--leaf-col) minmax(0, 1fr);
                column-gap: var(--s-5);
                align-items: start;
                margin-bottom: var(--s-7);
            }}
            .day-head {{
                position: sticky;
                top: var(--s-5);
                display: block;
                padding: 4px 0 0;
                border-bottom: 0;
            }}
            .day-weekday, .day-date {{ display: block; }}
            .day-weekday::after {{ content: none; }}
            .day-weekday {{ font-size: 2.125rem; }}
            .day-date {{
                margin-top: var(--s-1);
                font-family: var(--font-head);
                font-stretch: var(--head-narrow);
                font-size: 1.0625rem;
                font-weight: 800;
                letter-spacing: 0.03em;
                color: var(--text);
            }}
            .day-count {{ margin-top: var(--s-1); font-size: 0.8125rem; }}
            .day-list {{ border-top: var(--keyline) solid var(--line); }}
            .artist {{ font-size: 1.0625rem; }}
            .venue {{ font-size: 0.875rem; }}
            .row-time {{ font-size: 1rem; }}
            .row-time--words {{ font-size: 0.6875rem; }}
            .row {{ padding-block: var(--s-3); }}
            .venue-artists .row {{ padding-block: var(--s-2); }}
            .event--featured .row {{ padding: 4px var(--s-3) var(--s-3); }}
        }}
        @media print {{
            body {{ background: #fff; }}
            header {{ position: static; }}
            .rail-link {{ display: none; }}
            .event--featured {{ border: 1.5px solid var(--text); background: none; }}
        }}
    </style>
</head>
<body>
    <h1 class="sr-only">Memphis Live Music — live shows in Memphis over the next 8 days, from WYXR 91.7 FM</h1>
    <div class="page">
    <header>
        <a class="masthead" href="/" aria-label="Memphis Concert Calendar: the full calendar">
            <picture class="masthead-art">
                <source media="(min-width: 1024px)" srcset="/brand/logo.svg" width="968" height="994">
                <img src="/brand/mascot.svg" alt="" width="524" height="600">
            </picture>
            <span class="lockup">
                <img class="masthead-script" src="/brand/word-memphis.svg" alt="" width="3141" height="906">
                <span class="masthead-words">Concert Calendar</span>
            </span>
        </a>
        <p class="header-tagline">We live and breathe Memphis music &mdash; on air and in person. That&rsquo;s why WYXR teamed up with Where&rsquo;s the Music Memphis to bring you the Weekly Concert Calendar, your guide to what&rsquo;s happening every day.</p>
        <div class="header-meta">
            <span class="updated">Updated {run_time_str}</span>
            <span class="meta-badge">{total_events} show{"s" if total_events != 1 else ""} &middot; next 8 days</span>
        </div>
        <a class="rail-link" href="/">Full calendar</a>
    </header>

    <main>
        {event_sections}
    </main>

    <footer>
        <img class="signoff" src="/brand/word-see-you.svg" alt="See you at the show" width="6559" height="970" loading="lazy">
        Compiled for WYXR 91.7 FM &middot; Community Radio for Memphis<br>
        Last built {run_time_str}
        <div class="footer-feeds">
            <a href="/">Full calendar</a>
            <a href="webcal://concert-calendar.wyxr.org/calendar.ics">Subscribe in your calendar</a>
            <a href="/calendar.ics">Download .ics</a>
            <a href="/picks.xml">WYXR Picks RSS</a>
            <a href="/admin/">Admin</a>
        </div>
    </footer>
    </div>
    <script defer src="/_vercel/insights/script.js"></script>
</body>
</html>"""


def _esc(text: str) -> str:
    """HTML-escape text."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_CLOCK_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?", re.IGNORECASE)


def _time_cell(raw) -> str:
    """A start time typeset for the tabular time column.

    "7:30 PM" becomes 7:30 with a small pm and ":00" is dropped, as on the home
    page (``timeCell`` in docs/index.html). Presentation only: anything that is
    not a plain clock time ("Doors 7, Show 8", "Late") is shown exactly as
    written, escaped. Turning a time into a value still happens in one place,
    ``time_format.parse_start_time``.
    """
    text = (raw or "").replace("\u202f", " ").replace("\u00a0", " ").strip()
    if not text:
        return '<span class="row-time"></span>'
    m = _CLOCK_RE.fullmatch(text)
    if not m:
        return f'<span class="row-time row-time--words">{_esc(text)}</span>'
    minutes = f":{m.group(2)}" if m.group(2) and m.group(2) != "00" else ""
    # m.group(1) and (2) are \d only, and (3) is a letter: nothing to escape.
    return (
        f'<span class="row-time">{m.group(1)}{minutes}'
        f'<span class="row-ampm">{m.group(3).lower()}m</span></span>'
    )


def _safe_href(url) -> str:
    """The URL if it is plain http(s), else "". Escaping does not stop a
    ``javascript:`` URL, and ticket links come from scrapers and flyer OCR."""
    text = (url or "").strip()
    return text if re.match(r"https?://", text, re.IGNORECASE) else ""


def _row(event: Event, time_html: str, show_venue: bool) -> str:
    """One event row: time column, then the act over its venue line."""
    venue = (
        f'<span class="venue">{_esc(event.venue)}</span>'
        if show_venue and event.venue.strip()
        else ""
    )
    inner = (
        f'{time_html}<span class="row-text">'
        f'<span class="artist">{_esc(event.artist)}</span>{venue}</span>'
    )
    href = _safe_href(event.url)
    if href:
        return f'<a class="row" href="{_esc(href)}" target="_blank" rel="noopener">{inner}</a>'
    return f'<div class="row">{inner}</div>'
