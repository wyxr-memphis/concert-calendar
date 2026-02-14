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
        event_sections = '<p class="no-events">No events found for the upcoming week.</p>'

    # Convert UTC timestamp to Central Time
    central_tz = ZoneInfo("America/Chicago")
    run_time_central = run_timestamp.replace(tzinfo=ZoneInfo("UTC")).astimezone(central_tz)
    run_time_str = run_time_central.strftime("%B %-d, %Y at %-I:%M %p %Z")
    total_events = len(events)

    # Source status summary
    ok_sources = [sr for sr in source_results if sr.success and len(sr.events) > 0]
    error_sources = [sr for sr in source_results if not sr.success]

    source_summary = f"{total_events} events from {len(ok_sources)} source{'s' if len(ok_sources) != 1 else ''}"
    if error_sources:
        source_summary += f" ({len(error_sources)} had errors)"

    # Build per-source table rows
    source_rows = ""
    for sr in source_results:
        if not sr.success:
            css_class = "src-error"
        elif len(sr.events) == 0:
            css_class = "src-warn"
        else:
            css_class = "src-ok"
        count = str(len(sr.events)) if sr.success else "\u2014"
        source_rows += (
            f'<tr class="{css_class}">'
            f'<td class="src-dot">&#x25CF;</td>'
            f'<td>{_esc(sr.source_name)}</td>'
            f'<td class="src-count">{count}</td>'
            f'</tr>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Memphis Live Music — Next 8 Days</title>
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
        footer {{
            margin-top: 40px;
            padding-top: 16px;
            border-top: 1px solid #eee;
            font-size: 0.8em;
            color: #aaa;
            text-align: center;
        }}
        .source-summary {{
            font-size: 1.05em;
            color: #666;
            margin-bottom: 8px;
        }}
        .source-status {{
            margin-bottom: 12px;
            text-align: left;
        }}
        .source-status summary {{
            cursor: pointer;
            color: #888;
            font-size: 0.95em;
        }}
        .source-status summary:hover {{
            color: #555;
        }}
        .source-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 8px;
        }}
        .source-table th {{
            text-align: left;
            font-weight: 600;
            padding: 4px 8px;
            border-bottom: 1px solid #ddd;
            color: #888;
            font-size: 0.85em;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }}
        .source-table td {{
            padding: 3px 8px;
            border-bottom: 1px solid #f0f0f0;
        }}
        .src-dot {{ width: 16px; font-size: 0.7em; }}
        .src-count {{ text-align: right; color: #888; }}
        .src-ok .src-dot {{ color: #2e7d32; }}
        .src-warn .src-dot {{ color: #f9a825; }}
        .src-error .src-dot {{ color: #c62828; }}
        @media (prefers-color-scheme: dark) {{
            body {{ background: #1a1a1a; color: #e0e0e0; }}
            h2 {{ color: #e0e0e0; border-bottom-color: #444; }}
            .venue {{ color: #aaa; }}
            .time {{ color: #777; }}
            .updated {{ color: #888; }}
            .summary {{ color: #999; }}
            li {{ border-bottom-color: #2a2a2a; }}
            header {{ border-bottom-color: #e0e0e0; }}
            footer {{ border-top-color: #333; color: #555; }}
            .source-summary {{ color: #888; }}
            .source-status summary {{ color: #666; }}
            .source-status summary:hover {{ color: #aaa; }}
            .source-table th {{ border-bottom-color: #333; color: #666; }}
            .source-table td {{ border-bottom-color: #2a2a2a; }}
            .src-ok .src-dot {{ color: #81c784; }}
            .src-warn .src-dot {{ color: #fdd835; }}
            .src-error .src-dot {{ color: #ef9a9a; }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>MEMPHIS LIVE MUSIC</h1>
        <div class="updated">Updated {run_time_str}</div>
        <div class="summary">{total_events} show{"s" if total_events != 1 else ""} over the next 8 days</div>
    </header>

    <main>
        {event_sections}
    </main>

    <footer>
        <div class="source-summary">{source_summary}</div>
        <details class="source-status">
            <summary>Source Details</summary>
            <table class="source-table">
                <thead><tr><th></th><th>Source</th><th class="src-count">Events</th></tr></thead>
                <tbody>
                    {source_rows}
                </tbody>
            </table>
        </details>
        Compiled for WYXR 91.7 FM &middot; Community Radio for Memphis<br>
        Last built {run_time_str}<br>
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
