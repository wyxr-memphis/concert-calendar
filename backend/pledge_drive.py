"""Pledge-drive banner: settings, active window, and the live goal percentage.

The percentage is WYXR's fund-drive thermometer. It is *edited* on wyxr.org (a
password-protected stepper page that is not, and must never be, referenced
from this repo) and *published* by the WordPress thermometer block at
``GOAL_URL`` as ``{"percentage": <0-100>}``. We only ever read the public
endpoint, so no credential is involved.

Settings live as one JSON blob under the ``pledge_drive`` key of the existing
``admin_settings`` table — no DDL, so nothing to register in the schema fast
path. Everything here is pure except ``load_settings``/``save_settings`` (DB)
and ``fetch_percentage`` (one outbound GET, cached per worker).
"""

import json
import logging
import time
from datetime import date

import requests as http_requests

from backend.db import get_admin_setting, set_admin_setting

log = logging.getLogger(__name__)

GOAL_URL = "https://wyxr.org/wp-json/wyxr-blocks/v1/thermostat-goal"
SETTING_KEY = "pledge_drive"

DEFAULT_DONATE_URL = "https://wyxr.org"
MAX_HEADLINE = 80
MAX_COPY = 200

DEFAULTS = {
    "enabled": False,
    "headline": "WYXR Fund Drive",
    "copy": "",
    "donate_url": DEFAULT_DONATE_URL,
    "start_date": None,
    "end_date": None,
}

CACHE_TTL_SEC = 60
FETCH_TIMEOUT_SEC = 4

# Per-gunicorn-worker cache of the last good percentage. Same caveat as the
# health summary cache in app.py: each worker refreshes on its own schedule.
_PCT_CACHE = {"value": None, "fetched_at": 0.0}


# --- settings ---------------------------------------------------------------

def _merge_defaults(raw):
    settings = dict(DEFAULTS)
    if isinstance(raw, dict):
        for key in DEFAULTS:
            if key in raw:
                settings[key] = raw[key]
    return settings


def load_settings():
    """Read the blob from admin_settings; malformed or missing → defaults."""
    stored = get_admin_setting(SETTING_KEY)
    if not stored:
        return dict(DEFAULTS)
    try:
        return _merge_defaults(json.loads(stored))
    except (TypeError, ValueError):
        log.warning("pledge_drive setting is not valid JSON; using defaults")
        return dict(DEFAULTS)


def save_settings(settings):
    set_admin_setting(SETTING_KEY, json.dumps(settings))


def _parse_iso_date(value, field):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a YYYY-MM-DD string or null")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ValueError(f"{field} must be a YYYY-MM-DD date")


def validate_settings(body):
    """Allowlist + coerce an admin PUT body. Raises ValueError with a message
    suitable for a 400 response. Unknown keys are dropped."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")

    enabled = body.get("enabled", DEFAULTS["enabled"])
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
    enabled = bool(enabled)

    headline = body.get("headline", DEFAULTS["headline"])
    headline = (str(headline) if headline is not None else "").strip()
    if not headline:
        headline = DEFAULTS["headline"]
    if len(headline) > MAX_HEADLINE:
        raise ValueError(f"headline must be {MAX_HEADLINE} characters or fewer")

    copy = body.get("copy", DEFAULTS["copy"])
    copy = (str(copy) if copy is not None else "").strip()
    if len(copy) > MAX_COPY:
        raise ValueError(f"copy must be {MAX_COPY} characters or fewer")

    donate_url = body.get("donate_url", DEFAULT_DONATE_URL)
    donate_url = (str(donate_url) if donate_url is not None else "").strip()
    if not donate_url:
        donate_url = DEFAULT_DONATE_URL
    if not donate_url.lower().startswith("https://") or len(donate_url) > 500:
        raise ValueError("donate_url must be an https:// URL")

    start = _parse_iso_date(body.get("start_date"), "start_date")
    end = _parse_iso_date(body.get("end_date"), "end_date")
    if start and end and start > end:
        raise ValueError("start_date must be on or before end_date")

    return {
        "enabled": enabled,
        "headline": headline,
        "copy": copy,
        "donate_url": donate_url,
        "start_date": start,
        "end_date": end,
    }


def is_active(settings, today):
    """Enabled and inside the (optional, inclusive) date window."""
    if not settings.get("enabled"):
        return False
    today_iso = today.isoformat() if isinstance(today, date) else str(today)
    start = settings.get("start_date")
    end = settings.get("end_date")
    if start and today_iso < start:
        return False
    if end and today_iso > end:
        return False
    return True


# --- percentage -------------------------------------------------------------

def parse_percentage(payload):
    """``{"percentage": n}`` → int clamped to 0–100, else None."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("percentage")
    if isinstance(raw, bool):
        return None
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


def fetch_percentage(session_get=http_requests.get, now=time.time, cache=_PCT_CACHE):
    """Live percentage from wyxr.org, cached for CACHE_TTL_SEC.

    Any failure (timeout, non-JSON, unexpected shape) returns the last good
    value rather than blanking the banner; None only if nothing has ever been
    fetched successfully."""
    current = now()
    if cache["value"] is not None and current - cache["fetched_at"] < CACHE_TTL_SEC:
        return cache["value"]
    try:
        resp = session_get(GOAL_URL, timeout=FETCH_TIMEOUT_SEC,
                           headers={"Accept": "application/json"})
        resp.raise_for_status()
        pct = parse_percentage(resp.json())
    except Exception as exc:  # noqa: BLE001 — any failure falls back to last-good
        log.warning("pledge goal fetch failed: %s", exc)
        pct = None
    if pct is None:
        return cache["value"]
    cache["value"] = pct
    cache["fetched_at"] = current
    return pct


# --- payloads ----------------------------------------------------------------

def public_payload(settings, percentage, today):
    if not is_active(settings, today):
        return {"active": False}
    return {
        "active": True,
        "headline": settings["headline"],
        "copy": settings["copy"],
        "donate_url": settings["donate_url"],
        "percentage": percentage,
        "goal_url": GOAL_URL,
    }


def admin_payload(settings, percentage, today):
    payload = dict(settings)
    payload["percentage"] = percentage
    payload["active"] = is_active(settings, today)
    payload["goal_url"] = GOAL_URL
    return payload
