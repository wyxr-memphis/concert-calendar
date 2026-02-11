"""Generate the static HTML page for Memphis concert calendar."""

from datetime import date, datetime
from typing import Dict, List
from collections import defaultdict
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
        
        event_lines = ""
        for event in day_events:
            line = f'<span class="artist">{_esc(event.artist)}</span> — '
            line += f'<span class="venue">{_esc(event.venue)}</span>'
            if event.time:
                line += f' <span class="time">({_esc(event.time)})</span>'
            
            if event.url:
                event_lines += f'<li><a href="{_esc(event.url)}" target="_blank" rel="noopener">{line}</a></li>\n'
            else:
                event_lines += f'<li>{line}</li>\n'

        event_sections += f"""
        <div class="day-section">
            <h2>{day_name}</h2>
            <ul>{event_lines}</ul>
        </div>
        """

    if not events:
        event_sections = '<p class="no-events">No events found for the upcoming week. Check SOURCE NOTES below for details.</p>'

    # Build source notes (sanitized for public display)
    source_lines = ""
    for sr in source_results:
        source_lines += f"<li>{_sanitize_source_line(sr)}</li>\n"

    run_time_str = run_timestamp.strftime("%B %-d, %Y at %-I:%M %p CT")
    total_events = len(events)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Memphis Live Music — Next 7 Days</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            max-width: 700px;
            margin: 0 auto;
            padding: 20px 16px;
            background: #fafafa;
            color: #1a1a1a;
            line-height: 1.5;
        }}
        header {{
            border-bottom: 3px solid #1a1a1a;
            padding-bottom: 12px;
            margin-bottom: 24px;
        }}
        h1 {{
            font-size: 1.4em;
            font-weight: 700;
            letter-spacing: 0.02em;
        }}
        .updated {{
            font-size: 0.85em;
            color: #666;
            margin-top: 4px;
        }}
        .summary {{
            font-size: 0.9em;
            color: #444;
        }}
        .day-section {{
            margin-bottom: 28px;
        }}
        h2 {{
            font-size: 0.95em;
            font-weight: 700;
            letter-spacing: 0.08em;
            color: #1a1a1a;
            border-bottom: 1px solid #ccc;
            padding-bottom: 4px;
            margin-bottom: 8px;
        }}
        ul {{
            list-style: none;
            padding: 0;
        }}
        li {{
            padding: 4px 0;
            font-size: 0.95em;
            border-bottom: 1px solid #eee;
        }}
        li:last-child {{
            border-bottom: none;
        }}
        li a {{
            color: inherit;
            text-decoration: none;
        }}
        li a:hover {{
            text-decoration: underline;
        }}
        .artist {{
            font-weight: 600;
        }}
        .venue {{
            color: #555;
        }}
        .time {{
            color: #888;
            font-size: 0.9em;
        }}
        .no-events {{
            color: #666;
            font-style: italic;
            padding: 20px 0;
        }}
        .source-notes {{
            margin-top: 40px;
            border-top: 2px solid #ddd;
            padding-top: 16px;
        }}
        .source-notes h2 {{
            font-size: 0.85em;
            color: #888;
            border-bottom: none;
            margin-bottom: 8px;
        }}
        .source-notes ul {{
            font-size: 0.82em;
            color: #888;
        }}
        .source-notes li {{
            border-bottom: none;
            padding: 2px 0;
        }}
        footer {{
            margin-top: 40px;
            padding-top: 16px;
            border-top: 1px solid #eee;
            font-size: 0.8em;
            color: #aaa;
            text-align: center;
        }}
        @media (prefers-color-scheme: dark) {{
            body {{ background: #1a1a1a; color: #e0e0e0; }}
            h2 {{ color: #e0e0e0; border-bottom-color: #444; }}
            .venue {{ color: #aaa; }}
            .time {{ color: #777; }}
            .updated {{ color: #888; }}
            .summary {{ color: #999; }}
            .source-notes {{ border-top-color: #333; }}
            .source-notes h2 {{ color: #666; }}
            .source-notes ul {{ color: #666; }}
            li {{ border-bottom-color: #2a2a2a; }}
            header {{ border-bottom-color: #e0e0e0; }}
            footer {{ border-top-color: #333; color: #555; }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>MEMPHIS LIVE MUSIC</h1>
        <div class="updated">Updated {run_time_str}</div>
        <div class="summary">{total_events} show{"s" if total_events != 1 else ""} over the next 7 days</div>
    </header>

    <main>
        {event_sections}
    </main>

    <div class="source-notes">
        <h2>SOURCE NOTES</h2>
        <ul>
            {source_lines}
        </ul>
    </div>

    <footer>
        Compiled for WYXR 91.7 FM &middot; Community Radio for Memphis<br>
        Data sourced from Ticketmaster, DICE, Memphis Flyer, venue websites, and manual entries.<br>
        <a href="/upload.html" style="color:inherit">Upload Artifact</a>
    </footer>
</body>
</html>"""


def _sanitize_source_line(sr: SourceResult) -> str:
    """Build a sanitized source status line for public HTML display.

    Hides internal URLs, full error details, and API specifics.
    """
    import re
    name = _esc(sr.source_name)
    if not sr.success:
        # Strip URLs and technical details from error messages
        error = sr.error_message or "unavailable"
        error = re.sub(r'https?://\S+', '[url]', error)
        error = re.sub(r'HTTPSConnectionPool.*', 'connection failed', error)
        error = error[:80]
        return f"{sr.status_emoji} {name}: unavailable"
    if sr.events_found == 0:
        return f"{sr.status_emoji} {name}: no events this week"
    msg = f"{sr.status_emoji} {name}: {sr.events_found} event(s)"
    return msg


def _esc(text: str) -> str:
    """HTML-escape text."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
