"""Shared JWT auth helpers for admin API routes.

Underscore prefix = shared module, NOT a Vercel handler.
"""

import os
import time
import hashlib
import hmac
import base64
import json


SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY", "")
TOKEN_EXPIRY_SECONDS = 7 * 24 * 60 * 60  # 7 days
COOKIE_NAME = "admin_token"


def create_token() -> str:
    """Create a JWT-like token with HMAC-SHA256 signing.

    Uses a simple header.payload.signature format to avoid PyJWT dependency
    in Vercel's Python runtime. Compatible with standard JWT structure.
    """
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}))
    payload = _b64encode(json.dumps({
        "sub": "admin",
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
        "iat": int(time.time()),
    }))
    signature = _sign(f"{header}.{payload}")
    return f"{header}.{payload}.{signature}"


def verify_token(token: str) -> dict | None:
    """Verify token signature and expiration. Returns payload or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature = parts

        # Verify signature
        expected = _sign(f"{header_b64}.{payload_b64}")
        if not hmac.compare_digest(signature, expected):
            return None

        # Decode payload
        payload = json.loads(_b64decode(payload_b64))

        # Check expiration
        if payload.get("exp", 0) < time.time():
            return None

        return payload
    except Exception:
        return None


def get_token_from_cookie(cookie_header: str | None) -> str | None:
    """Extract admin_token value from Cookie header."""
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(f"{COOKIE_NAME}="):
            return part[len(COOKIE_NAME) + 1:]
    return None


def set_cookie_header(token: str) -> str:
    """Build Set-Cookie header value for the admin token."""
    max_age = TOKEN_EXPIRY_SECONDS
    return (
        f"{COOKIE_NAME}={token}; "
        f"HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age={max_age}"
    )


def clear_cookie_header() -> str:
    """Build Set-Cookie header value that clears the admin token."""
    return f"{COOKIE_NAME}=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0"


def _sign(message: str) -> str:
    """HMAC-SHA256 sign and base64url encode."""
    sig = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


def _b64encode(data: str) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data.encode()).rstrip(b"=").decode()


def _b64decode(data: str) -> str:
    """Base64url decode with padding restoration."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data).decode()
