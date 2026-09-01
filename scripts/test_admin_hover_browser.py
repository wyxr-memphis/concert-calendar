#!/usr/bin/env python3
"""End-to-end test for the admin event list's hover preview card.

The Events tab shows the full event record on row hover so an editor scanning
the list does not have to open the edit page to see the details. That card
renders eleven scraper- and OCR-sourced fields into the admin origin — the same
origin that holds sessionStorage.admin_token, and where API key names were once
a live stored-XSS vector. So the payloads here travel the real path: stubbed API
response, real Chromium, real mouseover.

It also pins the behaviour that is easy to regress silently:
  - the card must not swallow the row click that opens the edit page,
  - it must stay inside the viewport wherever the cursor is,
  - it must disappear when the pointer leaves the table,
  - it must not nest a Cloudinary URL inside a Cloudinary URL (each nested URL
    bills as its own derived asset against the free-tier quota),
  - a dead image URL must not leave a broken placeholder box.

Requires playwright and a Chromium build. Skips cleanly (exit 0) when either is
missing. Point CHROME_PATH at a binary to override discovery.

Usage:
    python scripts/test_admin_hover_browser.py
"""
import base64
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_test_util import SkipTest, find_chrome, require_playwright, serve_docs  # noqa: E402

PORT = int(os.environ.get("HOVER_TEST_PORT", "8791"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN_HTML = os.path.join(ROOT, "docs", "admin", "index.html")

FAILURES = []

CLEAN_ID = "11111111-1111-1111-1111-111111111111"
HOSTILE_ID = "22222222-2222-2222-2222-222222222222"

# A 1x1 PNG, so the transformed thumbnail URL can be asserted on. Serving a 404
# instead would legitimately remove the element.
ONE_PX_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

EVENTS = [
    {
        "id": CLEAN_ID,
        "title": 'Lucero "Hometown" & Friends',
        "venue": "Hi Tone",
        # Far future so it survives the default Upcoming filter forever.
        "date": "2099-10-11",  # a Sunday
        "start_time": "9:00 PM",
        "doors_time": "8:00 PM",
        "ticket_url": "https://www.dice.fm/event/abc",
        "ticket_price": "$25",
        "image_url": "https://res.cloudinary.com/demo/image/upload/v1/sample.jpg",
        "description": "A long-running Memphis band plays a hometown show with special guests.",
        "genre": "Rock",
        "source": "ticketmaster",
        "is_featured": True,
        "is_wyxr_presents": True,
        "is_active": True,
        "updated_at": "2026-08-30T12:00:00+00:00",
    },
    {
        # Hostile content in every field the card renders, including the two
        # that reach an attribute (image_url) and a URL sink (ticket_url).
        "id": HOSTILE_ID,
        "title": '<img src=x onerror=window.__XSS_T=1>"><scr' + 'ipt>window.__XSS_T=1</scr' + 'ipt>',
        "venue": '" onmouseover="window.__XSS_V=1',
        "date": "2099-10-12",
        "start_time": "<b>8pm</b>",
        "doors_time": "'\"><svg onload=window.__XSS_D=1>",
        "ticket_url": "javascript:window.__XSS_U=1",
        "ticket_price": "<i>free</i>",
        "image_url": 'javascript:window.__XSS_I=1"><img src=y onerror=window.__XSS_I=1>',
        "description": "<scr" + "ipt>window.__XSS_DESC=1</scr" + "ipt>",
        "genre": "</dd><img src=z onerror=window.__XSS_G=1>",
        "source": "manual",
        "is_featured": False,
        "is_wyxr_presents": False,
        "is_active": False,
        "updated_at": "2026-08-31T12:00:00+00:00",
    },
]


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def main():
    try:
        sync_playwright = require_playwright()
        chrome = find_chrome()
    except SkipTest as exc:
        print(f"SKIP: {exc}")
        return 0

    base = serve_docs(PORT)
    # Rewrite the API base to same-origin. The page ships pointing at Render,
    # and a cross-origin stub cannot satisfy a credentialed CORS request.
    admin_html = io.open(ADMIN_HTML, encoding="utf-8").read().replace(
        "window.__API_BASE = 'https://concert-calendar-api.onrender.com'",
        "window.__API_BASE = ''",
    )

    console_errors = []
    watching = {"on": True}
    navigations = []

    def note_console(msg):
        # The 404 below is deliberate, and an aborted request is not a defect.
        if not watching["on"] or msg.type != "error":
            return
        if "net::ERR_FAILED" in msg.text or "404 (Not Found)" in msg.text:
            return
        console_errors.append(msg.text)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("console", note_console)
        page.on("pageerror", lambda e: watching["on"] and console_errors.append(f"pageerror: {e}"))
        page.on("framenavigated", lambda f: navigations.append(f.url))

        def stub(route, body):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        # Playwright matches routes last-registered-first, so the catch-all goes first.
        page.route("**/api/**", lambda r: stub(r, []))
        page.route("**/api/admin/me", lambda r: stub(r, {"token": "t", "user": "test"}))
        page.route("**/api/admin/events", lambda r: stub(r, EVENTS))
        page.route("**/admin/index.html", lambda r: r.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=admin_html))
        page.route("https://res.cloudinary.com/**", lambda r: r.fulfill(
            status=200, content_type="image/png", body=ONE_PX_PNG))

        page.goto(f"{base}/admin/index.html", wait_until="domcontentloaded")
        page.evaluate("sessionStorage.setItem('admin_token','t')")
        page.reload(wait_until="domcontentloaded")
        page.click('.nav-tab[data-tab="events"]')
        page.click('.filter-tab[data-filter="all"]')
        page.wait_for_selector("#eventBody tr[data-id]")

        card = page.query_selector("#eventHover")
        check("hover card element exists", card is not None)
        check("both fixture rows rendered",
              len(page.query_selector_all("#eventBody tr[data-id]")) == 2)

        print("\nhovering a well-formed event")
        page.hover(f'#eventBody tr[data-id="{CLEAN_ID}"] .col-title')
        page.wait_for_selector("#eventHover.visible", timeout=5000)
        text = card.inner_text()
        for want in ["Lucero", "Hi Tone", "Sunday, October 11, 2099", "9:00 PM", "8:00 PM",
                     "$25", "Rock", "dice.fm", "WYXR PRESENTS", "FEATURED", "ticketmaster",
                     "hometown show"]:
            check(f"card shows {want!r}", want.lower() in text.lower())

        src = page.get_attribute("#eventHover .hc-thumb", "src") or ""
        check("thumbnail is width-limited", "w_400,c_fill" in src, src)
        check("thumbnail is not nested Cloudinary-in-Cloudinary",
              src.count("res.cloudinary.com") == 1, src)

        box = card.bounding_box()
        check("card is laid out", bool(box) and box["width"] > 200 and box["height"] > 100, str(box))
        check("card stays inside the viewport",
              bool(box) and box["x"] >= 0 and box["y"] >= 0
              and box["x"] + box["width"] <= 1280 and box["y"] + box["height"] <= 900, str(box))

        print("\nhovering an event full of hostile strings")
        page.hover(f'#eventBody tr[data-id="{HOSTILE_ID}"] .col-title')
        page.wait_for_timeout(700)
        check("card switched rows", page.query_selector("#eventHover.visible") is not None)
        hostile = card.inner_text()
        check("hostile title rendered as literal text", "onerror" in hostile)
        check("no injected elements in the card",
              page.evaluate("document.querySelectorAll('#eventHover img, #eventHover svg,"
                            " #eventHover script').length") == 0)
        check("javascript: image_url rendered no thumbnail",
              page.query_selector("#eventHover .hc-thumb") is None)
        flags = page.evaluate("Object.keys(window).filter(k => k.startsWith('__XSS'))")
        check("no __XSS* global was set", not flags, str(flags))

        print("\nleaving the table")
        page.hover(".nav-tabs")
        page.wait_for_timeout(400)
        check("card is no longer visible", page.query_selector("#eventHover.visible") is None)
        check("card is hidden from the a11y tree",
              page.evaluate("document.getElementById('eventHover').hidden"))

        print("\na dead image URL")
        page.route("https://res.cloudinary.com/**", lambda r: r.fulfill(status=404, body=""))
        page.hover(f'#eventBody tr[data-id="{CLEAN_ID}"] .col-title')
        page.wait_for_selector("#eventHover.visible", timeout=5000)
        page.wait_for_timeout(700)
        check("broken thumbnail was removed", page.query_selector("#eventHover .hc-thumb") is None)
        check("rest of the card survived", "Lucero" in card.inner_text())

        print("\nrow click still opens the edit page")
        # Only index.html is stubbed, so edit.html legitimately bounces on to
        # login.html — assert on the navigation, not the resting URL.
        watching["on"] = False
        navigations.clear()
        page.click(f'#eventBody tr[data-id="{CLEAN_ID}"] .col-title')
        page.wait_for_timeout(800)
        check("click navigated to the edit page",
              any(f"edit.html?id={CLEAN_ID}" in u for u in navigations), str(navigations))

        browser.close()

    check("no console errors", not console_errors, "; ".join(console_errors[:3]))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("All admin hover-card checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
