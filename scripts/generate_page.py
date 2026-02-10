"""
Generate the static HTML page for the concert calendar.
Clean, minimal, readable — designed for quick DJ reference on-air.
"""

from typing import Dict, List
from datetime import datetime
from scripts.sources import Event


def generate_html(
    events_by_date: Dict[str, List[Event]],
    source_status: dict,
    updated_at: datetime,
) -> str:
    """Generate the full HTML page."""

    # Build event sections
    event_sections = []
    total_events = 0

    for date_label, events in events_by_date.items():
        total_events += len(events)
        lines = []
        if events:
            for event in events:
                line = event.display_line()
                if event.url:
                    lines.append(f'<li><a href="{event.url}" target="_blank" rel="noopener">{_escape(line)}</a></li>')
                else:
                    lines.append(f"<li>{_escape(line)}</li>")
        else:
            lines.append('<li class="no-events">No events listed</li>')

        event_sections.append(f"""
        <div class="day-section">
            <h2>{_escape(date_label)}</h2>
            <ul>
                {"".join(lines)}
            </ul>
        </div>""")

    # Build source status section
    source_lines = []
    for name, info in source_status.items():
        status = info.get("status", "unknown")
        if status == "ok":
            count = info.get("count", 0)
            source_lines.append(f'<li class="source-ok">✅ {_escape(name)}: {count} events found</li>')
        elif status == "error":
            msg = info.get("message", "Unknown error")
            source_lines.append(f'<li class="source-error">❌ {_escape(name)}: {_escape(msg)}</li>')
        else:
            source_lines.append(f'<li class="source-warn">⚠️ {_escape(name)}: {status}</li>')

    updated_str = updated_at.strftime("%B %-d, %Y at %-I:%M %p %Z")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Memphis Live Music — WYXR 91.7 FM</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: "Courier New", Courier, monospace;
            background: #0a0a0a;
            color: #e8e8e8;
            max-width: 700px;
            margin: 0 auto;
            padding: 24px 20px;
            line-height: 1.5;
        }}

        header {{
            border-bottom: 2px solid #444;
            padding-bottom: 16px;
            margin-bottom: 32px;
        }}

        h1 {{
            font-size: 18px;
            font-weight: bold;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: #fff;
        }}

        .subtitle {{
            font-size: 12px;
            color: #888;
            margin-top: 4px;
        }}

        .event-count {{
            font-size: 13px;
            color: #aaa;
            margin-top: 8px;
        }}

        .day-section {{
            margin-bottom: 28px;
        }}

        h2 {{
            font-size: 14px;
            font-weight: bold;
            color: #f0c040;
            letter-spacing: 1px;
            border-bottom: 1px solid #333;
            padding-bottom: 6px;
            margin-bottom: 10px;
        }}

        ul {{
            list-style: none;
            padding: 0;
        }}

        li {{
            font-size: 15px;
            padding: 4px 0;
            color: #ddd;
        }}

        li a {{
            color: #ddd;
            text-decoration: none;
            border-bottom: 1px dotted #555;
        }}

        li a:hover {{
            color: #f0c040;
            border-bottom-color: #f0c040;
        }}

        .no-events {{
            color: #666;
            font-style: italic;
            font-size: 13px;
        }}

        .source-notes {{
            margin-top: 48px;
            border-top: 2px solid #333;
            padding-top: 16px;
        }}

        .source-notes h2 {{
            color: #888;
            font-size: 12px;
            letter-spacing: 1px;
            border-bottom: none;
            margin-bottom: 8px;
        }}

        .source-notes li {{
            font-size: 12px;
            color: #777;
            padding: 2px 0;
        }}

        .source-ok {{ color: #6a9; }}
        .source-error {{ color: #c66; }}
        .source-warn {{ color: #ca6; }}

        footer {{
            margin-top: 48px;
            padding-top: 16px;
            border-top: 1px solid #222;
            font-size: 11px;
            color: #555;
        }}

        footer a {{
            color: #666;
        }}

        @media (max-width: 480px) {{
            body {{
                padding: 16px 14px;
            }}
            li {{
                font-size: 14px;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>Memphis Live Music</h1>
        <div class="subtitle">WYXR 91.7 FM — Community Freeform Radio</div>
        <div class="event-count">{total_events} events over the next 7 days · Updated {updated_str}</div>
    </header>

    <main>
        {"".join(event_sections)}
    </main>

    <div class="source-notes">
        <h2>SOURCE NOTES</h2>
        <ul>
            {"".join(source_lines)}
        </ul>
    </div>

    <footer>
        <p>This page updates daily at 5 AM Central.</p>
        <p>Missing a show? Email <a href="mailto:info@wyxr.org">info@wyxr.org</a> or add it to the
        <a href="#" id="sheet-link">shared spreadsheet</a>.</p>
        <p>Powered by open data from Bandsintown, Ticketmaster, Eventbrite, DICE, Memphis Flyer, and venue calendars.</p>
    </footer>
</body>
</html>"""

    return html


def _escape(text: str) -> str:
    """Basic HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
