"""Generate ``docs/sitemap.xml`` and ``docs/robots.txt``.

The homepage is client-rendered — a crawler that does not execute JavaScript
sees an empty shell — so the sitemap is how event pages get discovered at all.
The per-event URLs it lists (``/e/<id>``) are server-rendered by Flask and
proxied through Vercel (see the ``rewrites`` block in ``vercel.json``), so they
are real crawlable pages with Event structured data on them.

Only the static pages and events inside the feed window are listed. Past events
are deliberately omitted: they are still reachable, but a sitemap advertising
thousands of expired shows spends crawl budget on pages nobody wants.
"""

from datetime import date, datetime
from typing import List, Optional
from xml.sax.saxutils import escape as _xml_escape

SITE_BASE = "https://concert-calendar.wyxr.org"

# Static pages, with the same URL shape as each page's own rel=canonical — a
# sitemap that disagrees with the canonical tag is a mixed signal.
STATIC_PAGES = [
    ("/", "daily", "1.0"),
    ("/thisweek.html", "daily", "0.8"),
    ("/submit.html", "monthly", "0.3"),
]

ROBOTS_TXT = f"""# WYXR 91.7 FM — Memphis Concert Calendar
User-agent: *
Allow: /

# The admin UI is behind a login; there is nothing here for a crawler.
Disallow: /admin/
Disallow: /api/

Sitemap: {SITE_BASE}/sitemap.xml
"""


def generate_sitemap(events: List[dict], build_date: datetime) -> str:
    """Render a urlset containing the static pages plus one URL per event."""
    build_day = build_date.date().isoformat()

    entries = [
        _url_entry(f"{SITE_BASE}{path}", build_day, changefreq, priority)
        for path, changefreq, priority in STATIC_PAGES
    ]

    for event in events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        lastmod = _lastmod(event.get("updated_at")) or build_day
        entries.append(
            _url_entry(f"{SITE_BASE}/e/{event_id}", lastmod, "weekly", "0.6")
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{"".join(entries)}'
        "</urlset>\n"
    )


def _url_entry(loc: str, lastmod: str, changefreq: str, priority: str) -> str:
    return (
        "    <url>\n"
        f"        <loc>{_xml_escape(loc)}</loc>\n"
        f"        <lastmod>{lastmod}</lastmod>\n"
        f"        <changefreq>{changefreq}</changefreq>\n"
        f"        <priority>{priority}</priority>\n"
        "    </url>\n"
    )


def _lastmod(value) -> Optional[str]:
    """A W3C-datetime date for <lastmod>, or None if the value is unusable."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except (ValueError, TypeError):
        return None
