"""Generate the static HTML page for Memphis concert calendar."""

from datetime import date, datetime
from typing import Dict, List
from collections import defaultdict
from zoneinfo import ZoneInfo
from .models import Event, SourceResult


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
        day_name = d.strftime("%A, %B %-d").upper()

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
    run_time_str = run_time_central.strftime("%B %-d, %Y at %-I:%M %p %Z")
    total_events = len(events)

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
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <meta name="description" content="What's happening in Memphis this week? Live music listings for the next 8 days. From WYXR 91.7 FM.">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="https://concert-calendar.wyxr.org/thisweek.html">
    <meta property="og:title" content="Memphis Live Music — Next 8 Days">
    <meta property="og:description" content="What's happening in Memphis this week? Live music listings for the next 8 days.">
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://concert-calendar.wyxr.org/thisweek.html">
    <meta property="og:site_name" content="WYXR 91.7 FM Concert Calendar">
    <meta property="og:image" content="https://concert-calendar.wyxr.org/wyxr-wtmm-header.png">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="Memphis Live Music — Next 8 Days">
    <meta name="twitter:description" content="What's happening in Memphis this week? Live music listings for the next 8 days.">
    <meta name="twitter:image" content="https://concert-calendar.wyxr.org/wyxr-wtmm-header.png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Anybody:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --wyxr-yellow: #FFCF2D;
            --wyxr-black: #000000;
            --wyxr-white: #FFFFFF;
            --wyxr-charcoal: #1A1A1A;
            --wyxr-gray: #888888;
            --wyxr-dim: #666666;
            --wyxr-border: #2A2A2A;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            max-width: 700px;
            margin: 0 auto;
            padding: 20px 16px;
            background: var(--wyxr-black);
            color: var(--wyxr-white);
            line-height: 1.5;
        }}
        header {{
            margin-bottom: 24px;
        }}
        .header-banner {{
            width: 100%;
            height: auto;
            display: block;
            border-radius: 6px;
        }}
        .header-tagline {{
            font-family: 'Inter', sans-serif;
            font-size: 0.9em;
            color: #999;
            margin-top: 12px;
            line-height: 1.5;
        }}
        .header-meta {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid var(--wyxr-border);
        }}
        .meta-badge {{
            display: inline-block;
            font-family: 'Inter', sans-serif;
            font-size: 0.8em;
            font-weight: 600;
            background: var(--wyxr-yellow);
            color: var(--wyxr-black);
            padding: 3px 10px;
            border-radius: 3px;
            letter-spacing: 0.02em;
        }}
        .updated {{
            font-size: 0.8em;
            color: var(--wyxr-gray);
        }}
        .day-section {{
            margin-bottom: 28px;
        }}
        h2 {{
            font-family: 'Anybody', sans-serif;
            font-size: 1em;
            font-weight: 800;
            letter-spacing: 0.08em;
            color: var(--wyxr-yellow);
            border-left: 4px solid var(--wyxr-yellow);
            border-bottom: none;
            padding-left: 10px;
            padding-bottom: 0;
            margin-bottom: 8px;
        }}
        ul {{
            list-style: none;
            padding: 0;
        }}
        li {{
            padding: 5px 0;
            font-size: 0.95em;
            border-bottom: 1px solid var(--wyxr-border);
        }}
        li:last-child {{
            border-bottom: none;
        }}
        li.featured, li.event--featured {{
            border-left: 3px solid var(--wyxr-yellow);
            padding-left: 8px;
            margin-left: -3px;
        }}
        .featured-badge {{
            display: inline-block;
            background: var(--wyxr-yellow);
            color: var(--wyxr-black);
            font-family: 'Anybody', sans-serif;
            font-size: 0.6em;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 3px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            vertical-align: middle;
            margin-right: 4px;
        }}
        li a {{
            color: inherit;
            text-decoration: none;
        }}
        li a:hover {{
            color: var(--wyxr-yellow);
        }}
        .artist {{
            font-weight: 600;
            text-transform: uppercase;
        }}
        .venue {{
            color: #aaa;
        }}
        .time {{
            color: var(--wyxr-gray);
            font-size: 0.9em;
        }}
        .venue-group {{
            padding: 5px 0;
        }}
        .venue-artists {{
            list-style: none;
            padding: 0;
        }}
        .venue-artists li {{
            padding: 2px 0;
            font-size: 0.95em;
            border-bottom: none;
        }}
        .venue-footer {{
            font-size: 0.85em;
            margin-top: 2px;
            padding-left: 0;
        }}
        .no-events {{
            color: var(--wyxr-dim);
            font-style: italic;
            padding: 20px 0;
        }}
        footer {{
            margin-top: 40px;
            padding-top: 16px;
            border-top: 1px solid var(--wyxr-border);
            font-size: 0.8em;
            color: #555;
            text-align: center;
        }}
        footer a {{ color: var(--wyxr-dim); }}
        footer a:hover {{ color: var(--wyxr-yellow); }}
    </style>
</head>
<body>
    <header>
        <picture>
            <source srcset="/wyxr-wtmm-header.webp" type="image/webp">
            <img src="/wyxr-wtmm-header.png" alt="WYXR 91.7 FM &amp; Where's the Music Memphis — Concert Calendar" class="header-banner" width="1200" height="280">
        </picture>
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
        Compiled for WYXR 91.7 FM &middot; Community Radio for Memphis<br>
        Last built {run_time_str}<br>
        <a href="/">Full Calendar</a> &middot; <a href="/admin/">Admin</a>
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
