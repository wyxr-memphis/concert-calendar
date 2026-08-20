#!/usr/bin/env python3
"""Regression tests for Ticketmaster pagination (REVIEW.md 1.8).

Both Ticketmaster callers issued a single request — size=50 per venue,
size=100 city-wide — with no page loop. Any query with more results than one
page was silently truncated: a busy venue lost the tail of its six-month
window and the build reported a clean run.

These tests drive fetch_ticketmaster_events() against a fake Discovery API, so
they also pin the two ways a paging loop goes wrong: never terminating when the
API reports more pages than it serves, and paging past the 1000-item ceiling
the API refuses.

Runs offline — no network, no API key, no database.

Usage:
    python scripts/test_ticketmaster_pagination.py
"""
import math
import os
import sys
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import src.http_utils as http_utils  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def eq(label, got, want):
    check(label, got == want, f"got {got!r}, want {want!r}" if got != want else "")


def fake_api(total, size, with_meta=True):
    """A fake Discovery endpoint serving `total` events in pages of `size`."""
    pages_requested = []

    def _get(url, params=None, timeout=None):
        params = params or {}
        page = int(params.get("page", 0))
        sz = int(params.get("size", size))
        pages_requested.append(page)
        start = page * sz
        batch = [{"name": f"event-{i}"} for i in range(start, min(start + sz, total))]
        body = {"_embedded": {"events": batch}} if batch else {}
        if with_meta:
            body["page"] = {
                "size": sz,
                "totalElements": total,
                "totalPages": max(1, math.ceil(total / sz)),
                "number": page,
            }
        resp = mock.Mock()
        resp.json.return_value = body
        resp.raise_for_status.return_value = None
        return resp

    return _get, pages_requested


def fetch(getter, size):
    with mock.patch.object(http_utils, "get_with_retry", getter):
        return http_utils.fetch_ticketmaster_events("https://example.test", {"size": size})


def test_every_page_is_collected():
    print("\nall pages are collected")
    # 137 at size 50 is the shape that actually bit us: three pages, of which
    # only the first was ever requested.
    for total, size in [(0, 50), (1, 50), (50, 50), (51, 50), (137, 50),
                        (100, 100), (250, 100)]:
        getter, _ = fake_api(total, size)
        events, truncated = fetch(getter, size)
        eq(f"total={total} size={size}", len(events), total)
        check(f"total={total} size={size} not flagged truncated", truncated is False)


def test_no_pagination_metadata():
    print("\nfalls back to short-page detection when metadata is absent")
    for total, size in [(0, 50), (50, 50), (51, 50), (137, 50)]:
        getter, _ = fake_api(total, size, with_meta=False)
        events, _ = fetch(getter, size)
        eq(f"total={total} without page metadata", len(events), total)


def test_deep_paging_ceiling():
    print("\nstops at the API's 1000-item ceiling and says so")
    getter, pages = fake_api(5000, 100)
    events, truncated = fetch(getter, 100)
    eq("collected up to the ceiling", len(events), http_utils.TICKETMASTER_MAX_ITEMS)
    check("truncation is reported", truncated is True)
    check("did not request past the ceiling",
          max(pages) * 100 < http_utils.TICKETMASTER_MAX_ITEMS,
          f"deepest page requested: {max(pages)}")


def test_terminates_when_api_overclaims():
    print("\nterminates when the API claims more pages than it serves")

    def liar(url, params=None, timeout=None):
        resp = mock.Mock()
        resp.json.return_value = {
            "_embedded": {"events": []},
            "page": {"totalPages": 99, "number": int((params or {}).get("page", 0))},
        }
        resp.raise_for_status.return_value = None
        return resp

    with mock.patch.object(http_utils, "get_with_retry", liar):
        events, _ = http_utils.fetch_ticketmaster_events("https://example.test", {"size": 50})
    eq("returns without looping forever", len(events), 0)


def test_caller_params_are_not_mutated():
    print("\nthe caller's params dict is left alone")
    getter, _ = fake_api(10, 50)
    params = {"size": 50, "apikey": "x"}
    with mock.patch.object(http_utils, "get_with_retry", getter):
        http_utils.fetch_ticketmaster_events("https://example.test", params)
    check("no 'page' key leaked into the caller's dict", "page" not in params, str(params))


def main():
    print("Ticketmaster pagination regression tests (offline)")
    for fn in (
        test_every_page_is_collected,
        test_no_pagination_metadata,
        test_deep_paging_ceiling,
        test_terminates_when_api_overclaims,
        test_caller_params_are_not_mutated,
    ):
        fn()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("All Ticketmaster pagination tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
