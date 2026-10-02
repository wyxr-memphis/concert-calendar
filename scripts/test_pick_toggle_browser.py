#!/usr/bin/env python3
"""End-to-end test for the WYXR Pick toggle on the public calendar page.

A logged-in admin can star a show straight from docs/index.html — a button in
the event modal and a star on each row — instead of finding it again under
/admin/. Everything about that lives in the browser: whether the page even asks
the API if an admin is present, the optimistic re-render, the write-through to
the localStorage cache, and what a 401 does. So this drives the real page in
Chromium with the API stubbed same-origin.

What it pins:

  * an anonymous visitor causes **no** /api/admin/ request and sees no control
  * the non-secret localStorage hint earns exactly one /api/admin/me; a 401
    clears the hint and leaves the page anonymous — never a redirect
  * in admin mode the events fetch busts the 120 s HTTP cache (`_t=`)
  * a toggle sends PATCH .../featured with the Bearer header and a boolean
    body, moves the row into the day's Picks group, updates the modal badge in
    place, and writes through to the cache — without touching history
  * the row star toggles without opening the modal, by click and by keyboard
  * a failed PATCH reverts; a 401 drops admin mode in place

Requires playwright and a Chromium build. Skips cleanly (exit 0) when either is
missing — check for the PASS lines, not just a zero exit.

Usage:
    python scripts/test_pick_toggle_browser.py
"""
import io
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

PORT = int(os.environ.get("PICK_TOGGLE_TEST_PORT", "8793"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML = os.path.join(ROOT, "docs", "index.html")

EVENT_A = "aaaaaaaa-0000-4000-8000-00000000000a"
EVENT_B = "aaaaaaaa-0000-4000-8000-00000000000b"
HINT_KEY = "wyxr_admin_hint"
CACHE_KEY = "wyxr_events_cache"


def build_events():
    # Two days out, so the rows are in the future and (almost always) in the
    # month the view opens on. Both on the same day so they share a section.
    d1 = (date.today() + timedelta(days=2)).isoformat()
    return [
        {
            "id": EVENT_A, "title": "Pick Toggle Test Show", "venue": "Hi Tone",
            "neighborhood": "Midtown", "date": d1, "start_time": "8:00 PM",
            "ticket_url": "", "image_url": "",
            "description": "Not yet a pick.", "is_active": True,
            "is_featured": False, "is_wyxr_presents": False,
        },
        {
            "id": EVENT_B, "title": "Already A Pick", "venue": "Minglewood Hall",
            "neighborhood": "Midtown", "date": d1, "start_time": "9:00 PM",
            "ticket_url": "", "image_url": "",
            "description": "Starred in admin.", "is_active": True,
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

    print("Browser WYXR Pick toggle test (offline, stubbed API)")
    events = build_events()
    base = serve_docs(PORT)
    check = Checker()

    # The page ships pointing at Render. A credentialed cross-origin fetch and
    # a preflighted PATCH cannot be satisfied by a cross-origin stub, so serve
    # a copy that calls the API same-origin.
    index_html = io.open(INDEX_HTML, encoding="utf-8").read()
    marker = "const API_BASE = 'https://concert-calendar-api.onrender.com';"
    if marker not in index_html:
        print("FAIL  API_BASE marker not found in docs/index.html — test needs updating")
        return 1
    index_html = index_html.replace(marker, "const API_BASE = '';")

    # Mutable stub behaviour, flipped per section.
    stub = {"me_status": 401, "patch_status": 200}
    requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome)
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.dismiss())
        page.on("request", lambda r: requests.append(r))

        def fulfill_json(route, status, body):
            route.fulfill(status=status, content_type="application/json",
                          body=json.dumps(body))

        def route_me(route):
            if stub["me_status"] == 200:
                fulfill_json(route, 200, {"ok": True, "user": "admin", "token": "t"})
            else:
                fulfill_json(route, stub["me_status"], {"error": "Not authenticated"})

        def route_featured(route):
            req = route.request
            if stub["patch_status"] != 200:
                fulfill_json(route, stub["patch_status"], {"error": "stubbed failure"})
                return
            event_id = req.url.rsplit("/api/admin/events/", 1)[1].split("/")[0]
            try:
                body = json.loads(req.post_data or "{}")
            except ValueError:
                body = {}
            ev = next((e for e in events if e["id"] == event_id), None)
            if not ev:
                fulfill_json(route, 404, {"error": "Event not found"})
                return
            fulfill_json(route, 200, dict(ev, is_featured=bool(body.get("is_featured"))))

        def route_events(route):
            fulfill_json(route, 200, events)

        # Playwright matches routes last-registered-first: catch-all first.
        page.route("**/api/**", lambda r: fulfill_json(r, 200, []))
        page.route("**/api/events*", route_events)
        page.route("**/api/calendar-sponsor", lambda r: fulfill_json(r, 200, {}))
        page.route("**/api/pledge-drive", lambda r: fulfill_json(r, 200, {"active": False}))
        page.route("**/api/admin/me", route_me)
        page.route("**/api/admin/events/*/featured", route_featured)
        page.route("**/index.html", lambda r: r.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=index_html))

        def load(hint=False, token=None):
            """Reset storage, seed what the section needs, then load fresh.

            The page decides whether it *might* be an admin synchronously at
            script start, so storage has to be in place before the load that
            is under test — hence the throwaway first navigation.
            """
            page.goto(f"{base}/index.html", wait_until="domcontentloaded", timeout=30000)
            page.evaluate("() => { sessionStorage.clear(); localStorage.clear(); }")
            if hint:
                page.evaluate(f"localStorage.setItem({HINT_KEY!r}, '1')")
            if token:
                page.evaluate(f"sessionStorage.setItem('admin_token', {token!r})")
            requests.clear()
            errors.clear()
            page.goto(f"{base}/index.html", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("[data-event-id]", timeout=15000)
            page.wait_for_timeout(1200)
            for _ in range(2):
                if page.locator(f'[data-event-id="{EVENT_A}"]').count():
                    break
                page.locator("#nextMonth").click()
                page.wait_for_timeout(700)

        def admin_requests():
            return [r for r in requests if "/api/admin/" in r.url]

        def patch_requests():
            return [r for r in requests if r.method == "PATCH"]

        def events_request_urls():
            return [r.url for r in requests if "/api/events" in r.url]

        def modal_open():
            return page.locator("#eventModal.open").count() > 0

        def pill_hidden():
            return page.evaluate("document.getElementById('adminPill').hidden")

        def row(event_id):
            return page.locator(f'li[data-event-id="{event_id}"]').first

        def star(event_id):
            return page.locator(f'[data-pick-toggle="{event_id}"]').first

        def in_picks_group(event_id):
            return page.locator(f'.featured-group li[data-event-id="{event_id}"]').count() == 1

        def cached_flag(event_id):
            return page.evaluate(
                "(id) => { const c = JSON.parse(localStorage.getItem(%r) || '[]');"
                " const e = c.find(x => x.id === id); return e ? e.is_featured : null; }"
                % CACHE_KEY, event_id)

        def admin_button():
            return page.locator("#eventModalActions .event-modal-btn-admin")

        def pick_badges():
            return page.locator("#eventModalBadges .event-modal-badge-pick").count()

        # -------------------------------------------------------------------
        check.section("anonymous visitor")
        stub["me_status"] = 401
        load()
        check("event rows rendered", page.locator("[data-event-id]").count() >= 2)
        check.equals("no /api/admin/ request at all", len(admin_requests()), 0)
        check("admin pill stays hidden", pill_hidden())
        check.equals("no row stars", page.locator("[data-pick-toggle]").count(), 0)
        check("events fetch is not cache-busted",
              all("_t=" not in u for u in events_request_urls()),
              "; ".join(events_request_urls()))
        row(EVENT_A).click()
        page.wait_for_timeout(500)
        check("modal opens as before", modal_open())
        check.equals("no pick button in the modal", admin_button().count(), 0)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        check("no uncaught page errors", not errors, "; ".join(errors[:2]))

        # -------------------------------------------------------------------
        check.section("stale hint: /api/admin/me answers 401")
        stub["me_status"] = 401
        load(hint=True)
        me_calls = [r for r in admin_requests() if r.url.endswith("/api/admin/me")]
        check.equals("exactly one /api/admin/me request", len(me_calls), 1)
        check.equals("hint cleared after the 401",
                     page.evaluate(f"localStorage.getItem({HINT_KEY!r})"), None)
        check("still anonymous: no stars", page.locator("[data-pick-toggle]").count() == 0)
        check("admin pill stays hidden", pill_hidden())
        check("no redirect to the admin login",
              page.evaluate("location.pathname").endswith("/index.html"),
              page.evaluate("location.pathname"))
        check("no uncaught page errors", not errors, "; ".join(errors[:2]))

        # -------------------------------------------------------------------
        check.section("live session: hint + /api/admin/me 200")
        stub["me_status"] = 200
        load(hint=True)
        page.wait_for_selector("[data-pick-toggle]", timeout=5000)
        check("admin pill shown", not pill_hidden())
        check.equals("echoed token stored for this tab",
                     page.evaluate("sessionStorage.getItem('admin_token')"), "t")
        check("events fetch bypasses the HTTP cache",
              all("_t=" in u for u in events_request_urls()),
              "; ".join(events_request_urls()))
        check.equals("one star per row", page.locator("[data-pick-toggle]").count(),
                     page.locator("li[data-event-id]").count())
        check.equals("non-pick star is off", star(EVENT_A).get_attribute("aria-pressed"), "false")
        check.equals("existing pick star is on", star(EVENT_B).get_attribute("aria-pressed"), "true")
        check("existing pick sits in the Picks group", in_picks_group(EVENT_B))
        check("non-pick does not", not in_picks_group(EVENT_A))

        # -------------------------------------------------------------------
        check.section("marking a show from the modal")
        stub["patch_status"] = 200
        row(EVENT_A).click()
        page.wait_for_timeout(500)
        check("modal opened", modal_open())
        check.equals("pick button present", admin_button().count(), 1)
        check("button offers to mark", admin_button().inner_text().startswith("☆"),
              admin_button().inner_text())
        check.equals("no pick badge yet", pick_badges(), 0)
        hist_before = page.evaluate("history.length")
        hash_before = page.evaluate("location.hash")
        requests.clear()
        admin_button().click()
        page.wait_for_timeout(800)

        patches = patch_requests()
        check.equals("exactly one PATCH sent", len(patches), 1)
        if patches:
            pr = patches[0]
            check("PATCH hits the featured route",
                  pr.url.endswith(f"/api/admin/events/{EVENT_A}/featured"), pr.url)
            check.equals("Bearer header sent", pr.headers.get("authorization"), "Bearer t")
            try:
                sent = json.loads(pr.post_data or "")
            except ValueError:
                sent = None
            check.equals("boolean JSON body", sent, {"is_featured": True})
        check.equals("modal badge updated in place", pick_badges(), 1)
        check("button now offers to remove", admin_button().inner_text().startswith("★"),
              admin_button().inner_text())
        check.equals("aria-pressed reflects state", admin_button().get_attribute("aria-pressed"), "true")
        check.equals("modal title unchanged", page.locator("#eventModalTitle").inner_text(),
                     "Pick Toggle Test Show")
        check("modal still open", modal_open())
        check.equals("history untouched", page.evaluate("history.length"), hist_before)
        check.equals("hash untouched", page.evaluate("location.hash"), hash_before)
        check("row moved into the Picks group", in_picks_group(EVENT_A))
        check.equals("row star is on", star(EVENT_A).get_attribute("aria-pressed"), "true")
        check.equals("written through to the localStorage cache", cached_flag(EVENT_A), True)
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        check("Escape still closes the modal", not modal_open())
        check.equals("and clears the hash", page.evaluate("location.hash"), "")
        check("focus returned to the (re-rendered) row",
              page.evaluate(f"document.activeElement && document.activeElement.dataset.eventId === {EVENT_A!r}"))

        # -------------------------------------------------------------------
        check.section("row star: click and keyboard, without opening the modal")
        requests.clear()
        star(EVENT_B).click()
        page.wait_for_timeout(800)
        check("click did not open the modal", not modal_open())
        patches = patch_requests()
        check.equals("one PATCH for the star click", len(patches), 1)
        if patches:
            check("unmarks the existing pick",
                  json.loads(patches[0].post_data) == {"is_featured": False}
                  and patches[0].url.endswith(f"/api/admin/events/{EVENT_B}/featured"),
                  patches[0].post_data)
        check("row left the Picks group", not in_picks_group(EVENT_B))
        check.equals("star is off", star(EVENT_B).get_attribute("aria-pressed"), "false")
        check.equals("cache follows", cached_flag(EVENT_B), False)

        requests.clear()
        star(EVENT_A).focus()
        page.keyboard.press("Enter")
        page.wait_for_timeout(800)
        check("Enter on the star did not open the modal", not modal_open())
        check.equals("one PATCH for the keypress", len(patch_requests()), 1)
        check("row left the Picks group", not in_picks_group(EVENT_A))
        check("focus stayed on the re-rendered star",
              page.evaluate(f"document.activeElement && document.activeElement.dataset.pickToggle === {EVENT_A!r}"))
        check("no uncaught page errors", not errors, "; ".join(errors[:2]))

        # -------------------------------------------------------------------
        check.section("a failed PATCH reverts")
        stub["patch_status"] = 500
        requests.clear()
        star(EVENT_B).click()
        page.wait_for_timeout(800)
        check.equals("PATCH was attempted", len(patch_requests()), 1)
        check.equals("star reverted", star(EVENT_B).get_attribute("aria-pressed"), "false")
        check("row not in the Picks group", not in_picks_group(EVENT_B))
        check.equals("cache reverted", cached_flag(EVENT_B), False)
        notice = page.locator("#adminNotice")
        check("error notice shown", notice.is_visible() and "try again" in notice.inner_text(),
              notice.inner_text() if notice.count() else "")
        check("still in admin mode", not pill_hidden())
        check("stars still present", page.locator("[data-pick-toggle]").count() >= 2)

        # -------------------------------------------------------------------
        check.section("a 401 drops admin mode in place")
        stub["patch_status"] = 401
        row(EVENT_A).click()
        page.wait_for_timeout(500)
        check("modal opened", modal_open())
        requests.clear()
        admin_button().click()
        page.wait_for_timeout(800)
        check.equals("state reverted: no pick badge", pick_badges(), 0)
        check.equals("cache reverted", cached_flag(EVENT_A), False)
        check("admin pill hidden", pill_hidden())
        check.equals("pick button removed from the modal", admin_button().count(), 0)
        check.equals("row stars removed", page.locator("[data-pick-toggle]").count(), 0)
        check.equals("token cleared", page.evaluate("sessionStorage.getItem('admin_token')"), None)
        check.equals("hint cleared", page.evaluate(f"localStorage.getItem({HINT_KEY!r})"), None)
        check("session-expired notice shown",
              notice.is_visible() and "Session expired" in notice.inner_text(),
              notice.inner_text() if notice.count() else "")
        check("no redirect to the admin login",
              page.evaluate("location.pathname").endswith("/index.html"),
              page.evaluate("location.pathname"))
        check("modal still open for the visitor", modal_open())
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        check("modal closes normally", not modal_open())
        check("no uncaught page errors", not errors, "; ".join(errors[:2]))

        browser.close()

    return check.report("pick-toggle")


if __name__ == "__main__":
    sys.exit(main())
