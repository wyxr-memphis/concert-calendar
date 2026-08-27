#!/usr/bin/env python3
"""Turn a short-lived Graph API token into the two values the pipeline needs.

Run this on your own machine. Nothing it prints leaves that terminal, and the
app secret is never written to output.

    export IG_APP_ID=...          # App settings -> Basic -> App ID
    export IG_APP_SECRET=...      # App settings -> Basic -> App Secret ("Show")
    export IG_SHORT_TOKEN=...     # Graph API Explorer -> Generate Access Token
    python scripts/instagram_setup_helper.py

It does three things the Graph API Explorer makes you do by hand:

  1. Exchanges the ~1 hour Explorer token for a long-lived (60-day) one.
  2. Lists the Facebook Pages the token can see.
  3. Resolves each Page's linked Instagram Business account.

Then prints the export lines for IG_ACCESS_TOKEN and IG_BUSINESS_ACCOUNT_ID.

The token is masked unless you pass --show-token. Reveal it only when you are
about to paste it into Render or GitHub Secrets, and don't paste that output
into a chat or an issue — a long-lived token is a 60-day credential.
"""

import argparse
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.http_utils import get_with_retry  # noqa: E402

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def _mask(token: str) -> str:
    """Enough of the token to tell two apart, not enough to use."""
    return f"{token[:6]}...{token[-4:]} ({len(token)} chars)" if len(token) > 12 else "***"


def _scrub(text: str, *secrets: str) -> str:
    """Strip credentials out of anything we print.

    requests puts the full request URL in its exception messages, and these
    requests carry both the app secret and the token in the query string.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<REDACTED>")
    return text


def _get(url: str, params: dict, *secrets: str, timeout: int = 20):
    """GET with retry. Returns (payload, error_message)."""
    try:
        resp = get_with_retry(url, params=params, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        return None, f"could not reach {GRAPH_BASE}: {_scrub(str(exc), *secrets)}"

    payload = resp.json() if resp.content else {}
    if resp.status_code != 200:
        err = (payload or {}).get("error") or {}
        detail = err.get("message") or f"HTTP {resp.status_code}"
        return None, _scrub(str(detail), *secrets)
    return payload, None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Exchange a short-lived Instagram token and find the account id.",
    )
    ap.add_argument(
        "--show-token",
        action="store_true",
        help="Print the long-lived token in full (default: masked)",
    )
    args = ap.parse_args()

    app_id = os.environ.get("IG_APP_ID", "").strip()
    app_secret = os.environ.get("IG_APP_SECRET", "").strip()
    short_token = os.environ.get("IG_SHORT_TOKEN", "").strip()

    missing = [
        name
        for name, value in (
            ("IG_APP_ID", app_id),
            ("IG_APP_SECRET", app_secret),
            ("IG_SHORT_TOKEN", short_token),
        )
        if not value
    ]
    if missing:
        print(f"Missing: {', '.join(missing)}", file=sys.stderr)
        print("\nSee this script's docstring for where each one comes from.", file=sys.stderr)
        return 2

    secrets = (app_secret, short_token)

    print("Instagram setup helper")
    print("=" * 60)

    print("\n[1/3] Exchanging the short-lived token for a 60-day one ...")
    payload, err = _get(
        f"{GRAPH_BASE}/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        *secrets,
    )
    if err:
        print(f"  FAIL  {err}")
        print("\n        A short-lived token expires about an hour after it is")
        print("        generated. If that is the problem, generate a fresh one in")
        print("        the Graph API Explorer and re-run.")
        return 1

    long_token = payload.get("access_token", "")
    if not long_token:
        print("  FAIL  no access_token in the response")
        return 1
    expires = payload.get("expires_in")
    print(f"  OK    got a long-lived token: {_mask(long_token)}")
    if expires:
        print(f"        expires in {int(expires) // 86400} days")

    print("\n[2/3] Listing Facebook Pages this token can see ...")
    payload, err = _get(
        f"{GRAPH_BASE}/me/accounts",
        {"fields": "id,name", "access_token": long_token},
        long_token,
        *secrets,
    )
    if err:
        print(f"  FAIL  {err}")
        print("\n        The token may be missing pages_show_list. Re-generate it")
        print("        in the Explorer with instagram_basic, pages_show_list and")
        print("        pages_read_engagement ticked.")
        return 1

    pages = payload.get("data") or []
    if not pages:
        print("  FAIL  no Pages returned")
        print("\n        The Facebook account behind this token does not manage any")
        print("        Page, or the app was not granted access to one.")
        return 1
    for page in pages:
        print(f"  OK    {page.get('name')} (id {page.get('id')})")

    print("\n[3/3] Resolving each Page's linked Instagram Business account ...")
    found = []
    for page in pages:
        page_id = page.get("id")
        payload, err = _get(
            f"{GRAPH_BASE}/{page_id}",
            {"fields": "instagram_business_account{id,username}", "access_token": long_token},
            long_token,
            *secrets,
        )
        if err:
            print(f"  WARN  {page.get('name')}: {err}")
            continue
        iba = payload.get("instagram_business_account")
        if not iba:
            print(f"  --    {page.get('name')}: no Instagram account linked")
            continue
        print(f"  OK    {page.get('name')} -> @{iba.get('username')} (id {iba['id']})")
        found.append(iba)

    if not found:
        print("\n  FAIL  no Page has a linked Instagram Business account.")
        print("\n        Either the WYXR Instagram is still a personal account, or")
        print("        it is not linked to the Page. Both are fixed in the Instagram")
        print("        app under Settings -> Account type and tools.")
        return 1

    account = found[0]
    if len(found) > 1:
        print(f"\n        More than one found — using @{account.get('username')}.")
        print("        If that is the wrong one, use the id you want instead.")

    print("\n" + "=" * 60)
    print("Set these two, then run the access check:\n")

    # The account id is not a credential — always print it in full.
    print(f"  export IG_BUSINESS_ACCOUNT_ID='{account['id']}'")

    if args.show_token:
        print(f"  export IG_ACCESS_TOKEN='{long_token}'")
    else:
        # Deliberately NOT a copy-pasteable export line. Printing the masked
        # value as one invites pasting "EAAWv8...ZDZD (216 chars)" as the token,
        # which fails later as an opaque auth error rather than an obvious one.
        print("  export IG_ACCESS_TOKEN=...")
        print(f"\n  The token is {_mask(long_token)} — masked, so the line above is")
        print("  a placeholder, not something to paste. Re-run with --show-token")
        print("  to print the real export line.")

    print("\n  python scripts/check_instagram_access.py --username <venue-handle>")

    if args.show_token:
        print("\n  That token is a 60-day credential. It goes in Render env vars and")
        print("  GitHub Secrets — not into a chat, an issue, or a commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
