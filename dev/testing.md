# Testing (`./test_before_push.sh`)

> Tripwires live in `CLAUDE.md`. This file is the detail behind them.

```bash
./test_before_push.sh
# If passed:
git push origin main
```

Runs **15 checks**: env vars, dependencies, DB connection, exposed-key scan, Python syntax, git
status, and ten regression suites. There is no test framework — each suite is a standalone
script following the `scripts/test_*.py` convention, offline except for the DB connection check.

| Suite | Covers |
|---|---|
| `scripts/test_health_check.py` | nightly health-check report parsing |
| `scripts/test_normalization.py` | year rollover, title/venue normalization, strftime |
| `scripts/test_admin_auth.py` | CSRF guard, login throttle, non-ASCII password (no DB needed) |
| `scripts/test_escaping.mjs` | `escAttr`/`safeUrl` vs attack payloads |
| `scripts/test_ticketmaster_pagination.py` | paging, 1000-item ceiling, non-terminating API |
| `scripts/test_ics_feed.py` | ICS DST offsets, RFC 5545 folding/escaping, UID stability |
| `scripts/test_event_page.py` | `/e/<id>` escaping, JSON-LD, price parsing, 404/503 routes |
| `scripts/test_xss_browser.py` | the real page in Chromium against live payloads |
| `scripts/test_deeplink_browser.py` | `#event=` deep links, Back/Forward, injected JSON-LD |
| `scripts/test_security_headers.py` | both CSP variants; the real pages driven under the shipped policy |

## ⚠️ The suite is not read-only against production

Check 3 calls `init_db()` with the `DATABASE_URL` from `.env`, so **running the test suite
applies any pending migration to the production database.** On 2026-08-20 that dropped
`api_keys.key` while the deployed code still queried it, and the v1 API returned 500 on every
authenticated request until the matching code deployed.

For a migration that drops or renames anything: **push and deploy first, or validate the SQL in
a transaction you roll back** (`conn.autocommit = False` … `conn.rollback()`) rather than by
running the suite.

## ⚠️ `test_admin_auth.py` drives the real app with `.env` loaded

Anything it does *not* stub reaches production. Two writers are deliberately neutered there and
must stay that way:

- `app_mod.log_admin_action` is replaced with a no-op at module import — the login-throttle
  tests otherwise wrote ~36 bogus `429 /api/admin/login` rows into the production audit log,
  which reads exactly like a brute-force attempt.
- `bump_admin_token_epoch` is stubbed in the revoke test — it otherwise really revoked every
  admin session. It did so three times before this was caught.

Anything new that mutates state needs the same treatment.

## Expect 17/17, not "all checks passed"

The three browser suites need Chromium:

```bash
pip3 install playwright && python3 -m playwright install chromium
```

They **skip cleanly when absent** — so a green run can hide them. Check the count: skipping all
three shows as `14/14`. (The total exceeds the 15 numbered checks because check 1 counts two
env vars.) Override discovery with `CHROME_PATH` if needed.

Chromium discovery and the static file server are shared in `scripts/browser_test_util.py`,
whose `Checker.equals()` exists because a truthiness check silently passes any non-empty value
— and fails a legitimately empty one.

## `test_escaping.mjs` reads the shipped source

It **extracts the helper sources from the shipped files** rather than copying them, so it fails
if the implementation regresses, and it asserts no attribute site reverts to `esc()`.
