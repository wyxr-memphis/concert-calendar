#!/usr/bin/env python3
"""Regression tests for admin authentication hardening (REVIEW.md 1.5, 1.6).

  * The admin cookie is SameSite=None so the Vercel frontend can reach the
    Render API, which means the browser also sends it cross-site. A
    multipart/form-data POST is a CORS-simple request — no preflight — so any
    page could trigger the admin upload routes. Those routes must therefore
    refuse cookie-only auth and require an Authorization: Bearer header.
  * POST /api/admin/login had no rate limit, making one shared password an
    unlimited guessing oracle.
  * hmac.compare_digest raises TypeError on a non-ASCII str, so a password with
    an accent in it returned 500 instead of 401.

Runs offline: every assertion here is decided before the request handler runs,
so no database is touched. DATABASE_URL is deliberately not required.

Usage:
    python scripts/test_admin_auth.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEST_PASSWORD = "correct-horse-battery-staple"
os.environ["ADMIN_PASSWORD"] = TEST_PASSWORD
os.environ.setdefault("ADMIN_SECRET_KEY", "test-only-secret-key")

import backend.app as app_mod  # noqa: E402
from backend.auth import create_token  # noqa: E402

# Routes that mutate state through a multipart upload.
MULTIPART_ROUTES = [
    "/api/admin/import/upload",
    "/api/admin/import/image",
    "/api/admin/sponsors/upload-image",
    "/api/admin/calendar-sponsor/upload-image",
]

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def client():
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def reset_login_throttle():
    app_mod._login_attempts.clear()


# ---------------------------------------------------------------------------
# 1.5  CSRF on multipart routes
# ---------------------------------------------------------------------------

def test_cookie_alone_cannot_reach_upload_routes():
    print("\nmultipart upload routes reject cookie-only auth")
    token = create_token()
    for route in MULTIPART_ROUTES:
        c = client()
        c.set_cookie("admin_token", token, domain="localhost")
        resp = c.post(route, data={"file": "x"}, content_type="multipart/form-data")
        check(f"401 with cookie only: {route}", resp.status_code == 401,
              f"got {resp.status_code}")


def test_bearer_header_passes_auth():
    """A valid header must get past auth — proving the guard is not a blanket 401.

    Reaching the handler without a file yields a 4xx that is *not* 401, or a 5xx
    if the handler then needs a database. Either proves auth succeeded.
    """
    print("\nmultipart upload routes accept a Bearer header")
    token = create_token()
    for route in MULTIPART_ROUTES:
        c = client()
        resp = c.post(
            route,
            data={},
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {token}"},
        )
        check(f"not 401 with header: {route}", resp.status_code != 401,
              f"got {resp.status_code}")


def test_bad_token_still_rejected():
    print("\nan invalid Bearer token is still rejected")
    for route in MULTIPART_ROUTES:
        c = client()
        resp = c.post(
            route,
            data={},
            content_type="multipart/form-data",
            headers={"Authorization": "Bearer not.a.token"},
        )
        check(f"401 with bad token: {route}", resp.status_code == 401,
              f"got {resp.status_code}")


def test_cookie_still_works_for_normal_routes():
    """The cookie fallback must survive for non-multipart routes."""
    print("\ncookie auth still works where it is safe")
    c = client()
    c.set_cookie("admin_token", create_token(), domain="localhost")
    resp = c.get("/api/admin/me")
    check("GET /api/admin/me accepts the cookie", resp.status_code == 200,
          f"got {resp.status_code}")


# ---------------------------------------------------------------------------
# 1.6  Login hardening
# ---------------------------------------------------------------------------

def test_login_is_rate_limited():
    print("\nfailed logins are throttled")
    reset_login_throttle()
    c = client()
    headers = {"X-Forwarded-For": "203.0.113.7"}
    codes = []
    for _ in range(app_mod.LOGIN_MAX_ATTEMPTS + 3):
        resp = c.post("/api/admin/login", json={"password": "wrong"}, headers=headers)
        codes.append(resp.status_code)

    check("first attempts return 401",
          codes[:app_mod.LOGIN_MAX_ATTEMPTS] == [401] * app_mod.LOGIN_MAX_ATTEMPTS,
          f"got {codes[:app_mod.LOGIN_MAX_ATTEMPTS]}")
    check("further attempts return 429",
          all(c == 429 for c in codes[app_mod.LOGIN_MAX_ATTEMPTS:]),
          f"got {codes[app_mod.LOGIN_MAX_ATTEMPTS:]}")

    resp = c.post("/api/admin/login", json={"password": "wrong"}, headers=headers)
    check("429 carries Retry-After", resp.headers.get("Retry-After") is not None)


def test_throttle_is_per_client():
    print("\nthrottling one client does not lock out another")
    reset_login_throttle()
    c = client()
    for _ in range(app_mod.LOGIN_MAX_ATTEMPTS + 1):
        c.post("/api/admin/login", json={"password": "wrong"},
               headers={"X-Forwarded-For": "203.0.113.7"})
    blocked = c.post("/api/admin/login", json={"password": "wrong"},
                     headers={"X-Forwarded-For": "203.0.113.7"})
    other = c.post("/api/admin/login", json={"password": "wrong"},
                   headers={"X-Forwarded-For": "198.51.100.4"})
    check("first client is throttled", blocked.status_code == 429,
          f"got {blocked.status_code}")
    check("second client is not", other.status_code == 401, f"got {other.status_code}")


def test_success_clears_the_failure_budget():
    print("\na successful login resets the client's budget")
    reset_login_throttle()
    c = client()
    headers = {"X-Forwarded-For": "203.0.113.9"}
    for _ in range(app_mod.LOGIN_MAX_ATTEMPTS - 1):
        c.post("/api/admin/login", json={"password": "wrong"}, headers=headers)
    ok = c.post("/api/admin/login", json={"password": TEST_PASSWORD}, headers=headers)
    check("correct password succeeds", ok.status_code == 200, f"got {ok.status_code}")
    after = c.post("/api/admin/login", json={"password": "wrong"}, headers=headers)
    check("budget was reset (401, not 429)", after.status_code == 401,
          f"got {after.status_code}")


def test_non_ascii_password_is_401_not_500():
    print("\na non-ASCII password is rejected, not a crash")
    reset_login_throttle()
    c = client()
    for payload in ({"password": "pässwörd"}, {"password": "密码"},
                    {"password": "🔑"}, {"password": None}, {}):
        resp = c.post("/api/admin/login", json=payload,
                      headers={"X-Forwarded-For": "198.51.100.20"})
        check(f"401 for {payload!r}", resp.status_code == 401, f"got {resp.status_code}")


def test_correct_password_still_issues_a_token():
    print("\nthe happy path still works")
    reset_login_throttle()
    c = client()
    resp = c.post("/api/admin/login", json={"password": TEST_PASSWORD},
                  headers={"X-Forwarded-For": "198.51.100.30"})
    check("200", resp.status_code == 200, f"got {resp.status_code}")
    body = resp.get_json() or {}
    check("returns a token", bool(body.get("token")))
    check("sets the cookie",
          any("admin_token" in h for h in resp.headers.getlist("Set-Cookie")))


def test_health_reports_missing_secret_key():
    print("\nhealth reports an ephemeral signing key")
    c = client()
    resp = c.get("/health")
    check("health is 200", resp.status_code == 200, f"got {resp.status_code}")
    check("status is ok", (resp.get_json() or {}).get("status") == "ok")
    # ADMIN_SECRET_KEY is set for this run, so there must be no warning.
    check("no warning when the key is set",
          "warnings" not in (resp.get_json() or {}))


def main():
    print("Admin auth regression tests (offline)")
    for fn in (
        test_cookie_alone_cannot_reach_upload_routes,
        test_bearer_header_passes_auth,
        test_bad_token_still_rejected,
        test_cookie_still_works_for_normal_routes,
        test_login_is_rate_limited,
        test_throttle_is_per_client,
        test_success_clears_the_failure_budget,
        test_non_ascii_password_is_401_not_500,
        test_correct_password_still_issues_a_token,
        test_health_reports_missing_secret_key,
    ):
        fn()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("All admin auth regression tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
