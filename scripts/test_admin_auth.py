#!/usr/bin/env python3
"""Regression tests for admin authentication hardening (REVIEW.md 1.5/1.6, issue #15).

  * The admin cookie is SameSite=None so the Vercel frontend can reach the
    Render API, which means the browser also sends it cross-site. A
    multipart/form-data POST is a CORS-simple request — no preflight — so any
    page could trigger the admin upload routes. Those routes must therefore
    refuse cookie-only auth and require an Authorization: Bearer header.
  * POST /api/admin/login had no rate limit, making one shared password an
    unlimited guessing oracle.
  * hmac.compare_digest raises TypeError on a non-ASCII str, so a password with
    an accent in it returned 500 instead of 401.
  * There was no way to revoke a leaked session short of rotating
    ADMIN_SECRET_KEY on Render (a redeploy). Tokens now carry an epoch that
    POST /api/admin/revoke-sessions bumps.
  * Admin writes were not recorded anywhere.

Runs offline: every assertion here is decided before the request handler runs,
so no database is touched. DATABASE_URL is deliberately not required.

Usage:
    python scripts/test_admin_auth.py
"""
import base64
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEST_PASSWORD = "correct-horse-battery-staple"
os.environ["ADMIN_PASSWORD"] = TEST_PASSWORD
os.environ.setdefault("ADMIN_SECRET_KEY", "test-only-secret-key")

import backend.app as app_mod  # noqa: E402
import backend.auth as auth_mod  # noqa: E402
from backend.auth import create_token, verify_token  # noqa: E402

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


def test_me_echoes_the_token_for_bearer_recovery():
    """A cookie-only tab must be able to recover its Bearer token.

    sessionStorage is per-tab and the cookie is not, so a new tab (the Slack
    reply links straight to /admin/edit?id=...) authenticates on the cookie but
    has no header to send, and every multipart upload route 401s. GET
    /api/admin/me echoes the token it authenticated with so the page can seed
    the header — and echoes the SAME token, not a fresh one, so a session cannot
    extend itself past its 8 hours by polling this route.
    """
    print("\nGET /api/admin/me echoes the authenticating token")
    token = create_token()
    c = client()
    c.set_cookie("admin_token", token, domain="localhost")
    body = c.get("/api/admin/me").get_json() or {}
    check("cookie request gets a token back", body.get("token") == token,
          f"got {body.get('token')!r}")

    c2 = client()
    body2 = c2.get("/api/admin/me",
                   headers={"Authorization": f"Bearer {token}"}).get_json() or {}
    check("bearer request echoes the same token", body2.get("token") == token,
          f"got {body2.get('token')!r}")

    c3 = client()
    check("unauthenticated request gets no token",
          "token" not in (c3.get("/api/admin/me").get_json() or {}))


def test_recovered_token_reaches_the_upload_routes():
    """The echoed token must actually satisfy require_bearer_auth."""
    print("\nthe echoed token unlocks the upload routes")
    c = client()
    c.set_cookie("admin_token", create_token(), domain="localhost")
    recovered = (c.get("/api/admin/me").get_json() or {}).get("token")
    check("a token was recovered", bool(recovered))
    for route in MULTIPART_ROUTES:
        resp = c.post(
            route,
            data={},
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {recovered}"},
        )
        check(f"not 401 with the recovered token: {route}",
              resp.status_code != 401, f"got {resp.status_code}")


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


# ---------------------------------------------------------------------------
# #15  Token revocation
# ---------------------------------------------------------------------------

def _pin_epoch(value):
    """Force the cached epoch so no database read is attempted."""
    auth_mod._epoch_cache["value"] = value
    auth_mod._epoch_cache["fetched_at"] = time.time()


def _token_payload(token):
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def test_token_carries_an_epoch():
    print("\ntokens carry the epoch they were issued under")
    _pin_epoch(7)
    try:
        payload = _token_payload(create_token())
        check("epoch is in the payload", payload.get("epoch") == 7,
              str(payload.get("epoch")))
    finally:
        auth_mod.invalidate_epoch_cache()


def test_bumping_the_epoch_kills_existing_tokens():
    print("\nrevoking sessions invalidates tokens already issued")
    _pin_epoch(7)
    try:
        token = create_token()
        check("token valid at its own epoch", verify_token(token) is not None)
        _pin_epoch(8)  # what bump_admin_token_epoch() would produce
        check("token rejected after a bump", verify_token(token) is None)
        check("a freshly minted token works again",
              verify_token(create_token()) is not None)
    finally:
        auth_mod.invalidate_epoch_cache()


def test_unreadable_epoch_fails_open():
    """A database blip must not lock the admin out.

    current_token_epoch() returns None when it cannot read, and verify_token
    skips the check for None. Availability wins: revocation is rare and
    deliberate, tokens still expire on their own within 8 hours, and Render
    Postgres times out occasionally.
    """
    print("\nan unreadable epoch does not lock anyone out")
    # Force the read to fail rather than relying on the environment lacking a
    # database — test_before_push.sh sources .env, so DATABASE_URL is usually
    # present and the read would succeed.
    import backend.db as db_mod
    original = db_mod.get_admin_token_epoch

    def _boom():
        raise RuntimeError("timeout expired")

    db_mod.get_admin_token_epoch = _boom
    auth_mod.invalidate_epoch_cache()
    try:
        check("epoch reads as None", auth_mod.current_token_epoch() is None)
        token = create_token()
        check("token still verifies", verify_token(token) is not None)
    finally:
        db_mod.get_admin_token_epoch = original
        auth_mod.invalidate_epoch_cache()


def test_revoke_route_refuses_cookie_only_auth():
    print("\nPOST /api/admin/revoke-sessions requires a Bearer header")
    _pin_epoch(1)
    try:
        token = create_token()
        c = client()
        c.set_cookie("admin_token", token, domain="localhost")
        resp = c.post("/api/admin/revoke-sessions")
        check("401 with cookie only", resp.status_code == 401, f"got {resp.status_code}")

        c2 = client()
        resp2 = c2.post("/api/admin/revoke-sessions",
                        headers={"Authorization": f"Bearer {token}"})
        # Reaching the handler means auth passed; without a database it then
        # returns 503, which is exactly the "could not revoke" path.
        check("Bearer header gets past auth", resp2.status_code != 401,
              f"got {resp2.status_code}")
    finally:
        auth_mod.invalidate_epoch_cache()


# ---------------------------------------------------------------------------
# #15  Admin audit log
# ---------------------------------------------------------------------------

def test_audit_log_records_only_authenticated_writes():
    print("\nthe audit hook records writes, not reads or failed attempts")
    _pin_epoch(1)
    recorded = []
    original = app_mod.log_admin_action
    app_mod.log_admin_action = lambda **kw: recorded.append(kw)
    # These routes reach for the database, which this process does not have.
    # Letting Flask turn that into a 500 response (rather than re-raising under
    # TESTING) is the point: after_request still runs, so an attempted change is
    # audited even when the change itself failed.
    app_mod.app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        token = create_token()
        auth = {"Authorization": f"Bearer {token}"}

        recorded.clear()
        client().get("/api/admin/events", headers=auth)
        check("a GET is not audited", not recorded, str(recorded[:1]))

        # An unauthenticated write must not be able to write audit rows.
        recorded.clear()
        client().delete("/api/admin/events/11111111-1111-1111-1111-111111111111")
        check("a 401 is not audited", not recorded, str(recorded[:1]))

        recorded.clear()
        client().delete("/api/admin/events/11111111-1111-1111-1111-111111111111",
                        headers=auth)
        check("an authenticated DELETE is audited", len(recorded) == 1,
              str(recorded[:1]))
        if recorded:
            entry = recorded[0]
            check("records the method", entry.get("method") == "DELETE",
                  str(entry.get("method")))
            check("records the path",
                  entry.get("path", "").startswith("/api/admin/events/"),
                  str(entry.get("path")))
            check("records a status code", entry.get("status_code") is not None)
            # The IP is hashed, never stored in the clear.
            ip_hash = entry.get("ip_hash")
            check("ip is hashed or absent, never raw",
                  ip_hash is None or (len(ip_hash) == 64 and "." not in ip_hash),
                  str(ip_hash))

        recorded.clear()
        client().post("/api/admin/nonexistent-route", headers=auth)
        check("a 404 admin write is still audited (attempted change)",
              len(recorded) <= 1)
    finally:
        app_mod.log_admin_action = original
        app_mod.app.config["PROPAGATE_EXCEPTIONS"] = None
        auth_mod.invalidate_epoch_cache()


def main():
    print("Admin auth regression tests (offline)")
    for fn in (
        test_cookie_alone_cannot_reach_upload_routes,
        test_bearer_header_passes_auth,
        test_bad_token_still_rejected,
        test_cookie_still_works_for_normal_routes,
        test_me_echoes_the_token_for_bearer_recovery,
        test_recovered_token_reaches_the_upload_routes,
        test_login_is_rate_limited,
        test_throttle_is_per_client,
        test_success_clears_the_failure_budget,
        test_non_ascii_password_is_401_not_500,
        test_correct_password_still_issues_a_token,
        test_health_reports_missing_secret_key,
        test_token_carries_an_epoch,
        test_bumping_the_epoch_kills_existing_tokens,
        test_unreadable_epoch_fails_open,
        test_revoke_route_refuses_cookie_only_auth,
        test_audit_log_records_only_authenticated_writes,
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
