"""Shared HTTP client with automatic retry for transient failures.

Uses requests' built-in HTTPAdapter + urllib3 Retry so that a single
timeout or 503 doesn't kill a source for 12+ hours until the next build.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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


def get_with_retry(url: str, **kwargs) -> requests.Response:
    """Drop-in replacement for requests.get() with automatic retry."""
    return _session.get(url, **kwargs)


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
