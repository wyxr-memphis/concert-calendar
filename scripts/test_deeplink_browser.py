#!/usr/bin/env python3
"""End-to-end test for event deep links and the injected structured data.

Drives docs/index.html in Chromium with the API stubbed, because none of this
behaviour is observable any other way: the events arrive over fetch, the modal
is opened by delegated clicks, and the history plumbing only exists in a real
browser with a real session history.

The history handling is the part worth guarding. It has three distinct paths
that are easy to get subtly wrong:

  * opened by click        -> we own a pushed entry, so closing must go *back*
                              (and the browser's Back must close the modal)
  * loaded straight onto a -> there is no entry of ours to pop, so closing must
    #event= URL               strip the hash in place, never send the visitor
                              off the site
  * navigated by history   -> opening/closing must not push another entry, or
                              Back becomes a loop the user cannot escape

Requires playwright and a Chromium build. Skips cleanly (exit 0) when either is
missing — check for the PASS lines, not just a zero exit.

Usage:
    python scripts/test_deeplink_browser.py
"""
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_test_util import (  # noqa: E402
    Checker,
    SkipTest,
    find_chrome,
    require_playwright,
    serve_docs,
)

PORT = int(os.environ.get("DEEPLINK_TEST_PORT", "8788"))

EVENT_A = "aaaaaaaa-0000-4000-8000-00000000000a"
EVENT_B = "aaaaaaaa-0000-4000-8000-00000000000b"
UNKNOWN = "ffffffff-0000-4000-8000-00000000ffff"


def build_events():
    # Two days out, so the events are in the future and in the month the view
    # opens on for all but the last couple of days of a month.
    d1 = (date.today() + timedelta(days=2)).isoformat()
    d2 = (date.today() + timedelta(days=3)).isoformat()
    return [
        {
            "id": EVENT_A, "title": "Deep Link Test Show", "venue": "Hi Tone",
            "neighborhood": "Midtown", "date": d1, "start_time": "8:00 PM",
            "ticket_url": "https://example.com/tix",
            "image_url": "https://example.com/i.jpg",
            "description": "First show.", "is_active": True,
            "is_featured": False, "is_wyxr_presents": False,
        },
        {
            "id": EVENT_B, "title": "Second Show", "venue": "Minglewood Hall",
            "neighborhood": "Midtown", "date": d2, "start_time": "9:00 PM",
            "ticket_url": "", "image_url": "",
            "description": "Second show.", "is_active": True,
            "is_featured": True, "is_wyxr_presents": False,
        },
    ]


def main():
    try:
        sync_playwright = require_playwright()
        chrome = find_chrome()
    except SkipTest as e:
        print(f"SKIP: {e}")
        return 0

    print("Browser deep-link + structured-data test (offline, stubbed API)")
    events = build_events()
    base = serve_docs(PORT)
    check = Checker()

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.dismiss())

        def route_api(route):
            url = route.request.url
            if "/api/events" in url:
                body = json.dumps(events)
            elif "/api/calendar-sponsor" in url:
                body = "{}"
            else:
                body = "[]"
            route.fulfill(status=200, content_type="application/json", body=body)

        page.route("**/concert-calendar-api.onrender.com/**", route_api)

        def load(hash_part=""):
            page.goto(f"{base}/index.html{hash_part}",
                      wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            # Advance a month if the fixture rows landed in the next one.
            for _ in range(2):
                if page.locator(f'[data-event-id="{EVENT_A}"]').count():
                    break
                page.locator("#nextMonth").click()
                page.wait_for_timeout(700)

        def modal_open():
            return page.locator("#eventModal.open").count() > 0

        def modal_title():
            return page.locator("#eventModalTitle").inner_text()

        # -------------------------------------------------------------------
        check.section("baseline render")
        load()
        check("event rows rendered", page.locator("[data-event-id]").count() > 0)
        check("no modal on a plain load", not modal_open())
        check("no uncaught page errors", not errors, "; ".join(errors[:2]))

        # -------------------------------------------------------------------
        check.section("opening a show writes its URL")
        page.locator(f'[data-event-id="{EVENT_A}"]').first.click()
        page.wait_for_timeout(600)
        check("modal opened", modal_open())
        check.equals("hash names the event", page.evaluate("location.hash"),
                     f"#event={EVENT_A}")
        check("modal shows the right show", modal_title() == "Deep Link Test Show",
              modal_title())
        check("share button is present",
              page.locator("#eventModalActions button", has_text="Copy link").count() == 1)

        check.section("closing returns the URL to the calendar")
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        check("modal closed", not modal_open())
        # history.back() past our pushed entry, so no stale #event= is left in
        # the address bar to be copied or bookmarked.
        check.equals("hash cleared", page.evaluate("location.hash"), "")
        check("still on the calendar page",
              page.evaluate("location.pathname").endswith("/index.html"))

        check.section("the back button closes the modal")
        page.locator(f'[data-event-id="{EVENT_A}"]').first.click()
        page.wait_for_timeout(600)
        check("modal open again", modal_open())
        page.go_back()
        page.wait_for_timeout(700)
        check("back closed the modal", not modal_open())
        check.equals("back cleared the hash", page.evaluate("location.hash"), "")
        check("back did not leave the page",
              page.locator("[data-event-id]").count() > 0)

        check.section("forward re-opens it")
        page.go_forward()
        page.wait_for_timeout(700)
        check("forward re-opened the modal", modal_open())
        check("on the same show", modal_title() == "Deep Link Test Show",
              modal_title())

        # -------------------------------------------------------------------
        check.section("loading a shared link opens that show")
        load(f"#event={EVENT_B}")
        check("modal opened from the hash", modal_open())
        check("on the linked show", modal_title() == "Second Show", modal_title())

        check.section("closing a deep-loaded modal stays on the page")
        page.locator("#eventModalClose").click()
        page.wait_for_timeout(600)
        check("modal closed", not modal_open())
        # There is no entry of ours to pop here — going back would leave the
        # site entirely, so the hash is replaced in place instead.
        check.equals("hash cleared in place", page.evaluate("location.hash"), "")
        check("still on the calendar", page.locator("[data-event-id]").count() > 0)

        check.section("a link to an unknown event degrades quietly")
        errors.clear()
        load(f"#event={UNKNOWN}")
        check("no modal for an unknown id", not modal_open())
        check("calendar still renders", page.locator("[data-event-id]").count() > 0)
        check("no uncaught errors", not errors, "; ".join(errors[:2]))

        load("#event=%3Cscript%3Ealert(1)%3C/script%3E")
        check("a markup payload in the hash opens nothing", not modal_open())
        check("and raises no error", not errors, "; ".join(errors[:2]))

        # -------------------------------------------------------------------
        check.section("structured data for the rendered events")
        load()
        raw = page.evaluate(
            "() => (document.getElementById('eventsJsonLd') || {}).textContent || ''")
        check("json-ld block is populated", len(raw) > 0)
        # A literal '<' here would mean an unescaped scraped title could close
        # the block when the DOM is serialized.
        check("no raw '<' in the json payload", "<" not in raw)
        parsed = None
        try:
            parsed = json.loads(raw)
        except ValueError as e:
            check("json-ld parses", False, str(e))
        if parsed:
            check("json-ld parses", True)
            check.equals("is an ItemList", parsed.get("@type"), "ItemList")
            items = parsed.get("itemListElement", [])
            check("lists the rendered events", len(items) >= 1, f"{len(items)} items")
            first = items[0]["item"] if items else {}
            check.equals("items are MusicEvents", first.get("@type"), "MusicEvent")
            check("each item links to its permalink page",
                  str(first.get("url", "")).startswith(
                      "https://concert-calendar.wyxr.org/e/"),
                  str(first.get("url")))
            check("startDate carries a Central offset",
                  str(first.get("startDate", "")).endswith(("-05:00", "-06:00")),
                  str(first.get("startDate")))
            check.equals("location is a venue",
                         first.get("location", {}).get("@type"), "MusicVenue")

        check.section("feed discovery")
        check("rss feed is linked",
              page.locator('link[rel="alternate"][type="application/rss+xml"]').count() == 1)
        check("calendar feed is linked",
              page.locator('link[rel="alternate"][type="text/calendar"]').count() == 1)
        check("footer offers a webcal subscribe link",
              page.locator('footer a[href^="webcal://"]').count() == 1)

        check.section("accessibility scaffolding")
        check("page has exactly one h1", page.locator("h1").count() == 1)
        check("the h1 is not empty",
              len(page.locator("h1").first.inner_text(timeout=1000).strip()) > 0
              if page.locator("h1").count() else False)
        check("skip link is present", page.locator("a.skip-link").count() == 1)

        browser.close()

    return check.report("deep-link")


if __name__ == "__main__":
    sys.exit(main())
