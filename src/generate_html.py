"""Generate the static HTML page for Memphis concert calendar."""

import json
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
        day_name = strftime_nopad(d, "%A, %B %-d").upper()

        # Group events by venue (case-insensitive, preserving order)
        venue_groups: Dict[str, List[Event]] = {}
        venue_order: List[str] = []
        for event in day_events:
            key = event.venue.strip().lower()
            if key not in venue_groups:
                venue_groups[key] = []
                venue_order.append(key)
            venue_groups[key].append(event)

        event_lines = ""
        for venue_key in venue_order:
            venue_events = venue_groups[venue_key]

            if len(venue_events) == 1:
                # Single event at this venue — render as before
                event = venue_events[0]
                line = f'<span class="artist">{_esc(event.artist)}</span> — '
                line += f'<span class="venue">{_esc(event.venue)}</span>'
                if event.time:
                    line += f' <span class="time">({_esc(event.time)})</span>'

                cls = ' class="featured event--featured"' if event.is_featured else ''
                badge = '<span class="featured-badge">WYXR Pick</span> ' if event.is_featured else ''
                if event.url:
                    event_lines += f'<li{cls}><a href="{_esc(event.url)}" target="_blank" rel="noopener">{badge}{line}</a></li>\n'
                else:
                    event_lines += f'<li{cls}>{badge}{line}</li>\n'
            else:
                # Multiple events at same venue — group them
                venue_name = venue_events[0].venue
                times = [e.time for e in venue_events]
                all_same_time = len(set(times)) == 1
                shared_time = times[0] if all_same_time else None

                artist_items = ""
                for event in venue_events:
                    badge = '<span class="featured-badge">WYXR Pick</span> ' if event.is_featured else ''
                    cls = ' class="featured event--featured"' if event.is_featured else ''
                    artist_text = f'{badge}<span class="artist">{_esc(event.artist)}</span>'
                    if not all_same_time and event.time:
                        artist_text += f' <span class="time">({_esc(event.time)})</span>'

                    if event.url:
                        artist_items += f'<li{cls}><a href="{_esc(event.url)}" target="_blank" rel="noopener">{artist_text}</a></li>\n'
                    else:
                        artist_items += f'<li{cls}>{artist_text}</li>\n'

                footer_line = f'<span class="venue">{_esc(venue_name)}</span>'
                if shared_time:
                    footer_line += f' <span class="time">({_esc(shared_time)})</span>'

                event_lines += f'<li class="venue-group"><ul class="venue-artists">\n{artist_items}</ul>\n<div class="venue-footer">{footer_line}</div></li>\n'

        event_sections += f"""
        <div class="day-section">
            <h2>{day_name}</h2>
            <ul>{event_lines}</ul>
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
        }}
        *, *::before, *::after {{ box-sizing: border-box; }}
        * {{ margin: 0; padding: 0; }}
        body {{
            font-family: var(--font-body);
            max-width: 720px;
            margin: 0 auto;
            padding: 16px 16px 56px;
            background: var(--ground);
            color: var(--text);
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }}
        ::selection {{ background: var(--lit); color: var(--on-lit); }}
        a {{ color: inherit; text-underline-offset: 0.18em; }}
        :focus-visible {{ outline: 3px solid var(--focus); outline-offset: 2px; }}

        header {{ margin-bottom: 28px; }}
        .masthead {{
            display: grid;
            grid-template-columns: clamp(84px, 24vw, 132px) minmax(0, 1fr);
            align-items: center;
            column-gap: 12px;
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
            font-size: clamp(2.5rem, 14.2vw, 4.75rem);
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
            border-top: 2px solid var(--line);
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

        .day-section {{ margin-bottom: 32px; }}
        h2 {{
            margin-bottom: 4px;
            padding-bottom: 6px;
            border-bottom: 2px solid var(--line);
            font-family: var(--font-display);
            font-stretch: 50%;
            font-size: 2.125rem;
            font-weight: 700;
            line-height: 1;
            letter-spacing: 0.02em;
            color: var(--accent);
        }}
        ul {{ list-style: none; }}
        li {{ padding: 10px 4px; border-bottom: 1px solid var(--rule); }}
        li:last-child {{ border-bottom: none; }}
        li.featured, li.event--featured {{
            margin: 6px 0;
            padding: 10px 12px;
            border-bottom: none;
            border-radius: 12px;
            background: var(--lit);
            color: var(--on-lit);
        }}
        .featured-badge {{
            display: block;
            margin-bottom: 2px;
            font-family: var(--font-head);
            font-stretch: var(--head-narrow);
            font-size: 0.6875rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        li a {{ display: block; color: inherit; text-decoration: none; }}
        li a:hover .artist {{ text-decoration: underline; }}
        .artist {{
            font-family: var(--font-head);
            font-stretch: var(--head-narrow);
            font-weight: 700;
            letter-spacing: 0.01em;
            text-transform: uppercase;
            overflow-wrap: anywhere;
        }}
        .venue {{ font-size: 0.875rem; font-weight: 500; color: var(--text-soft); }}
        .time {{ font-size: 0.875rem; font-weight: 600; white-space: nowrap; color: var(--accent-text); }}
        li.featured .time, li.event--featured .time {{ color: var(--on-lit); }}
        .venue-group {{ padding: 6px 4px 10px; }}
        .venue-artists li {{ padding: 4px 0; border-bottom: none; }}
        .venue-artists li.featured, .venue-artists li.event--featured {{ padding: 8px 12px; }}
        .venue-footer {{ margin-top: 2px; }}
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
        @media print {{
            body {{ background: #fff; }}
            li.featured, li.event--featured {{ border: 1.5px solid var(--text); background: none; }}
        }}
    </style>
</head>
<body>
    <h1 class="sr-only">Memphis Live Music — live shows in Memphis over the next 8 days, from WYXR 91.7 FM</h1>
    <header>
        <a class="masthead" href="/" aria-label="Memphis Concert Calendar: the full calendar">
            <img src="/brand/mascot.svg" alt="" width="524" height="600">
            <span>
                <img class="masthead-script" src="/brand/word-memphis.svg" alt="" width="3141" height="906">
                <span class="masthead-words">Concert Calendar</span>
            </span>
        </a>
        <p class="header-tagline">We live and breathe Memphis music &mdash; on air and in person. That&rsquo;s why WYXR teamed up with Where&rsquo;s the Music Memphis to bring you the Weekly Concert Calendar, your guide to what&rsquo;s happening every day.</p>
        <div class="header-meta">
            <span class="updated">Updated {run_time_str}</span>
            <span class="meta-badge">{total_events} show{"s" if total_events != 1 else ""} &middot; next 8 days</span>
        </div>
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
