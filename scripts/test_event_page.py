#!/usr/bin/env python3
"""Regression tests for the event permalink pages (backend/event_page.py).

Offline — no database, no network. The route tests use Flask's test client with
``get_event_by_id`` monkeypatched, so nothing here touches Postgres.

What these protect: every string on this page comes from a venue scraper, from
Claude Vision OCR of an uploaded flyer, or from the unauthenticated /submit
form. The page is server-rendered on the *public* domain, so an unescaped title
is a stored XSS on concert-calendar.wyxr.org — a strictly worse position than
the client-rendered calendar, which at least never had a server-side sink.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.event_page import (  # noqa: E402
    absolute_image_url,
    render_event_page,
    render_missing_page,
    safe_http_url,
    _structured_price,
)

FAILURES = []
CHECKS = [0]


def check(label, actual, expected):
    CHECKS[0] += 1
    if actual != expected:
        FAILURES.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


def check_true(label, value):
    CHECKS[0] += 1
    if not value:
        FAILURES.append(f"{label}\n    expected truthy, got {value!r}")


BASE = "https://concert-calendar.wyxr.org"

GOOD_EVENT = {
    "id": "11111111-1111-1111-1111-111111111111",
    "title": "Lucero",
    "venue": "Minglewood Hall",
    "neighborhood": "Midtown",
    "date": "2026-11-05",
    "start_time": "8:00 PM",
    "doors_time": "7:00 PM",
    "ticket_price": "$25",
    "genre": "Rock",
    "description": "An evening with Lucero.",
    "ticket_url": "https://example.com/tix",
    "image_url": "https://res.cloudinary.com/wyxr/image/upload/v1/a.jpg",
    "is_featured": True,
    "is_wyxr_presents": False,
    "is_active": True,
}


def _jsonld(html):
    """Extract and parse the JSON-LD block, undoing the unicode escaping."""
    m = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    if not m:
        return None
    return json.loads(m.group(1))


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------

def test_url_safety():
    check("javascript: rejected", safe_http_url("javascript:alert(1)"), "")
    check("tab-smuggled scheme rejected", safe_http_url("java\tscript:alert(1)"), "")
    check("newline-smuggled scheme rejected", safe_http_url("java\nscript:alert(1)"), "")
    check("leading-space scheme rejected", safe_http_url("  javascript:alert(1)"), "")
    check("data: rejected", safe_http_url("data:text/html,<script>"), "")
    check("vbscript: rejected", safe_http_url("vbscript:msgbox"), "")
    check("protocol-relative rejected", safe_http_url("//evil.example"), "")
    check("relative rejected", safe_http_url("/event-images/a.jpg"), "")
    check("uppercase scheme kept", safe_http_url("HTTPS://a.example"),
          "HTTPS://a.example")
    check("https kept", safe_http_url(" https://a.example "), "https://a.example")


def test_absolute_image_url():
    # The three URL shapes that exist in the database.
    check("cloudinary passes through",
          absolute_image_url("https://res.cloudinary.com/wyxr/x.jpg", BASE),
          "https://res.cloudinary.com/wyxr/x.jpg")
    check("legacy relative path is absolutised",
          absolute_image_url("event-images/a.jpg", BASE),
          f"{BASE}/event-images/a.jpg")
    check("leading slash is not doubled",
          absolute_image_url("/event-images/a.jpg", BASE),
          f"{BASE}/event-images/a.jpg")
    check("empty stays empty", absolute_image_url("", BASE), "")
    check("None stays empty", absolute_image_url(None, BASE), "")
    # og:image must be a real URL — a javascript: or protocol-relative value is
    # not one, and must not be turned into one by prefixing.
    check("javascript: is not absolutised",
          absolute_image_url("javascript:alert(1)", BASE), "")
    check("protocol-relative is not absolutised",
          absolute_image_url("//evil.example/a.jpg", BASE), "")


def test_price_parsing():
    check("plain dollars", _structured_price("$25"), "25")
    check("bare number", _structured_price("18"), "18")
    check("cents", _structured_price("$12.50"), "12.50")
    check("free", _structured_price("Free"), "0")
    check("no cover", _structured_price("no cover"), "0")
    # Ambiguous values must not become a single wrong price in a search result.
    check("range omitted", _structured_price("$15-25"), None)
    check("adv/dos omitted", _structured_price("$20 ADV / $25 DOS"), None)
    check("donation omitted", _structured_price("$10 suggested donation"), None)
    check("empty omitted", _structured_price(""), None)
    check("None omitted", _structured_price(None), None)


# ---------------------------------------------------------------------------
# Rendering and escaping
# ---------------------------------------------------------------------------

def test_happy_path():
    html = render_event_page(GOOD_EVENT, BASE)

    check_true("has a doctype", html.startswith("<!DOCTYPE html>"))
    check_true("title carries artist and venue",
               "<title>Lucero — Minglewood Hall | Memphis Concert Calendar</title>" in html)
    check_true("canonical is the permalink",
               f'<link rel="canonical" href="{BASE}/e/{GOOD_EVENT["id"]}">' in html)
    check_true("og:title present", 'property="og:title"' in html)
    check_true("og:image is the event image",
               f'<meta property="og:image" content="{GOOD_EVENT["image_url"]}">' in html)
    check_true("twitter large card", 'content="summary_large_image"' in html)
    check_true("indexable", 'content="index, follow"' in html)
    check_true("links back to the calendar entry",
               f'href="{BASE}/#event={GOOD_EVENT["id"]}"' in html)
    check_true("ticket button rendered", "Buy Tickets" in html)
    check_true("advertises the ics feed", "/calendar.ics" in html)
    check_true("advertises the rss feed", "/feed.xml" in html)
    check_true("shows the badge", "WYXR Pick" in html)
    check_true("formats the date", "Thursday, November 5, 2026" in html)
    check_true("shows doors and show times", "Doors 7:00 PM / Show 8:00 PM" in html)


def test_jsonld():
    data = _jsonld(render_event_page(GOOD_EVENT, BASE))
    check_true("json-ld parses", data is not None)
    check("@type is MusicEvent", data["@type"], "MusicEvent")
    check("name", data["name"], "Lucero")
    check("url", data["url"], f"{BASE}/e/{GOOD_EVENT['id']}")
    # 8 PM on Nov 5 is CST (UTC-6) — the DST transition is Nov 1 in 2026.
    check("startDate carries the Central offset", data["startDate"],
          "2026-11-05T20:00:00-06:00")
    check("endDate is three hours later", data["endDate"],
          "2026-11-05T23:00:00-06:00")
    check("location type", data["location"]["@type"], "MusicVenue")
    check("location name", data["location"]["name"], "Minglewood Hall")
    check("city", data["location"]["address"]["addressLocality"], "Memphis")
    check("offer url", data["offers"]["url"], "https://example.com/tix")
    check("offer price", data["offers"]["price"], "25")
    check("offer currency", data["offers"]["priceCurrency"], "USD")


def test_jsonld_summer_offset():
    summer = dict(GOOD_EVENT, date="2026-07-15")
    data = _jsonld(render_event_page(summer, BASE))
    # CDT — a fixed offset here would put half the year in the wrong hour.
    check("summer startDate is UTC-5", data["startDate"], "2026-07-15T20:00:00-05:00")


def test_xss_payloads():
    """Every field an attacker or a bad OCR pass can influence."""
    payloads = {
        "title": '<script>alert(1)</script>',
        "venue": '"><img src=x onerror=alert(1)>',
        "neighborhood": "</style><script>alert(1)</script>",
        "description": "</script><script>alert(1)</script>",
        "genre": '" onmouseover="alert(1)',
        "ticket_price": "'\"><svg onload=alert(1)>",
    }
    event = dict(GOOD_EVENT, **payloads)
    html = render_event_page(event, BASE)

    # No executable markup may survive anywhere on the page.
    check_true("no raw <script>alert", "<script>alert(1)</script>" not in html)
    check_true("no raw <img onerror", "<img src=x onerror" not in html)
    check_true("no raw <svg onload", "<svg onload" not in html)
    # The venue payload tries to break out of a quoted attribute. Testing for
    # a bare '"><' would false-positive on legitimate empty elements
    # (class="badges"></div>), so assert on the payload itself.
    check_true("no unescaped attribute break", '"><img' not in html)
    check_true("payload is present but escaped",
               "&lt;script&gt;alert(1)&lt;/script&gt;" in html)

    # The only <script> tags on the page are the JSON-LD block we emit.
    script_opens = re.findall(r"<script[^>]*>", html)
    check("exactly one script tag", len(script_opens), 1)
    check_true("and it is the json-ld block",
               script_opens[0] == '<script type="application/ld+json">')

    # A "</script>" inside a JSON string value would close the block early;
    # unicode-escaping keeps the JSON parseable and inert.
    data = _jsonld(html)
    check_true("json-ld still parses with a </script> payload", data is not None)
    check("payload survives intact inside the json, as data",
          data["description"], payloads["description"])
    check_true("json block contains no literal '<'",
               "<" not in re.search(
                   r'<script type="application/ld\+json">(.*?)</script>',
                   html, re.S).group(1))


def test_dangerous_urls_in_page():
    event = dict(
        GOOD_EVENT,
        ticket_url="javascript:alert(1)",
        image_url="javascript:alert(1)",
    )
    html = render_event_page(event, BASE)
    check_true("javascript: never reaches the page", "javascript:" not in html)
    check_true("no ticket button without a safe url", "Buy Tickets" not in html)
    # og:image is required, so it falls back to the site banner.
    check_true("og:image falls back to the banner",
               f'content="{BASE}/wyxr-wtmm-header.png"' in html)


def test_sparse_event():
    """An event with only the fields the database guarantees."""
    html = render_event_page(
        {"id": "22222222-2222-2222-2222-222222222222", "title": "Open Mic",
         "date": "2026-11-06"}, BASE)
    check_true("renders", html.startswith("<!DOCTYPE html>"))
    check_true("title has no trailing dash separator",
               "<title>Open Mic | Memphis Concert Calendar</title>" in html)
    check_true("no ticket button", "Buy Tickets" not in html)
    data = _jsonld(html)
    check("location falls back to a Place", data["location"]["@type"], "Place")
    check_true("no offers block", "offers" not in data)

    # A missing/blank title must not render an empty heading.
    untitled = render_event_page({"id": "33333333-3333-3333-3333-333333333333",
                                  "date": "2026-11-07"}, BASE)
    check_true("blank title falls back", "Live Music" in untitled)


def test_missing_page():
    html = render_missing_page(BASE)
    check_true("says not found", "Event not found" in html)
    # A 404 shell must never be indexed, or it competes with real pages.
    check_true("noindex", 'content="noindex, follow"' in html)
    check_true("links home", f'href="{BASE}/"' in html)

    unavailable = render_missing_page(
        BASE, heading="Temporarily unavailable", message="Please try again.")
    check_true("db-failure wording differs", "Temporarily unavailable" in unavailable)
    check_true("and does not claim the show was deleted",
               "may have been removed" not in unavailable)


# ---------------------------------------------------------------------------
# Route behaviour
# ---------------------------------------------------------------------------

def test_route():
    os.environ.setdefault("ADMIN_PASSWORD", "test-only")
    os.environ.setdefault("ADMIN_SECRET_KEY", "test-only-key")

    import backend.app as app_module

    # Skip the before_request DB init — these tests never reach Postgres.
    app_module._db_ready = True
    client = app_module.app.test_client()
    original = app_module.get_event_by_id

    try:
        app_module.get_event_by_id = lambda _id: dict(GOOD_EVENT)
        r = client.get(f"/e/{GOOD_EVENT['id']}")
        check("active event returns 200", r.status_code, 200)
        check_true("content type is html",
                   r.headers["Content-Type"].startswith("text/html"))
        check_true("cached at the edge", "s-maxage" in r.headers["Cache-Control"])
        check_true("body is the event page", b"Minglewood Hall" in r.data)

        # A malformed id must be rejected before the query: passing a non-UUID
        # to a uuid column raises, and a raised error inside a cursor block
        # poisons the transaction for the next statement.
        def _should_not_run(_id):
            raise AssertionError("query ran for a malformed id")

        app_module.get_event_by_id = _should_not_run
        r = client.get("/e/not-a-uuid")
        check("malformed id returns 404", r.status_code, 404)
        check_true("404 is not indexed", r.headers.get("X-Robots-Tag") == "noindex")
        check_true("404 is not cached", r.headers["Cache-Control"] == "no-store")

        app_module.get_event_by_id = lambda _id: None
        r = client.get("/e/44444444-4444-4444-4444-444444444444")
        check("unknown id returns 404", r.status_code, 404)

        # Soft-deleted events must not stay live on a shared link.
        app_module.get_event_by_id = lambda _id: dict(GOOD_EVENT, is_active=False)
        r = client.get(f"/e/{GOOD_EVENT['id']}")
        check("inactive event returns 404", r.status_code, 404)

        def _boom(_id):
            raise RuntimeError("timeout expired")

        app_module.get_event_by_id = _boom
        r = client.get(f"/e/{GOOD_EVENT['id']}")
        check("db failure returns 503, not 404", r.status_code, 503)
        check_true("and does not claim the show was deleted",
                   b"may have been removed" not in r.data)
    finally:
        app_module.get_event_by_id = original


def main():
    print("Testing event permalink pages...\n")
    test_url_safety()
    test_absolute_image_url()
    test_price_parsing()
    test_happy_path()
    test_jsonld()
    test_jsonld_summer_offset()
    test_xss_payloads()
    test_dangerous_urls_in_page()
    test_sparse_event()
    test_missing_page()
    test_route()

    if FAILURES:
        print(f"❌ {len(FAILURES)} of {CHECKS[0]} checks failed:\n")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"✅ All {CHECKS[0]} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
