#!/usr/bin/env python3
"""Regression tests for the security headers on both origins.

Two halves:

1. **Flask** (`backend/app.py`) — asserted through the test client. Covers the
   two Content-Security-Policy variants: JSON responses get a deny-everything
   policy, the `/e/<id>` HTML page gets one that still allows the fonts and
   images it actually needs.

2. **Vercel** (`vercel.json`) — the policy is *parsed out of the config file*
   and applied by a local server to the real `docs/index.html`, which is then
   driven in Chromium. This half exists because a CSP that breaks the page is
   worse than no CSP: the calendar fetches its events at runtime, loads Google
   Fonts, reports to GA, and frames a Mailchimp form, and every one of those is
   a directive that can silently kill a feature. Testing the shipped string
   rather than a copy means the test fails if the policy drifts.

The browser half needs Chromium and skips cleanly without it — check for the
PASS lines, not just a zero exit.

Usage:
    python scripts/test_security_headers.py
"""

import http.server
import json
import os
import socketserver
import sys
import threading
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from browser_test_util import (  # noqa: E402
    DOCS,
    ROOT,
    SkipTest,
    find_chrome,
    require_playwright,
)

PORT = int(os.environ.get("CSP_TEST_PORT", "8792"))

FAILURES = []
CHECKS = [0]


def check(label, cond, detail=""):
    CHECKS[0] += 1
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def section(title):
    print(f"\n{title}")


# ---------------------------------------------------------------------------
# The shipped Vercel policy
# ---------------------------------------------------------------------------

def vercel_security_headers():
    """The security headers from vercel.json's catch-all rule."""
    cfg = json.loads((Path(ROOT) / "vercel.json").read_text())
    for rule in cfg.get("headers", []):
        keys = {h["key"] for h in rule["headers"]}
        if "Content-Security-Policy" in keys:
            return {h["key"]: h["value"] for h in rule["headers"]}
    return {}


# ---------------------------------------------------------------------------
# Flask origin
# ---------------------------------------------------------------------------

def test_flask_headers():
    os.environ.setdefault("ADMIN_PASSWORD", "test-only")
    os.environ.setdefault("ADMIN_SECRET_KEY", "test-only-key")

    import backend.app as app_module

    app_module._db_ready = True
    client = app_module.app.test_client()

    section("Flask: JSON responses")
    r = client.get("/health")
    for header, expected in [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ]:
        check(f"{header} is {expected}", r.headers.get(header) == expected,
              str(r.headers.get(header)))
    csp = r.headers.get("Content-Security-Policy", "")
    check("JSON CSP denies everything by default", "default-src 'none'" in csp, csp)
    check("JSON CSP forbids framing", "frame-ancestors 'none'" in csp)
    # HSTS over plain http would pin a developer's localhost to https.
    check("no HSTS on a plain-http request",
          "Strict-Transport-Security" not in r.headers)

    section("Flask: HSTS over TLS")
    r = client.get("/health", base_url="https://concert-calendar-api.onrender.com")
    check("HSTS present on https", "Strict-Transport-Security" in r.headers,
          r.headers.get("Strict-Transport-Security", ""))

    section("Flask: the /e/<id> HTML page")
    original = app_module.get_event_by_id
    try:
        app_module.get_event_by_id = lambda _id: {
            "id": "11111111-1111-1111-1111-111111111111",
            "title": "Test Show", "venue": "Hi Tone", "date": "2026-11-05",
            "start_time": "8:00 PM", "is_active": True,
        }
        r = client.get("/e/11111111-1111-1111-1111-111111111111")
        check("page still renders", r.status_code == 200, str(r.status_code))
        csp = r.headers.get("Content-Security-Policy", "")
        # The page has no executable script at all — the only script element is
        # a JSON-LD data block, which CSP does not treat as script.
        check("HTML CSP forbids all script", "script-src 'none'" in csp, csp)
        check("HTML CSP allows the inline stylesheet",
              "style-src 'unsafe-inline'" in csp)
        check("HTML CSP allows Google Fonts CSS",
              "https://fonts.googleapis.com" in csp)
        check("HTML CSP allows the font files",
              "font-src https://fonts.gstatic.com" in csp)
        # Event images come from Cloudinary, the legacy Vercel path, and
        # arbitrary venue sites — that set cannot be enumerated.
        check("HTML CSP allows https images", "img-src https: data:" in csp)
        check("HTML CSP forbids framing", "frame-ancestors 'none'" in csp)
        check("HTML CSP forbids form posts", "form-action 'none'" in csp)
    finally:
        app_module.get_event_by_id = original

    section("Flask: a route's own headers are not clobbered")
    # The event page sets its own Cache-Control; after_request must fill in
    # only what is missing.
    try:
        app_module.get_event_by_id = lambda _id: {
            "id": "22222222-2222-2222-2222-222222222222", "title": "T",
            "venue": "V", "date": "2026-11-05", "is_active": True,
        }
        r = client.get("/e/22222222-2222-2222-2222-222222222222")
        check("route Cache-Control survives",
              "s-maxage" in r.headers.get("Cache-Control", ""),
              r.headers.get("Cache-Control", ""))
    finally:
        app_module.get_event_by_id = original


# ---------------------------------------------------------------------------
# Vercel origin, in a real browser under the real policy
# ---------------------------------------------------------------------------

def test_vercel_csp_declaration():
    section("vercel.json: policy declaration")
    headers = vercel_security_headers()
    check("a catch-all security rule exists", bool(headers))
    if not headers:
        return
    csp = headers.get("Content-Security-Policy", "")
    for directive, why in [
        ("default-src 'self'", "same-origin default"),
        ("object-src 'none'", "no plugins"),
        ("base-uri 'self'", "no <base> hijacking"),
        ("frame-ancestors 'self'", "no clickjacking"),
        ("https://concert-calendar-api.onrender.com", "the API the page fetches from"),
        ("https://fonts.gstatic.com", "the font files"),
        ("https://wyxr.us19.list-manage.com", "the Mailchimp subscribe iframe"),
        ("https://www.googletagmanager.com", "gtag.js"),
    ]:
        check(f"CSP declares {directive} ({why})", directive in csp)
    for header, expected in [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "SAMEORIGIN"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ]:
        check(f"{header} is {expected}", headers.get(header) == expected,
              str(headers.get(header)))
    check("HSTS is declared", "max-age=" in headers.get("Strict-Transport-Security", ""))


class _CSPHandler(http.server.SimpleHTTPRequestHandler):
    """Serves docs/ with the shipped Vercel security headers attached."""

    extra_headers = {}

    def end_headers(self):
        for key, value in self.extra_headers.items():
            self.send_header(key, value)
        super().end_headers()

    def log_message(self, *args):
        pass


def test_page_under_csp():
    section("Chromium: the real page under the shipped CSP")
    try:
        sync_playwright = require_playwright()
        chrome = find_chrome()
    except SkipTest as e:
        print(f"  SKIP: {e}")
        return

    headers = vercel_security_headers()
    # HSTS from a local http origin would pin localhost to https in the
    # browser profile; every other header is applied as shipped.
    headers = {k: v for k, v in headers.items() if k != "Strict-Transport-Security"}

    handler = partial(_CSPHandler, directory=DOCS)
    _CSPHandler.extra_headers = headers
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    from datetime import date, timedelta
    d1 = (date.today() + timedelta(days=2)).isoformat()
    events = [{
        "id": "aaaaaaaa-0000-4000-8000-00000000000a", "title": "CSP Test Show",
        "venue": "Hi Tone", "neighborhood": "Midtown", "date": d1,
        "start_time": "8:00 PM", "ticket_url": "https://example.com/t",
        "image_url": "https://res.cloudinary.com/wyxr/image/upload/v1/x.jpg",
        "description": "d", "is_active": True, "is_featured": False,
        "is_wyxr_presents": False,
    }]

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome)
        page = browser.new_page()
        violations, errors = [], []
        # CSP violations surface as console errors; the security policy also
        # fires securitypolicyviolation in the page.
        page.on("console", lambda m: violations.append(m.text)
                if "Content Security Policy" in m.text else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        def route_api(route):
            url = route.request.url
            # Admin endpoints must 401, or login.html sees a valid session and
            # redirects to /admin/ before its form can be inspected.
            if "/api/admin/" in url:
                route.fulfill(status=401, content_type="application/json",
                              body='{"error": "Not authenticated"}')
            elif "/api/events" in url:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(events))
            elif "calendar-sponsor" in url:
                route.fulfill(status=200, content_type="application/json", body="{}")
            else:
                route.fulfill(status=200, content_type="application/json", body="[]")

        page.route("**/concert-calendar-api.onrender.com/**", route_api)

        page.add_init_script(
            "window.__cspViolations = [];"
            "document.addEventListener('securitypolicyviolation',"
            " e => window.__cspViolations.push(e.violatedDirective + ' <- ' + e.blockedURI));"
        )
        page.goto(f"http://127.0.0.1:{PORT}/index.html",
                  wait_until="load", timeout=30000)
        page.wait_for_timeout(4500)

        in_page = page.evaluate("() => window.__cspViolations || []")

        # The events arriving at all proves connect-src allows the API.
        rows = page.locator("[data-event-id]").count()
        check("events still load under the CSP", rows > 0, f"{rows} rows")
        check("no CSP violations in the page", not in_page, "; ".join(in_page[:4]))
        check("no CSP violations on the console", not violations,
              "; ".join(violations[:2]))
        check("no uncaught page errors", not errors, "; ".join(errors[:2]))

        # Google Fonts is a stylesheet + font fetch, both CSP-gated.
        font_loaded = page.evaluate(
            "() => Array.from(document.styleSheets).some("
            "  s => (s.href || '').includes('fonts.googleapis.com'))"
        )
        check("Google Fonts stylesheet loaded", font_loaded)

        # Opening the modal exercises the calendar-link builder and the image.
        if rows:
            page.locator("[data-event-id]").first.click()
            page.wait_for_timeout(800)
            check("event modal opens under the CSP",
                  page.locator("#eventModal.open").count() == 1)
            after = page.evaluate("() => window.__cspViolations || []")
            check("still no CSP violations after interacting", not after,
                  "; ".join(after[:3]))

        # The catch-all rule applies the same policy to every page on the
        # origin, so a directive that suits the calendar can still break the
        # submit form or the admin login. Those pages have their own inline
        # scripts, their own fetches, and (on submit) a canvas downscale.
        for path, must_contain in [
            ("submit.html", "#eventTitle, input[name=title], form"),
            ("admin/login.html", "input[type=password]"),
        ]:
            page.evaluate("() => { window.__cspViolations = []; }")
            page.goto(f"http://127.0.0.1:{PORT}/{path}",
                      wait_until="load", timeout=30000)
            page.wait_for_timeout(2500)
            page_violations = page.evaluate("() => window.__cspViolations || []")
            check(f"{path}: no CSP violations", not page_violations,
                  "; ".join(page_violations[:3]))
            check(f"{path}: rendered its form",
                  page.locator(must_contain).count() > 0)

        browser.close()

    httpd.shutdown()


def main():
    print("Testing security headers...")
    test_flask_headers()
    test_vercel_csp_declaration()
    test_page_under_csp()

    print()
    if FAILURES:
        print(f"❌ {len(FAILURES)} of {CHECKS[0]} checks failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"✅ All {CHECKS[0]} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
