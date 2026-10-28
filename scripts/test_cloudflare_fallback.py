#!/usr/bin/env python3
"""Regression tests for the Cloudflare proxy fallback and the Eventim queue poll.

Four venues' sites answer 403 to every GitHub Actions build because Cloudflare
scores the runner's IP as a bot (dev/venues-and-scrapers.md). http_utils now
retries such a response once through ScraperAPI, and the Eventim fetcher polls
through Cloudflare's waiting room instead of giving up on the first queue page.
These tests pin the boundaries that matter:

- only a response that looks like a Cloudflare block is proxied — an origin
  403, a 406, a healthy 200 never spend a credit;
- with no SCRAPERAPI_KEY nothing changes at all;
- the per-run budget holds, and a proxy error returns the direct response;
- the proxy request forwards our own headers (Pontotoc's WAF needs our UA);
- a venue flagged `requires_proxy` is reported as skipped, not failed, when
  the key is unset;
- the Eventim poll stops when admitted and when the budget is spent, and
  honours the queue page's Refresh interval.

Runs offline — no network, no API key, no database.

Usage:
    python scripts/test_cloudflare_fallback.py
"""
import os
import sys
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import requests  # noqa: E402

import src.http_utils as hu  # noqa: E402
from src.sources import venue_scrapers as vs  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def resp(status=200, headers=None, text=""):
    r = requests.Response()
    r.status_code = status
    r.headers.update(headers or {})
    r._content = text.encode("utf-8")
    r.encoding = "utf-8"
    return r


CF_CHALLENGE = '<!DOCTYPE html><html><head><title>Just a moment...</title></head></html>'


# ---------------------------------------------------------------------------
def test_block_detection():
    print("\nwhat counts as a Cloudflare block")
    check("403 from a cloudflare edge", hu.is_cloudflare_block(resp(403, {"server": "cloudflare"})))
    check("cf-mitigated header", hu.is_cloudflare_block(resp(403, {"cf-mitigated": "challenge"})))
    check("challenge page body, no headers", hu.is_cloudflare_block(resp(503, text=CF_CHALLENGE)))
    check("origin 403 (nginx) is NOT a block", not hu.is_cloudflare_block(resp(403, {"server": "nginx"})))
    check("Landers' 406 is NOT a block", not hu.is_cloudflare_block(resp(406)))
    check("a 200 behind cloudflare is NOT a block",
          not hu.is_cloudflare_block(resp(200, {"server": "cloudflare"}, CF_CHALLENGE)))
    check("a 500 is NOT a block", not hu.is_cloudflare_block(resp(500, {"server": "cloudflare"})))


def test_no_key_means_no_change():
    print("\nwithout SCRAPERAPI_KEY the blocked response is returned as-is")
    blocked = resp(403, {"server": "cloudflare"})
    with mock.patch.object(hu, "SCRAPERAPI_KEY", ""), \
         mock.patch.object(hu._session, "get", return_value=blocked), \
         mock.patch.object(hu, "fetch_via_proxy") as proxy:
        out = hu.get_with_retry("https://blocked.example/wp-json/x", headers={"User-Agent": "u"})
    check("direct response returned", out is blocked)
    check("proxy never called", proxy.call_count == 0)
    check("proxy_configured() is False", not hu.proxy_configured())


def test_fallback_on_block():
    print("\na Cloudflare block is retried once through the proxy")
    blocked = resp(403, {"server": "cloudflare"})
    proxied = resp(200, text='{"events": []}')
    with mock.patch.object(hu, "SCRAPERAPI_KEY", "k"), \
         mock.patch.object(hu, "_proxy_used", 0), \
         mock.patch.object(hu._session, "get", return_value=blocked), \
         mock.patch.object(hu, "fetch_via_proxy", return_value=proxied) as proxy:
        out = hu.get_with_retry("https://blocked.example/wp-json/x",
                                headers={"User-Agent": "u"}, params={"a": 1}, timeout=15)
        used = hu.proxy_fetches_this_run()  # read before the patch restores the counter
    check("proxied response returned", out is proxied)
    check("proxy called once", proxy.call_count == 1)
    kw = proxy.call_args.kwargs
    check("headers forwarded", kw.get("headers") == {"User-Agent": "u"}, str(kw))
    check("params forwarded", kw.get("params") == {"a": 1}, str(kw))
    check("one budget slot used", used == 1, str(used))


def test_healthy_and_origin_errors_are_not_proxied():
    print("\nhealthy pages and origin errors never spend a credit")
    for label, r in (("200", resp(200, text="ok")),
                     ("origin 403", resp(403, {"server": "Apache"})),
                     ("406", resp(406)),
                     ("origin 404", resp(404, {"server": "cloudflare"}))):
        with mock.patch.object(hu, "SCRAPERAPI_KEY", "k"), \
             mock.patch.object(hu._session, "get", return_value=r), \
             mock.patch.object(hu, "fetch_via_proxy") as proxy:
            out = hu.get_with_retry("https://x.example/")
        check(f"{label}: direct response, no proxy call", out is r and proxy.call_count == 0)


def test_budget_and_proxy_error():
    print("\nbudget exhaustion and proxy failure fall back to the direct response")
    blocked = resp(403, {"server": "cloudflare"})
    with mock.patch.object(hu, "SCRAPERAPI_KEY", "k"), \
         mock.patch.object(hu, "_proxy_used", hu.PROXY_BUDGET_PER_RUN), \
         mock.patch.object(hu._session, "get", return_value=blocked), \
         mock.patch.object(hu, "fetch_via_proxy") as proxy:
        out = hu.get_with_retry("https://x.example/")
    check("budget spent: direct response", out is blocked)
    check("budget spent: proxy not called", proxy.call_count == 0)

    with mock.patch.object(hu, "SCRAPERAPI_KEY", "k"), \
         mock.patch.object(hu, "_proxy_used", 0), \
         mock.patch.object(hu._session, "get", return_value=blocked), \
         mock.patch.object(hu, "fetch_via_proxy", side_effect=requests.exceptions.ConnectTimeout("t")):
        out = hu.get_with_retry("https://x.example/")
    check("proxy error: direct response", out is blocked)

    with mock.patch.object(hu, "SCRAPERAPI_KEY", "k"), \
         mock.patch.object(hu, "_proxy_used", 0), \
         mock.patch.object(hu._session, "get", return_value=blocked), \
         mock.patch.object(hu, "fetch_via_proxy") as proxy:
        hu.get_with_retry("https://x.example/", cloudflare_fallback=False)
    check("cloudflare_fallback=False opts out", proxy.call_count == 0)


def test_proxy_request_shape():
    print("\nthe ScraperAPI request carries the key, the full target URL and our headers")
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(url=url, params=params, headers=headers, timeout=timeout)
        return resp(200, text="ok")

    with mock.patch.object(hu, "SCRAPERAPI_KEY", "secret"), \
         mock.patch.object(hu.requests, "get", fake_get):
        hu.fetch_via_proxy("https://hotelpontotoc.com/wp-json/tribe/events/v1/events",
                           params={"per_page": 50, "page": 1},
                           headers={"User-Agent": "WYXR-Concert-Calendar/1.0", "Accept": "application/json"},
                           timeout=15)
    check("endpoint", captured["url"] == hu._SCRAPERAPI_ENDPOINT, captured["url"])
    check("api_key", captured["params"].get("api_key") == "secret")
    check("target url includes the query string",
          captured["params"].get("url") == "https://hotelpontotoc.com/wp-json/tribe/events/v1/events?per_page=50&page=1",
          captured["params"].get("url"))
    check("keep_headers=true when headers given", captured["params"].get("keep_headers") == "true")
    check("our UA is sent to the proxy", captured["headers"].get("User-Agent") == "WYXR-Concert-Calendar/1.0")
    check("client timeout raised to the proxy minimum", captured["timeout"] >= hu._PROXY_TIMEOUT, str(captured["timeout"]))

    captured.clear()
    with mock.patch.object(hu, "SCRAPERAPI_KEY", "secret"), \
         mock.patch.object(hu.requests, "get", fake_get):
        hu.fetch_via_proxy("https://x.example/")
    check("no keep_headers without headers", "keep_headers" not in captured["params"])


def test_requires_proxy_skip():
    print("\na requires_proxy venue is reported as skipped when the key is unset")
    fake_venues = {
        "needs-proxy": {"name": "Hotel Pontotoc", "scraper": "tribe_events",
                        "calendar_url": "https://hotelpontotoc.com/events/", "requires_proxy": True},
        "plain": {"name": "Plain Venue", "scraper": "generic", "calendar_url": "https://plain.example/"},
        "manual": {"name": "Manual Venue", "scraper": "manual_only", "calendar_url": None},
    }
    scraped = []

    def fake_scrape(key, info):
        scraped.append(key)
        return vs.SourceResult(source_name=f"Venue: {info['name']}")

    with mock.patch.object(vs, "VENUES", fake_venues), \
         mock.patch.object(vs, "proxy_configured", return_value=False), \
         mock.patch.object(vs, "_scrape_venue", fake_scrape):
        results = vs.fetch_individual()
    names = {r.source_name: r for r in results}
    check("proxy venue not scraped", "needs-proxy" not in scraped, str(scraped))
    check("plain venue scraped", scraped == ["plain"], str(scraped))
    check("proxy venue still has a build-log row", "Venue: Hotel Pontotoc" in names)
    pont = names.get("Venue: Hotel Pontotoc")
    check("…marked success (skipped, not failed)", pont is not None and pont.success)
    check("…with a reason naming the key",
          pont is not None and "SCRAPERAPI_KEY" in (pont.error_message or ""), str(pont and pont.error_message))

    scraped.clear()
    with mock.patch.object(vs, "VENUES", fake_venues), \
         mock.patch.object(vs, "proxy_configured", return_value=True), \
         mock.patch.object(vs, "_scrape_venue", fake_scrape):
        vs.fetch_individual()
    check("with a key the proxy venue is scraped", sorted(scraped) == ["needs-proxy", "plain"], str(scraped))


def test_eventim_queue_poll():
    print("\nEventim: polling through the waiting room")
    queue = resp(200, {"Refresh": "5"}, "<h1>You're in line!</h1>")
    admitted = resp(200, text='<div class="search-event"></div>')
    sleeps = []

    class FakeSession:
        def __init__(self, replies):
            self.replies = list(replies)
            self.calls = 0

        def get(self, url, timeout=None):
            self.calls += 1
            return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    s = FakeSession([queue, queue, admitted])
    polls = {"left": vs._EVENTIM_QUEUE_POLLS}
    with mock.patch.object(vs.time, "sleep", sleeps.append):
        out = vs._eventim_get(s, "https://wl.eventim.us/X", polls)
    check("admitted page returned", out is admitted)
    check("three requests", s.calls == 3, str(s.calls))
    check("two sleeps using the Refresh interval", sleeps == [5, 5], str(sleeps))
    check("two polls spent", polls["left"] == vs._EVENTIM_QUEUE_POLLS - 2, str(polls))

    s = FakeSession([queue])
    polls = {"left": 2}
    sleeps.clear()
    with mock.patch.object(vs.time, "sleep", sleeps.append):
        out = vs._eventim_get(s, "https://wl.eventim.us/X", polls)
    check("budget spent: queue page returned", vs._EVENTIM_QUEUE_MARKER in out.text)
    check("budget spent: stopped after 2 polls", s.calls == 3 and polls["left"] == 0, f"{s.calls} {polls}")

    no_refresh = resp(200, text="You're in line")
    s = FakeSession([no_refresh, admitted])
    sleeps.clear()
    with mock.patch.object(vs.time, "sleep", sleeps.append):
        vs._eventim_get(s, "https://wl.eventim.us/X", {"left": 3})
    check("default interval without a Refresh header", sleeps == [vs._EVENTIM_QUEUE_INTERVAL], str(sleeps))

    huge = resp(200, {"Refresh": "600; url=/"}, "You're in line")
    s = FakeSession([huge, admitted])
    sleeps.clear()
    with mock.patch.object(vs.time, "sleep", sleeps.append):
        vs._eventim_get(s, "https://wl.eventim.us/X", {"left": 3})
    check("Refresh interval is capped", sleeps == [vs._EVENTIM_QUEUE_MAX_WAIT], str(sleeps))

    s = FakeSession([admitted])
    sleeps.clear()
    with mock.patch.object(vs.time, "sleep", sleeps.append):
        vs._eventim_get(s, "https://wl.eventim.us/X", {"left": 0})
    check("no budget, admitted first try: one request, no sleep", s.calls == 1 and sleeps == [])


def main():
    print("Cloudflare fallback + Eventim queue tests (offline)")
    for fn in (
        test_block_detection,
        test_no_key_means_no_change,
        test_fallback_on_block,
        test_healthy_and_origin_errors_are_not_proxied,
        test_budget_and_proxy_error,
        test_proxy_request_shape,
        test_requires_proxy_skip,
        test_eventim_queue_poll,
    ):
        fn()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("All Cloudflare fallback tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
