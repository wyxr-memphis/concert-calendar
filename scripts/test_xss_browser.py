#!/usr/bin/env python3
"""End-to-end XSS test: renders the real page in a real browser with hostile data.

scripts/test_escaping.mjs unit-tests the escaping helpers. This drives
docs/index.html in Chromium with the API responses stubbed out, so the payloads
travel the whole path a scraped event actually takes — fetch, render, click,
modal — and any sink that escaping missed executes for real.

That is not hypothetical: this test is what found the second innerHTML sink in
_buildCalendarData. The description was correctly switched to textContent in the
modal, but the calendar-link builder still used the
"assign to innerHTML, read textContent back" idiom to strip tags. A detached div
does not run <script>, which makes that idiom look safe — but the parser still
builds the nodes, so "<img src=x onerror=...>" fired immediately. Now uses
DOMParser, whose documents have no browsing context.

Requires playwright and a Chromium build. Skips cleanly (exit 0) when either is
missing, so it never blocks a machine that has not set them up. Point
CHROME_PATH at a binary to override discovery.

Usage:
    python scripts/test_xss_browser.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Chromium discovery and the static server live in browser_test_util so the two
# browser tests cannot drift apart on them.
from browser_test_util import SkipTest, find_chrome, require_playwright, serve_docs  # noqa: E402

PORT = int(os.environ.get("XSS_TEST_PORT", "8787"))

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


# The payload event must be in the future (past events are filtered out) and in
# a month the view is showing. Near the end of a month these land in the next
# one, so the test navigates forward if the row is not on screen.
def _fixture_dates():
    from datetime import date, timedelta
    today = date.today()
    return (today + timedelta(days=2)).isoformat(), (today + timedelta(days=3)).isoformat()


PAYLOAD_ID = "aaaaaaaa-0000-4000-8000-000000000001"


def build_fixtures():
    d1, d2 = _fixture_dates()
    events = [
        {
            "id": PAYLOAD_ID,
            # Quote characters plus an attribute-injection attempt. Real titles
            # contain quotes: 136 of 3096 events in the snapshot do.
            "title": 'Barraclough\'s "Hi" " onerror="window.__XSS=1" x="',
            "venue": 'Hi Tone " onmouseover="window.__XSS2=1',
            "neighborhood": "Midtown",
            "date": d1, "start_time": "8:00 PM",
            "ticket_url": "javascript:window.__XSS3=1",
            "image_url": "javascript:window.__XSS4=1",
            "description": '<img src=x onerror="window.__XSS5=1">'
                           '<script>window.__XSS6=1</script>plain text',
            "is_active": True, "is_featured": False, "is_wyxr_presents": False,
        },
        {
            # The WYXR Presents section is a separate render path.
            "id": "aaaaaaaa-0000-4000-8000-000000000002",
            "title": 'Presents " onerror="window.__XSS7=1',
            "venue": "Minglewood Hall", "neighborhood": "Midtown",
            "date": d2, "start_time": "9:00 PM",
            "ticket_url": "https://example.com/ok",
            "image_url": "https://example.com/i.jpg",
            "description": "safe", "is_active": True,
            "is_featured": False, "is_wyxr_presents": True,
        },
    ]
    sponsors = [{
        "id": "bbbbbbbb-0000-4000-8000-000000000001",
        "name": 'Sponsor " onerror="window.__XSS8=1',
        "image_url": "javascript:window.__XSS9=1",
        "link_url": "javascript:window.__XSS10=1",
        "display_after_date": d1, "is_active": True,
    }]
    calendar_sponsor = {
        "id": "cccccccc-0000-4000-8000-000000000001",
        "name": 'CalSponsor " onerror="window.__XSS11=1',
        "image_url": "javascript:window.__XSS12=1",
        "link_url": "javascript:window.__XSS13=1",
        "copy_line": "<script>window.__XSS14=1</script>",
        "start_date": "2020-01-01", "end_date": "2099-12-31", "is_active": True,
    }
    return events, sponsors, calendar_sponsor


def main():
    try:
        sync_playwright = require_playwright()
        chrome = find_chrome()
    except SkipTest as e:
        print(f"SKIP: {e}")
        return 0

    print("Browser XSS regression test (offline, stubbed API)")
    events, sponsors, calendar_sponsor = build_fixtures()
    base = serve_docs(PORT)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome)
        page = browser.new_page()
        dialogs, errors = [], []
        page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        page.on("pageerror", lambda e: errors.append(str(e)))

        def route_api(route):
            url = route.request.url
            if "/api/events" in url:
                body = json.dumps(events)
            elif "/api/calendar-sponsor" in url:
                body = json.dumps(calendar_sponsor)
            elif "/api/sponsors" in url:
                body = json.dumps(sponsors)
            else:
                body = "[]"
            route.fulfill(status=200, content_type="application/json", body=body)

        page.route("**/concert-calendar-api.onrender.com/**", route_api)
        page.goto(f"{base}/index.html",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)

        # Advance a month if the payload event is not in the current view.
        for _ in range(2):
            if page.locator(f'[data-event-id="{PAYLOAD_ID}"]').count():
                break
            page.locator("#nextMonth").click()
            page.wait_for_timeout(800)

        rendered = page.locator("[data-event-id]").count()
        print(f"  ({rendered} event rows rendered)")
        check("fixtures rendered", rendered > 0)

        def xss_flags():
            return page.evaluate("() => Object.keys(window).filter(k => k.startsWith('__XSS'))")

        print("\nnothing executed on render")
        check("no __XSS* global set", not xss_flags(), str(xss_flags()))
        check("no dialog fired", not dialogs, str(dialogs))
        check("no uncaught page errors", not errors, "; ".join(errors[:2]))

        print("\nno payload reached a handler attribute")
        poisoned = page.evaluate(
            """() => Array.from(document.querySelectorAll('[onerror],[onmouseover],[onload]'))
                 .map(e => (e.getAttribute('onerror')||'') + (e.getAttribute('onmouseover')||'')
                           + (e.getAttribute('onload')||''))
                 .filter(v => v.includes('__XSS'))"""
        )
        check("no handler attribute contains a payload", not poisoned, str(poisoned[:2]))

        print("\nno script-bearing URL rendered")
        bad_urls = page.evaluate(
            """() => Array.from(document.querySelectorAll('img, a'))
                 .map(e => e.getAttribute('src') || e.getAttribute('href'))
                 .filter(Boolean)
                 .filter(u => /^\\s*(javascript|data|vbscript|file):/i.test(u))"""
        )
        check("no javascript:/data: URL in the DOM", not bad_urls, str(bad_urls[:3]))

        print("\nquote-laden values survive as literal text")
        labels = page.eval_on_selector_all(
            "[data-event-id][aria-label]",
            "els => els.map(e => e.getAttribute('aria-label'))")
        intact = [l for l in labels if l and "onerror" in l]
        check("attribute holds the payload as data, not markup", len(intact) > 0,
              intact[0][:60] if intact else "not found")

        print("\nthe event modal")
        target = page.locator(f'[data-event-id="{PAYLOAD_ID}"]').first
        check("payload event is in the main list", target.count() > 0)
        if target.count():
            target.click()
            page.wait_for_timeout(900)
            desc = page.locator("#eventModalDesc")
            if desc.count():
                check("description renders markup as visible text",
                      "<img" in desc.inner_text(), desc.inner_text()[:50])
                check("no real <img> was created in the description",
                      desc.locator("img").count() == 0)
            check("Buy Tickets suppressed for a javascript: URL",
                  page.locator(".event-modal-btn-tickets").count() == 0)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            check("Esc closes the event modal",
                  page.locator("#eventModal.open").count() == 0)
            check("Esc did not also close the subscribe modal",
                  page.locator("#subscribeModal.open").count() == 0)

        # The calendar-link builder reads the description too — this is the check
        # that caught the second innerHTML sink.
        print("\nafter interacting with the modal")
        check("still no __XSS* global", not xss_flags(), str(xss_flags()))
        check("still no dialog", not dialogs, str(dialogs))

        browser.close()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("All browser XSS checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
