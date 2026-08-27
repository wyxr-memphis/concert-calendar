#!/usr/bin/env python3
"""Probe whether this app can read a venue's Instagram posts via business_discovery.

Read-only. Spends no Anthropic tokens — it never calls Vision. Run this before
wiring up the ingestion pipeline, and again whenever the token is rotated.

    export IG_ACCESS_TOKEN=...          # long-lived (60-day) user token
    export IG_BUSINESS_ACCOUNT_ID=...   # 17841... — WYXR's own IG business account
    python scripts/check_instagram_access.py --username bsidememphis

What it checks, in order — each step's failure tells you which piece of the
Meta setup is missing:

  1. Both env vars are set.
  2. The token authenticates and IG_BUSINESS_ACCOUNT_ID resolves to an account
     (proves: token valid, not expired, account is Business/Creator, and the
     app has instagram_basic).
  3. business_discovery returns posts for --username (proves: the target is a
     public Business/Creator account and the app is allowed to read other
     businesses' public data — the piece most likely to need App Review).

Exits 0 when unconfigured, so it is safe to call from a pipeline. Exits 1 on a
real failure, 2 on bad usage.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.http_utils import get_with_retry  # noqa: E402

# Pinned rather than floating: a Graph API version reaching end-of-life fails
# loudly here instead of silently changing response shapes in the nightly job.
GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Response headers Meta uses to report how much of the rate-limit budget is
# spent. Worth printing: REVIEW.md quotes "~200 calls/hour" from documentation,
# and this is the number that actually applies to this app.
_USAGE_HEADERS = (
    "x-app-usage",
    "x-business-use-case-usage",
    "x-ad-account-usage",
)

MEDIA_FIELDS = "id,caption,media_type,media_url,permalink,timestamp"


def _fail(msg: str, hint: str = "") -> None:
    print(f"\n  FAIL  {msg}")
    if hint:
        for line in hint.strip().splitlines():
            print(f"        {line}")


def _print_usage_headers(resp) -> None:
    found = {h: resp.headers[h] for h in _USAGE_HEADERS if h in resp.headers}
    if not found:
        return
    print("\n  Rate-limit budget reported by Meta:")
    for header, raw in found.items():
        try:
            # These arrive as JSON; pretty-print so percentages are readable.
            print(f"    {header}: {json.dumps(json.loads(raw), separators=(',', ' '))}")
        except (ValueError, TypeError):
            print(f"    {header}: {raw}")


def _scrub(text: str, token: str) -> str:
    """Remove the access token from anything we are about to print.

    requests puts the full request URL — query string included — into its
    exception messages, so an unhandled network error would print the token to
    the terminal and into whatever log or chat the output gets pasted into.
    Same rule as the Slack error handling in backend/app.py: the operator gets
    a usable message, the secret does not travel with it.
    """
    return text.replace(token, "<IG_ACCESS_TOKEN>") if token else text


def _request(url: str, params: dict, token: str, timeout: int):
    """GET with retry, turning transport failures into a clean message.

    Returns the response, or None after printing why the call never completed.
    """
    try:
        return get_with_retry(url, params=params, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        _fail(
            f"could not reach {GRAPH_BASE}",
            f"""
{_scrub(str(exc), token)}

This is a network problem, not an authentication one — the request never
reached Meta. Check your connection, any proxy or VPN, and whether
graph.facebook.com is reachable from this machine:
  curl -sS -o /dev/null -w '%{{http_code}}\\n' {GRAPH_BASE}/me
""",
        )
        return None


def _graph_error(payload: dict) -> str:
    """Human-readable line from a Graph API error body."""
    err = (payload or {}).get("error") or {}
    bits = [err.get("message") or "unknown error"]
    for key in ("type", "code", "error_subcode"):
        if err.get(key):
            bits.append(f"{key}={err[key]}")
    return " | ".join(str(b) for b in bits)


def check_token(token: str, account_id: str) -> bool:
    """Step 2 — does the token work, and does the account id resolve?"""
    print(f"\n[2/3] Resolving IG_BUSINESS_ACCOUNT_ID {account_id} ...")
    resp = _request(
        f"{GRAPH_BASE}/{account_id}",
        {"fields": "username,name,followers_count", "access_token": token},
        token,
        timeout=15,
    )
    if resp is None:
        return False
    payload = resp.json() if resp.content else {}

    if resp.status_code != 200:
        _fail(
            f"HTTP {resp.status_code}: {_graph_error(payload)}",
            """
Most likely causes, in order:
  - The token expired. A Graph API Explorer token lasts ~1 hour; exchange it
    for a long-lived one (see the plan's Phase 0).
  - IG_BUSINESS_ACCOUNT_ID is wrong. Get it with:
      GET /me/accounts                          -> find the WYXR Page id
      GET /{page-id}?fields=instagram_business_account
  - The WYXR Instagram account is not a Business/Creator account, or is not
    linked to the Facebook Page.
  - The app is missing the instagram_basic permission.
""",
        )
        _print_usage_headers(resp)
        return False

    print(f"  OK    authenticated as @{payload.get('username')} ({payload.get('name')})")
    if payload.get("followers_count") is not None:
        print(f"        {payload['followers_count']} followers")
    _print_usage_headers(resp)
    return True


def check_business_discovery(token: str, account_id: str, username: str, limit: int) -> bool:
    """Step 3 — can we read the target venue's public posts?"""
    print(f"\n[3/3] Reading posts for @{username} via business_discovery ...")
    fields = (
        f"business_discovery.username({username})"
        f"{{followers_count,media_count,media{{{MEDIA_FIELDS}}}}}"
    )
    resp = _request(
        f"{GRAPH_BASE}/{account_id}",
        {"fields": fields, "access_token": token},
        token,
        timeout=20,
    )
    if resp is None:
        return False
    payload = resp.json() if resp.content else {}

    if resp.status_code != 200:
        _fail(
            f"HTTP {resp.status_code}: {_graph_error(payload)}",
            f"""
Most likely causes, in order:
  - @{username} is a personal account. business_discovery only reads public
    Business/Creator accounts — there is no API for personal ones.
  - The handle is wrong. Check it against the venue's profile URL.
  - The app cannot read other businesses' data yet. The app dashboard's
    "Become a Tech Provider" notice points at this: reading another business's
    data can require App Review. If step 2 passed and only this step fails,
    that is the blocker — and it is a Meta process, not a code problem.
""",
        )
        _print_usage_headers(resp)
        return False

    disco = payload.get("business_discovery") or {}
    media = (disco.get("media") or {}).get("data") or []

    print(f"  OK    @{username}: {disco.get('media_count')} posts, "
          f"{disco.get('followers_count')} followers")
    print(f"        business_discovery returned {len(media)} recent post(s)\n")

    if not media:
        print("        No posts came back. The account may have no public posts,")
        print("        or the media edge may be restricted for it.")
        _print_usage_headers(resp)
        return True

    for post in media[:limit]:
        caption = (post.get("caption") or "").replace("\n", " ").strip()
        if len(caption) > 90:
            caption = caption[:87] + "..."
        print(f"        - {post.get('timestamp')}  {post.get('media_type')}")
        print(f"          caption: {caption or '(none)'}")
        # media_url is what the pipeline downloads. Its absence on a post type
        # we expected to ingest is the thing worth catching here.
        print(f"          media_url: {'present' if post.get('media_url') else 'MISSING'}")
        print(f"          {post.get('permalink')}")

    _print_usage_headers(resp)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Probe Instagram business_discovery access for a venue account.",
    )
    ap.add_argument(
        "--username",
        required=True,
        help="Venue Instagram handle to read, without the @ (e.g. bsidememphis)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=5,
        help="How many recent posts to print (default 5)",
    )
    args = ap.parse_args()

    username = args.username.lstrip("@").strip()
    if not username:
        print("--username was empty after stripping '@'", file=sys.stderr)
        return 2

    print("Instagram access check")
    print("=" * 60)

    print("\n[1/3] Checking environment ...")
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    account_id = os.environ.get("IG_BUSINESS_ACCOUNT_ID", "").strip()

    missing = [
        name
        for name, value in (
            ("IG_ACCESS_TOKEN", token),
            ("IG_BUSINESS_ACCOUNT_ID", account_id),
        )
        if not value
    ]
    if missing:
        # Not an error: "not configured yet" is a legitimate state, and the
        # ingestion pipeline ships dark in exactly this condition.
        print(f"  SKIP  not configured — {', '.join(missing)} unset")
        print("\n        Nothing to check. Set both and re-run.")
        return 0

    # Never print the token itself — this output gets pasted into chats.
    print(f"  OK    IG_ACCESS_TOKEN set ({len(token)} chars)")
    print(f"  OK    IG_BUSINESS_ACCOUNT_ID set ({account_id})")

    if not check_token(token, account_id):
        return 1
    if not check_business_discovery(token, account_id, username, args.limit):
        return 1

    print("\n" + "=" * 60)
    print("All checks passed — this app can read @%s's posts." % username)
    return 0


if __name__ == "__main__":
    sys.exit(main())
