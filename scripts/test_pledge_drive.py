#!/usr/bin/env python3
"""Regression tests for the pledge-drive banner logic (backend/pledge_drive.py).

Offline — no database, no network. ``fetch_percentage`` takes an injected
``session_get`` and clock, so the wyxr.org thermometer endpoint is never hit.

What these protect:
  * the date window — an off-by-one here shows a fund-drive banner a day late
    or leaves it up a day after the drive ends;
  * the percentage parser — the value comes from a third-party WordPress
    endpoint and is rendered into a CSS width, so it must be a clamped int;
  * the last-good fallback — a wyxr.org hiccup must not blank the meter;
  * settings validation — the admin body is the only writer of the blob the
    public homepage renders, so http:// links and oversized text stop here.
"""

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# pledge_drive imports backend.db, which needs a DATABASE_URL at import time
# only if something calls it — but keep the module import self-contained.
os.environ.setdefault("DATABASE_URL", "postgresql://unused:unused@localhost/unused")

from backend import pledge_drive as pd  # noqa: E402

FAILURES = []
CHECKS = [0]


def check(label, actual, expected):
    CHECKS[0] += 1
    if actual != expected:
        FAILURES.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


def check_raises(label, fn, needle):
    CHECKS[0] += 1
    try:
        fn()
    except ValueError as exc:
        if needle not in str(exc):
            FAILURES.append(f"{label}\n    ValueError raised but message {str(exc)!r} lacks {needle!r}")
        return
    FAILURES.append(f"{label}\n    expected ValueError containing {needle!r}, nothing raised")


def settings(**over):
    s = dict(pd.DEFAULTS)
    s.update(over)
    return s


# --- is_active ---------------------------------------------------------------

def test_active_window():
    today = date(2026, 10, 15)
    check("disabled is never active", pd.is_active(settings(enabled=False), today), False)
    check("enabled, no dates → active", pd.is_active(settings(enabled=True), today), True)
    check("start only, in the past", pd.is_active(settings(enabled=True, start_date="2026-10-01"), today), True)
    check("start only, in the future", pd.is_active(settings(enabled=True, start_date="2026-10-16"), today), False)
    check("start == today is inclusive", pd.is_active(settings(enabled=True, start_date="2026-10-15"), today), True)
    check("end only, in the future", pd.is_active(settings(enabled=True, end_date="2026-10-31"), today), True)
    check("end only, in the past", pd.is_active(settings(enabled=True, end_date="2026-10-14"), today), False)
    check("end == today is inclusive", pd.is_active(settings(enabled=True, end_date="2026-10-15"), today), True)
    check("inside both", pd.is_active(settings(enabled=True, start_date="2026-10-01", end_date="2026-10-31"), today), True)
    check("year boundary: Dec drive still active on Dec 31",
          pd.is_active(settings(enabled=True, start_date="2026-12-01", end_date="2026-12-31"), date(2026, 12, 31)), True)
    check("year boundary: not active on Jan 1",
          pd.is_active(settings(enabled=True, start_date="2026-12-01", end_date="2026-12-31"), date(2027, 1, 1)), False)


# --- parse_percentage ---------------------------------------------------------

def test_parse_percentage():
    check("int passes through", pd.parse_percentage({"percentage": 42}), 42)
    check("numeric string coerces", pd.parse_percentage({"percentage": "42"}), 42)
    check("float truncates", pd.parse_percentage({"percentage": 42.9}), 42)
    check("over 100 clamps", pd.parse_percentage({"percentage": 150}), 100)
    check("negative clamps to 0", pd.parse_percentage({"percentage": -3}), 0)
    check("zero is a real value, not None", pd.parse_percentage({"percentage": 0}), 0)
    check("missing key → None", pd.parse_percentage({}), None)
    check("non-numeric → None", pd.parse_percentage({"percentage": "lots"}), None)
    check("bool is not a percentage", pd.parse_percentage({"percentage": True}), None)
    check("list payload → None", pd.parse_percentage([5]), None)
    check("None payload → None", pd.parse_percentage(None), None)


# --- fetch_percentage ---------------------------------------------------------

class _Resp:
    def __init__(self, payload=None, status=200, raise_json=False):
        self._payload = payload
        self.status_code = status
        self._raise_json = raise_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


def test_fetch_percentage():
    calls = []
    clock = [1000.0]

    def make_get(resp_or_exc):
        def _get(url, **kwargs):
            calls.append((url, kwargs.get("timeout")))
            if isinstance(resp_or_exc, Exception):
                raise resp_or_exc
            return resp_or_exc
        return _get

    cache = {"value": None, "fetched_at": 0.0}
    now = lambda: clock[0]  # noqa: E731

    got = pd.fetch_percentage(make_get(_Resp({"percentage": 5})), now, cache)
    check("first fetch returns the live value", got, 5)
    check("fetch hits the public thermometer URL", calls[-1][0], pd.GOAL_URL)
    check("fetch has an explicit timeout", calls[-1][1], pd.FETCH_TIMEOUT_SEC)
    check("value cached", cache["value"], 5)

    n_calls = len(calls)
    clock[0] += 10
    got = pd.fetch_percentage(make_get(_Resp({"percentage": 99})), now, cache)
    check("inside TTL returns cached value", got, 5)
    check("inside TTL does not call out", len(calls), n_calls)

    clock[0] += pd.CACHE_TTL_SEC
    got = pd.fetch_percentage(make_get(_Resp({"percentage": 7})), now, cache)
    check("after TTL refetches", got, 7)

    clock[0] += pd.CACHE_TTL_SEC
    got = pd.fetch_percentage(make_get(RuntimeError("timeout")), now, cache)
    check("exception → last good value", got, 7)

    clock[0] += pd.CACHE_TTL_SEC
    got = pd.fetch_percentage(make_get(_Resp(status=503)), now, cache)
    check("HTTP error → last good value", got, 7)

    clock[0] += pd.CACHE_TTL_SEC
    got = pd.fetch_percentage(make_get(_Resp(raise_json=True)), now, cache)
    check("non-JSON body → last good value", got, 7)

    clock[0] += pd.CACHE_TTL_SEC
    got = pd.fetch_percentage(make_get(_Resp({"percentage": "n/a"})), now, cache)
    check("unparseable payload → last good value", got, 7)

    cold = {"value": None, "fetched_at": 0.0}
    got = pd.fetch_percentage(make_get(RuntimeError("down")), now, cold)
    check("cold cache + failure → None", got, None)
    check("failure never poisons the cache with a timestamp", cold["fetched_at"], 0.0)


# --- validate_settings --------------------------------------------------------

def test_validate_settings():
    out = pd.validate_settings({
        "enabled": True, "headline": "  Fall Drive  ", "copy": "Give now",
        "donate_url": "https://wyxr.org/donate", "start_date": "2026-10-01",
        "end_date": "2026-10-31", "bogus": "dropped",
    })
    check("happy path", out, {
        "enabled": True, "headline": "Fall Drive", "copy": "Give now",
        "donate_url": "https://wyxr.org/donate",
        "start_date": "2026-10-01", "end_date": "2026-10-31",
    })
    check("unknown keys dropped", "bogus" in out, False)

    out = pd.validate_settings({})
    check("empty body → defaults", out, dict(pd.DEFAULTS))

    check("enabled string 'true' coerces", pd.validate_settings({"enabled": "true"})["enabled"], True)
    check("enabled string 'false' coerces", pd.validate_settings({"enabled": "false"})["enabled"], False)
    check("enabled 0 coerces", pd.validate_settings({"enabled": 0})["enabled"], False)
    check("blank headline falls back to default",
          pd.validate_settings({"headline": "   "})["headline"], pd.DEFAULTS["headline"])
    check("blank donate_url falls back to wyxr.org",
          pd.validate_settings({"donate_url": ""})["donate_url"], pd.DEFAULT_DONATE_URL)
    check("empty-string dates become null",
          pd.validate_settings({"start_date": "", "end_date": ""})["start_date"], None)

    check_raises("http:// rejected", lambda: pd.validate_settings({"donate_url": "http://wyxr.org"}), "https://")
    check_raises("javascript: rejected", lambda: pd.validate_settings({"donate_url": "javascript:alert(1)"}), "https://")
    check_raises("headline too long", lambda: pd.validate_settings({"headline": "x" * 81}), "80")
    check_raises("copy too long", lambda: pd.validate_settings({"copy": "x" * 201}), "200")
    check_raises("start after end", lambda: pd.validate_settings(
        {"start_date": "2026-11-01", "end_date": "2026-10-01"}), "on or before")
    check_raises("malformed date", lambda: pd.validate_settings({"start_date": "10/01/2026"}), "YYYY-MM-DD")
    check_raises("non-string date", lambda: pd.validate_settings({"end_date": 20261001}), "YYYY-MM-DD")
    check_raises("non-object body", lambda: pd.validate_settings(["enabled"]), "JSON object")
    check_raises("null body", lambda: pd.validate_settings(None), "JSON object")


# --- payloads -----------------------------------------------------------------

def test_payloads():
    today = date(2026, 10, 15)
    inactive = pd.public_payload(settings(enabled=False), 42, today)
    check("inactive public payload is minimal", inactive, {"active": False})

    active = pd.public_payload(settings(enabled=True, copy="Go!"), 42, today)
    check("active public payload", active, {
        "active": True, "headline": "WYXR Fund Drive", "copy": "Go!",
        "donate_url": "https://wyxr.org", "percentage": 42, "goal_url": pd.GOAL_URL,
    })
    check("percentage None survives to the client (meter hidden, banner shown)",
          pd.public_payload(settings(enabled=True), None, today)["percentage"], None)

    admin = pd.admin_payload(settings(enabled=True, end_date="2026-10-01"), 42, today)
    check("admin payload reports active=False when past end", admin["active"], False)
    check("admin payload keeps enabled flag", admin["enabled"], True)
    check("admin payload carries percentage", admin["percentage"], 42)


# --- settings blob round-trip (DB stubbed) ------------------------------------

def test_load_settings_tolerates_bad_json():
    store = {}
    pd.get_admin_setting = lambda key, default=None: store.get(key, default)
    pd.set_admin_setting = lambda key, value: store.__setitem__(key, value)

    check("missing row → defaults", pd.load_settings(), dict(pd.DEFAULTS))
    store[pd.SETTING_KEY] = "{not json"
    check("malformed JSON → defaults", pd.load_settings(), dict(pd.DEFAULTS))
    store[pd.SETTING_KEY] = '["a list"]'
    check("non-object JSON → defaults", pd.load_settings(), dict(pd.DEFAULTS))

    pd.save_settings(settings(enabled=True, headline="Round trip"))
    loaded = pd.load_settings()
    check("save/load round-trips", loaded["headline"], "Round trip")
    check("save/load keeps enabled", loaded["enabled"], True)
    store[pd.SETTING_KEY] = '{"enabled": true, "unknown": 1}'
    loaded = pd.load_settings()
    check("unknown stored keys dropped on load", "unknown" in loaded, False)
    check("missing stored keys filled from defaults", loaded["donate_url"], pd.DEFAULT_DONATE_URL)


def main():
    print("Testing pledge-drive banner logic...\n")
    test_active_window()
    test_parse_percentage()
    test_fetch_percentage()
    test_validate_settings()
    test_payloads()
    test_load_settings_tolerates_bad_json()

    if FAILURES:
        print(f"❌ {len(FAILURES)} of {CHECKS[0]} checks failed:\n")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"✅ All {CHECKS[0]} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
