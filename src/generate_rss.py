"""Generate RSS 2.0 feed for Memphis Concert Calendar events."""

import html as html_module
from datetime import date, datetime
from email.utils import format_datetime
from typing import List
from zoneinfo import ZoneInfo

# Custom namespace for WYXR-specific item metadata. Consumers that want the
# badges as data (rather than parsing them out of <title>/<description>) read
# <wyxr:pick>, <wyxr:presents> and <wyxr:badge>.
WYXR_NS = "https://concert-calendar.wyxr.org/ns/rss/1.0"

BADGE_PICK = "WYXR Pick"
BADGE_PRESENTS = "WYXR Presents"


def generate_rss(events: List[dict], build_date: datetime, sponsors: List[dict] = None) -> str:
    """Generate an RSS 2.0 XML feed from event dicts.

    Events should be dicts with all DB fields (title, venue, date,
    start_time, doors_time, ticket_url, ticket_price, image_url,
    description, genre, is_featured, is_wyxr_presents, etc.).

    Sponsors (optional) are promotional callouts inserted as RSS items
    with a Sponsored category and an enclosure for the image.

    WYXR Pick / WYXR Presents are emitted as machine-readable flags on each
    item (<category>, plus <wyxr:pick>/<wyxr:presents>/<wyxr:badge>) in
    addition to the human-readable text already baked into the title and
    description.
    """
    items_xml = []
    for event in events:
        items_xml.append(_render_item(event))

    for sponsor in (sponsors or []):
        items_xml.append(_render_sponsor_item(sponsor))

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"'
        f' xmlns:wyxr="{WYXR_NS}">\n'
        "    <channel>\n"
        "        <title>WYXR Memphis Concert Calendar</title>\n"
        "        <link>https://concert-calendar.wyxr.org</link>\n"
        "        <description>Live music events in Memphis, TN — curated by WYXR 91.7 FM</description>\n"
        "        <language>en-US</language>\n"
        f"        <lastBuildDate>{format_datetime(build_date)}</lastBuildDate>\n"
        "        <generator>WYXR Concert Calendar</generator>\n"
        "        <docs>https://concert-calendar.wyxr.org</docs>\n"
        f'{"".join(items_xml)}'
        "    </channel>\n"
        "</rss>"
    )


def _render_item(event: dict) -> str:
    """Render a single event as an RSS <item>."""
    title = event.get("title", "")
    venue = event.get("venue", "")
    event_date = str(event.get("date", ""))

    item_title = f"{title} \u2014 {venue}" if venue else title
    link = event.get("ticket_url") or "https://concert-calendar.wyxr.org"

    is_presents = bool(event.get("is_wyxr_presents"))
    is_pick = bool(event.get("is_featured"))

    # Description — plain text summary
    desc_parts = []
    try:
        d = date.fromisoformat(event_date)
        desc_parts.append(d.strftime("%A, %B %-d, %Y"))
    except (ValueError, TypeError):
        desc_parts.append(event_date)
    if venue:
        desc_parts.append(venue)
    if event.get("start_time"):
        desc_parts.append(event["start_time"])
    if event.get("ticket_price"):
        desc_parts.append(event["ticket_price"])
    if is_presents:
        desc_parts.append(BADGE_PRESENTS)
    elif is_pick:
        desc_parts.append(BADGE_PICK)

    description = " | ".join(desc_parts)

    # content:encoded — rich HTML inside CDATA
    html_parts = []
    if is_presents:
        html_parts.append(
            f'<p><strong style="color: #f5a623;">\U0001f4fb {BADGE_PRESENTS}</strong></p>'
        )
    elif is_pick:
        html_parts.append(
            f'<p><strong style="color: #f5a623;">\u2b50 {BADGE_PICK}</strong></p>'
        )

    html_parts.append(f"<h3>{_esc(title)}</h3>")
    html_parts.append(f"<p><strong>{_esc(venue)}</strong></p>")

    try:
        d = date.fromisoformat(event_date)
        html_parts.append(f"<p>{d.strftime('%A, %B %-d, %Y')}</p>")
    except (ValueError, TypeError):
        pass

    details = []
    if event.get("start_time"):
        details.append(f"Time: {_esc(event['start_time'])}")
    if event.get("doors_time"):
        details.append(f"Doors: {_esc(event['doors_time'])}")
    if event.get("ticket_price"):
        details.append(f"Price: {_esc(event['ticket_price'])}")
    if event.get("genre"):
        details.append(f"Genre: {_esc(event['genre'])}")
    if details:
        html_parts.append("<p>" + "<br/>".join(details) + "</p>")

    if event.get("description"):
        html_parts.append(f"<p>{_esc(event['description'])}</p>")

    if event.get("ticket_url"):
        html_parts.append(
            f'<p><a href="{_esc(event["ticket_url"])}">Tickets / More Info</a></p>'
        )

    content_html = "".join(html_parts)

    # pubDate — event date at noon Central
    pub_date_str = ""
    try:
        d = date.fromisoformat(event_date)
        ct = ZoneInfo("America/Chicago")
        pub_dt = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=ct)
        pub_date_str = format_datetime(pub_dt)
    except (ValueError, TypeError):
        pass

    # Image as enclosure
    image_xml = ""
    if event.get("image_url"):
        image_xml = (
            f'\n            <enclosure url="{_esc(event["image_url"])}"'
            ' type="image/jpeg" length="0"/>'
        )

    event_id = event.get("id", title)

    # Machine-readable badge flags. <category> is standard RSS so generic
    # readers pick it up; the wyxr: elements are always present so a consumer
    # can branch on an explicit true/false instead of an absent tag.
    category_xml = ""
    if is_presents:
        category_xml += f"            <category>{BADGE_PRESENTS}</category>\n"
    if is_pick:
        category_xml += f"            <category>{BADGE_PICK}</category>\n"

    badge_xml = ""
    if is_presents:
        badge_xml = f"            <wyxr:badge>{BADGE_PRESENTS}</wyxr:badge>\n"
    elif is_pick:
        badge_xml = f"            <wyxr:badge>{BADGE_PICK}</wyxr:badge>\n"

    flags_xml = (
        f"{category_xml}"
        f"            <wyxr:presents>{_bool(is_presents)}</wyxr:presents>\n"
        f"            <wyxr:pick>{_bool(is_pick)}</wyxr:pick>\n"
        f"{badge_xml}"
    )

    return (
        "        <item>\n"
        f"            <title>{_esc(item_title)}</title>\n"
        f"            <link>{_esc(link)}</link>\n"
        f"            <description>{_esc(description)}</description>\n"
        f"{flags_xml}"
        f"            <content:encoded><![CDATA[{content_html}]]></content:encoded>"
        f"{image_xml}\n"
        f"            <pubDate>{pub_date_str}</pubDate>\n"
        f'            <guid isPermaLink="false">wyxr-concert-{_esc(str(event_id))}</guid>\n'
        "        </item>\n"
    )


def _render_sponsor_item(sponsor: dict) -> str:
    """Render a sponsor callout as an RSS <item>."""
    name = sponsor.get("name", "")
    image_url = sponsor.get("image_url", "")
    link_url = sponsor.get("link_url") or "https://concert-calendar.wyxr.org"
    start_date = str(sponsor.get("start_date", ""))

    pub_date_str = ""
    try:
        d = date.fromisoformat(start_date)
        ct = ZoneInfo("America/Chicago")
        pub_dt = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=ct)
        pub_date_str = format_datetime(pub_dt)
    except (ValueError, TypeError):
        pass

    enclosure_xml = ""
    if image_url:
        enclosure_xml = (
            f'\n            <enclosure url="{_esc(image_url)}"'
            ' type="image/jpeg" length="0"/>'
        )

    sponsor_id = sponsor.get("id", name)

    img_html = ""
    if image_url:
        img_html = f'<p><a href="{_esc(link_url)}"><img src="{_esc(image_url)}" style="max-width:100%;" /></a></p>'
    content_html = f"<p><strong>Sponsored</strong></p><p>{_esc(name)}</p>{img_html}"

    return (
        "        <item>\n"
        f"            <title>{_esc(name)}</title>\n"
        f"            <link>{_esc(link_url)}</link>\n"
        "            <category>Sponsored</category>\n"
        f"            <description>{_esc(name)}</description>\n"
        f"            <content:encoded><![CDATA[{content_html}]]></content:encoded>"
        f"{enclosure_xml}\n"
        f"            <pubDate>{pub_date_str}</pubDate>\n"
        f'            <guid isPermaLink="false">wyxr-sponsor-{_esc(str(sponsor_id))}</guid>\n'
        "        </item>\n"
    )


def _esc(text: str) -> str:
    """Escape text for XML."""
    return html_module.escape(str(text)) if text else ""


def _bool(value: bool) -> str:
    """Render a boolean as the XML text 'true' or 'false'."""
    return "true" if value else "false"
