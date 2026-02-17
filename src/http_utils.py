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
