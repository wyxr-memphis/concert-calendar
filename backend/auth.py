"""JWT authentication for admin API routes."""

import os
import time
import hashlib
import hmac
import base64
import json
from functools import wraps

from flask import request, jsonify

SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
TOKEN_EXPIRY_SECONDS = 8 * 60 * 60  # 8 hours


def create_token():
    """Create a JWT token with HMAC-SHA256 signing."""
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}))
    payload = _b64encode(json.dumps({
        "sub": "admin",
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
        "iat": int(time.time()),
    }))
    signature = _sign(f"{header}.{payload}")
    return f"{header}.{payload}.{signature}"


def verify_token(token):
    """Verify token signature and expiration. Returns payload or None."""
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

        return payload
    except Exception:
        return None


def require_auth(f):
    """Decorator that requires a valid JWT in the Authorization header or cookie."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        # Check Authorization header first
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        # Fall back to cookie
        if not token:
            token = request.cookies.get("admin_token")

        if not token or not verify_token(token):
            return jsonify({"error": "Not authenticated"}), 401

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
