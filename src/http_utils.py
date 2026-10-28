"""Shared HTTP client with automatic retry for transient failures.

Uses requests' built-in HTTPAdapter + urllib3 Retry so that a single
timeout or 503 doesn't kill a source for 12+ hours until the next build.
"""

import os
import threading
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Cloudflare fallback: re-fetch a blocked page through a scraping proxy.
#
# Four venues' sites (Hotel Pontotoc, Crosstown Arts, Growlers, Hernando's)
# sit behind Cloudflare rules that score GitHub's runner IPs — and Render's —
# as bots and answer 403 to every build while the identical request works from
# a home connection. Relaying through Render was probed and is dead
# (dev/spec-render-fetch-relay.md). Asking each venue for a WAF allowlist
# needs a human at the venue. So a request that comes back as a Cloudflare
# block is retried once through ScraperAPI, which fetches from residential
# IPs and returns the target's body and status code as-is.
#
# Scope is deliberately narrow: only a response that *looks like a Cloudflare
# block* (403/429/503 from a Cloudflare edge, or a challenge page) is retried,
# so a healthy venue never spends a credit. The free plan is 1,000 credits a
# month and a plain fetch costs one, so a per-build budget keeps a sudden
# site-wide outage from burning the month in a day. With no SCRAPERAPI_KEY the
# blocked response is returned unchanged and behaviour is exactly as before.
# ---------------------------------------------------------------------------
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")
_SCRAPERAPI_ENDPOINT = "https://api.scraperapi.com/"
# ScraperAPI holds a request open while it rotates IPs and retries on its
# side; its docs ask for a client timeout of at least 60s.
_PROXY_TIMEOUT = 70
PROXY_BUDGET_PER_RUN = 40
_proxy_used = 0
_proxy_lock = threading.Lock()
_CF_BLOCK_STATUSES = {403, 429, 503}
_CF_BODY_MARKERS = ("just a moment", "cf-chl", "challenge-platform",
                    "attention required! | cloudflare", "cf_chl_opt")

_RETRY_STRATEGY = Retry(
    total=2,                        # 2 retries → 3 total attempts
    backoff_factor=3,               # wait 3s, then 6s between retries
    status_forcelist=[429, 500, 502, 503],
)

_adapter = HTTPAdapter(max_retries=_RETRY_STRATEGY)


def _make_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", _adapter)
    session.mount("http://", _adapter)
    return session


_session = _make_session()


def proxy_configured() -> bool:
    """True when a Cloudflare-blocked fetch can be retried through the proxy."""
    return bool(SCRAPERAPI_KEY)


def is_cloudflare_block(resp: requests.Response) -> bool:
    """Does this response look like Cloudflare refusing us, not the site?

    A 403 from the origin itself (Landers' 406, a WordPress WAF) is left
    alone — only a Cloudflare edge response or a challenge page qualifies.
    """
    if resp.status_code not in _CF_BLOCK_STATUSES:
        return False
    if resp.headers.get("cf-mitigated"):
        return True
    if "cloudflare" in (resp.headers.get("server") or "").lower():
        return True
    try:
        head = (resp.text or "")[:4000].lower()
    except Exception:
        return False
    return any(marker in head for marker in _CF_BODY_MARKERS)


def _take_proxy_slot() -> bool:
    global _proxy_used
    with _proxy_lock:
        if _proxy_used >= PROXY_BUDGET_PER_RUN:
            return False
        _proxy_used += 1
        return True


def proxy_fetches_this_run() -> int:
    return _proxy_used


def fetch_via_proxy(url: str, params=None, headers=None,
                    timeout: int = _PROXY_TIMEOUT) -> requests.Response:
    """GET `url` through ScraperAPI, forwarding our own headers.

    `keep_headers=true` makes ScraperAPI send our User-Agent instead of its
    own — Hotel Pontotoc's WAF 403s a browser UA on /wp-json/ but allows the
    plain self-identifying one, so the UA that works directly must be the UA
    the proxy presents too. The target's status code and body come back
    unchanged, so callers' raise_for_status()/json()/text work as usual.

    Plain requests.get, not the retrying session: ScraperAPI already retries
    on its side for up to a minute, and a 500 from it means it gave up.
    """
    target = requests.Request("GET", url, params=params).prepare().url
    query = {"api_key": SCRAPERAPI_KEY, "url": target}
    if headers:
        query["keep_headers"] = "true"
    return requests.get(_SCRAPERAPI_ENDPOINT, params=query, headers=headers or {},
                        timeout=max(timeout or 0, _PROXY_TIMEOUT))


def get_with_retry(url: str, cloudflare_fallback: bool = True, **kwargs) -> requests.Response:
    """Drop-in replacement for requests.get() with automatic retry.

    When the response is a Cloudflare block and SCRAPERAPI_KEY is set, the
    same request is made once more through the proxy and that response is
    returned instead. Any other outcome — a healthy page, an origin 403, no
    key, budget spent, proxy error — returns the direct response untouched.
    """
    resp = _session.get(url, **kwargs)
    if not (cloudflare_fallback and proxy_configured() and is_cloudflare_block(resp)):
        return resp

    host = urlsplit(url).netloc
    if not _take_proxy_slot():
        print(f"  [proxy] Cloudflare {resp.status_code} on {host} — "
              f"per-run proxy budget ({PROXY_BUDGET_PER_RUN}) spent, keeping the block")
        return resp
    print(f"  [proxy] Cloudflare {resp.status_code} on {host} — refetching via ScraperAPI")
    try:
        return fetch_via_proxy(url, params=kwargs.get("params"),
                               headers=kwargs.get("headers"),
                               timeout=kwargs.get("timeout"))
    except requests.exceptions.RequestException as e:
        print(f"  [proxy] ScraperAPI request failed for {host}: {str(e)[:80]}")
        return resp


def new_session() -> requests.Session:
    """A private session with the same retry policy as get_with_retry.

    For a source whose pagination depends on a session cookie. The shared
    session's cookie jar is common to every scraper thread, so two venues
    paging the same host at once would share — and clobber — one server-side
    session.
    """
    return _make_session()


# Ticketmaster's Discovery API refuses deep paging beyond 1000 items
# (page * size must stay under it), so there is no point requesting past that.
TICKETMASTER_MAX_ITEMS = 1000


def fetch_ticketmaster_events(url: str, params: dict, timeout: int = 15):
    """Fetch every page of a Ticketmaster Discovery query.

    The callers used to issue a single request with size=50 (per venue) or
    size=100 (city-wide) and no page loop, so any query with more results than
    one page was silently truncated — a busy venue simply lost the tail of its
    six-month window with no error anywhere.

    Returns (events, truncated). `truncated` is True when results remain that
    the API will not serve, so the caller can say so instead of reporting a
    clean run.
    """
    params = dict(params)
    size = int(params.get("size") or 50)
    params["size"] = size

    events = []
    page = 0
    truncated = False

    while True:
        params["page"] = page
        response = get_with_retry(url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        batch = data.get("_embedded", {}).get("events", [])
        events.extend(batch)

        page_info = data.get("page", {}) or {}
        total_pages = page_info.get("totalPages")
        if total_pages is None:
            # No pagination metadata — trust a short page to mean the end.
            if len(batch) < size:
                break
            total_pages = page + 2  # keep going, re-checked next iteration

        page += 1
        if page >= total_pages:
            break
        if not batch:
            # Defensive: an empty page with more claimed would loop forever.
            break
        if page * size >= TICKETMASTER_MAX_ITEMS:
            # More results exist but the API will not page this deep.
            truncated = page < total_pages
            break

    return events, truncated
