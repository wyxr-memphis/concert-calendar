"""JWT authentication for admin API routes."""

import os
import time
import hashlib
import hmac
import base64
import json
from functools import wraps

from flask import request, jsonify

import sys

# A per-process random key is a silent failure mode, not a safe default: tokens
# signed by one gunicorn worker are rejected by every other, and every restart
# or deploy invalidates all sessions with no explanation. Announce it loudly and
# expose it on /health so it is diagnosable instead of mysterious.
#
# This deliberately does NOT abort startup. Making it fatal would take the whole
# API down on the next deploy if the variable is unset in the environment, and
# that call belongs to whoever can check Render's config. Flip
# SECRET_KEY_IS_EPHEMERAL to a hard failure once ADMIN_SECRET_KEY is confirmed
# set in production.
ADMIN_SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY")
SECRET_KEY_IS_EPHEMERAL = not ADMIN_SECRET_KEY

if SECRET_KEY_IS_EPHEMERAL:
    SECRET_KEY = __import__("secrets").token_hex(32)
    print(
        "[auth] WARNING: ADMIN_SECRET_KEY is not set. Using a random key for "
        "this process only — admin sessions will not survive a restart and "
        "will not work across multiple workers. Set ADMIN_SECRET_KEY.",
        file=sys.stderr,
        flush=True,
    )
else:
    SECRET_KEY = ADMIN_SECRET_KEY

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
TOKEN_EXPIRY_SECONDS = 8 * 60 * 60  # 8 hours

# Every token carries the epoch that was current when it was issued;
# POST /api/admin/revoke-sessions bumps the stored epoch, which invalidates all
# of them at once. Without this the only way to kill a leaked token was to
# rotate ADMIN_SECRET_KEY on Render — a redeploy, by someone with dashboard
# access.
#
# The epoch lives in the database because gunicorn runs several workers and a
# process-local value would only log out one of them. It is cached for a few
# seconds so this does not become a query on every authenticated request; the
# cost is that a revocation takes up to that long to reach every worker.
TOKEN_EPOCH_CACHE_SECONDS = 15
_epoch_cache = {"value": None, "fetched_at": 0.0}


def current_token_epoch(force=False):
    """The epoch a token must match, or None if it cannot be determined.

    Returns None — rather than raising or defaulting to 0 — when the database
    is unreachable. Callers treat None as "skip the check": Render Postgres
    times out occasionally, and an admin locked out of the UI by a transient
    database blip is a worse outcome than a revoked token surviving a few extra
    seconds. Availability wins here because revocation is a rare, deliberate
    act and the token still expires on its own within 8 hours.
    """
    now = time.time()
    if (not force and _epoch_cache["value"] is not None
            and now - _epoch_cache["fetched_at"] < TOKEN_EPOCH_CACHE_SECONDS):
        return _epoch_cache["value"]

    try:
        from backend.db import get_admin_token_epoch
        epoch = get_admin_token_epoch()
    except Exception as e:
        print(f"[auth] Could not read the token epoch: {e}", flush=True)
        # Keep serving the last known value if we ever had one.
        return _epoch_cache["value"]

    _epoch_cache["value"] = epoch
    _epoch_cache["fetched_at"] = now
    return epoch


def invalidate_epoch_cache():
    """Drop the cached epoch so the next check re-reads it.

    Called right after a bump so the worker that performed the revocation stops
    honouring its own old tokens immediately, rather than up to
    TOKEN_EPOCH_CACHE_SECONDS later.
    """
    _epoch_cache["value"] = None
    _epoch_cache["fetched_at"] = 0.0


def create_token():
    """Create a JWT token with HMAC-SHA256 signing."""
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}))
    payload = _b64encode(json.dumps({
        "sub": "admin",
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
        "iat": int(time.time()),
        "epoch": current_token_epoch() or 0,
    }))
    signature = _sign(f"{header}.{payload}")
    return f"{header}.{payload}.{signature}"


def verify_token(token):
    """Verify token signature, expiration and epoch. Returns payload or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature = parts
        expected = _sign(f"{header_b64}.{payload_b64}")
        if not hmac.compare_digest(signature, expected):
            return None

        payload = json.loads(_b64decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None

        # Revocation check. A token minted before the last bump is dead even
        # though its signature and expiry are still valid. Tokens issued before
        # this field existed have no "epoch" and read as 0, so they are only
        # rejected once someone actually revokes.
        expected_epoch = current_token_epoch()
        if expected_epoch is not None and int(payload.get("epoch", 0) or 0) != expected_epoch:
            return None

        return payload
    except Exception:
        return None


def _bearer_token():
    """The JWT from the Authorization header, or None."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def current_token():
    """The token that authenticated this request, header first then cookie.

    Lets a require_auth route hand the *existing* token back to the admin UI so
    a tab that only has the cookie can populate its Bearer header (see
    /api/admin/me). Returning the token already in play — rather than minting a
    new one — keeps the 8-hour session from silently extending itself.
    """
    return _bearer_token() or request.cookies.get("admin_token")


def require_auth(f):
    """Decorator that requires a valid JWT in the Authorization header or cookie."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _bearer_token() or request.cookies.get("admin_token")

        if not token or not verify_token(token):
            return jsonify({"error": "Not authenticated"}), 401

        return f(*args, **kwargs)
    return decorated


def require_bearer_auth(f):
    """Like require_auth, but refuses cookie-only auth — a CSRF guard.

    The admin cookie is SameSite=None so the admin UI on Vercel can reach the
    API on Render. That means the browser also attaches it to cross-site
    requests. A multipart/form-data POST is a CORS-*simple* request: it triggers
    no preflight, so any page on the internet can submit one to these routes and
    the browser sends the cookie along. The attacker cannot read the response,
    but the write already happened.

    A custom Authorization header is not simple — sending one forces a preflight
    that our CORS policy rejects for unknown origins. So requiring the header,
    and ignoring the cookie, makes these routes unreachable cross-site.

    Apply to any route that mutates state via multipart upload. The admin UI
    always sends the header (see AdminAPI.headers in admin-common.js), so this
    is transparent to it.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _bearer_token()

        if not token or not verify_token(token):
            return jsonify({
                "error": "Not authenticated",
                "detail": "This endpoint requires an Authorization: Bearer header.",
            }), 401

        return f(*args, **kwargs)
    return decorated


def _sign(message):
    sig = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


def _b64encode(data):
    return base64.urlsafe_b64encode(data.encode()).rstrip(b"=").decode()


def _b64decode(data):
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data).decode()
