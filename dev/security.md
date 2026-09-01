# Security & Auth

> Tripwires live in `CLAUDE.md`. This file is the detail behind them.
> **Not published** — `docs/` is Vercel's output directory, this file is deliberately outside it.

## Secrets

- API keys live in `.zshrc` (local), GitHub Secrets (CI/CD), Render env vars (production)
- `.claude/settings.local.json` contains API keys in permission strings — protected by `.gitignore`
- Never commit secrets — `test_before_push.sh` scans for them

### Where each variable lives

| Location | Variables |
|---|---|
| **Render** (production API) | `DATABASE_URL` (internal), `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, `ALLOWED_ORIGINS`, `GITHUB_PAT`, `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_CHANNEL_ID`, `ANTHROPIC_API_KEY`, `CLOUDINARY_URL`, `SUBMISSION_IP_SALT` |
| **Vercel** | `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, `GITHUB_PAT`, `UPLOAD_PASSWORD` |
| **GitHub Actions** | `TICKETMASTER_API_KEY`, `ANTHROPIC_API_KEY`, `DATABASE_URL` (external), `VERCEL_DEPLOY_HOOK` |
| **Local `.zshrc`** | `TICKETMASTER_API_KEY`, `ANTHROPIC_API_KEY` |
| **Local `.env`** | `DATABASE_URL` (external), `ADMIN_PASSWORD`, and the rest — from `.env.example` |

⚠️ `DATABASE_URL` must be a **single line** — a line break breaks the connection. Use the
**internal** URL for Render services, the **external** URL for GitHub Actions and local scripts.

## `ADMIN_SECRET_KEY` must be set on Render

Unset, `backend/auth.py` falls back to a per-process random key: tokens signed by one worker
are rejected by every other, and every restart silently invalidates all sessions. It warns
loudly at startup and reports in `GET /health` (a `warnings` array means it is missing) rather
than aborting boot — making it fatal would take the API down on deploy.
**Confirmed set in production 2026-08-20.**

## Login

- **Throttled** — 10 failures per client per 15 min → 429, counted in process memory (a new
  table would add DDL to the boot path; see the `init_db` lock gotcha in `dev/database.md`).
  Only failures count and success resets, so a legitimate admin retyping is never locked out.
- Passwords are compared as **UTF-8 bytes** — `hmac.compare_digest` raises `TypeError` on a
  non-ASCII `str`, which returned 500 instead of 401.

## Security headers ship from both origins

They are not the same policy: `backend/app.py`'s `_add_security_headers` (an `after_request`
that uses `setdefault`, so a route's own `Cache-Control` survives) and the catch-all rule in
`vercel.json`.

| | Content-Security-Policy |
|---|---|
| Flask, JSON | `default-src 'none'` — renders nothing, so allow nothing |
| Flask, `/e/<id>` HTML | strict, including **`script-src 'none'`** — the page's only `<script>` is a JSON-LD *data* block, which CSP does not treat as script |
| Vercel, all pages | `'unsafe-inline'` in `script-src`, because `index.html` and the admin pages carry their JS inline and there is no build step that could add nonces |

**So the Vercel CSP does *not* stop injected inline script — `escAttr`/`safeUrl` are still what
does that.** What it does stop: loading script from an unlisted host, exfiltrating to one,
`<base>` hijacking, plugins, and framing.

⚠️ **The GA4 host list was found empirically, not from documentation.** `analytics.google.com`
is a *bare* host, so a `*.analytics.google.com` wildcard misses it — and it carries the core
`page_view` beacon, so getting this wrong silently kills analytics. This property also has
Google Ads linking on, which adds `*.doubleclick.net` and `www.google.com`.

`scripts/test_security_headers.py` drives the real pages under the **shipped** policy (parsed
out of `vercel.json`) in Chromium and fails on any violation — a CSP that breaks the page is
worse than no CSP. Re-run it after touching either policy or adding any third-party embed.

## Image upload validation

**Checked three ways** (`backend/images.py` `validate()`): size, then the claimed extension,
then the file's own magic bytes plus a Pillow decode with `MAX_IMAGE_PIXELS` bounded. The
extension decides the Content-Type Cloudinary serves; only the signature says whether it is an
image at all. Admin uploads are *not* re-encoded (unlike submissions), so this is the only
place a mislabelled file is caught.

`src/sources/artifacts.py` sets `Image.MAX_IMAGE_PIXELS` at import and its optimize paths
re-raise `DecompressionBombError` rather than falling back to the raw bytes — falling back
would hand the payload to the Vision API and bill us for it.

## Misc hardening

- **`app.run(debug=...)` is gated behind `FLASK_DEBUG`.** Production runs under gunicorn and
  never reaches that branch, but `debug=True` there would expose the Werkzeug console on any
  traceback.
- **API keys are stored hashed** (`api_keys.key_hash`, sha256), with `key_prefix` kept only so
  a key is identifiable in the admin list. The plaintext exists exactly once, in the response
  from `POST /api/admin/api-keys`. **An issued key cannot be recovered** — if a partner loses
  theirs, issue a new one. `hash_api_key()` must keep producing the same digest as Postgres's
  `encode(sha256(key::bytea), 'hex')`, which the migration used to backfill.
- **Admin writes are audited** to `admin_audit_log` by a single `after_request` hook, so a
  route added later is covered without anyone instrumenting it. GETs are excluded (a read is
  not an action) and 401s are excluded — otherwise an unauthenticated caller could write rows.
  `log_admin_action` never raises: an audit failure must not turn a successful edit into an
  error response. Viewable at Admin → Tools → Security.
- **Sessions can be revoked** — `POST /api/admin/revoke-sessions` bumps an epoch stored in
  `admin_settings`, and every token carrying an older epoch dies. The epoch is in the DB
  because gunicorn runs several workers, cached for `TOKEN_EPOCH_CACHE_SECONDS` (15s) so it is
  not a query per request, and **reads as `None` on failure so `verify_token` skips the
  check** — a transient Postgres timeout must not lock the admin out. Availability wins here
  because revocation is rare and deliberate and tokens expire within 8 hours anyway.
- **Errors are never echoed into the Slack channel.** `#wyxr-concert-calendar` has the whole
  station in it; exception strings there have carried paths and API responses. The full
  exception goes to the Render logs (access controlled), the channel gets a generic line.

## API auth patterns

- Admin uses JWT Bearer tokens (cross-origin from Vercel to Render)
- CORS configured for the `ALLOWED_ORIGINS` environment variable

### Multipart upload routes use `@require_bearer_auth`, not `@require_auth`

The admin cookie is `SameSite=None` so Vercel can reach Render, which means the browser
attaches it cross-site too — and a `multipart/form-data` POST is a **CORS-simple** request, so
it sends with no preflight and the write lands even though the response is unreadable.
Requiring the `Authorization` header forces a preflight that CORS rejects for unknown origins.
Transparent to the admin UI, which always sends the header via `AdminAPI.apiFetch`.

Apply it to **any new state-mutating route that reads form data**; routes parsing JSON already
force a preflight.

### The Bearer token lives in `sessionStorage`, which is per-tab — the cookie is not

So a page opened in a *new* tab (the Slack bot's reply links go straight to
`/admin/edit?id=<uuid>`; any middle-click does it too) authenticates fine on the cookie —
`/api/admin/me` and every `require_auth` route work, the form loads and saves — while all four
`require_bearer_auth` upload routes answer 401 `Not authenticated`. That tab could not recover
on its own: `login.html` bounces to `/admin/` whenever the cookie is valid, so there was no way
to get a token into it short of logging out. Reported 2026-08-20 as "Not authenticated" when
uploading an event image.

**Fix:** `GET /api/admin/me` echoes the token it authenticated with (`current_token()` in
`backend/auth.py` — the *same* token, never a fresh one, so polling cannot extend the 8-hour
session), and `AdminAPI.apiFetch` calls `hydrateToken()` before any request when
`sessionStorage` is empty. Echoing it does not weaken the CSRF guard: a cross-site page can
send that credentialed GET but CORS won't let it read the response, so it still cannot learn
the token or forge the header.

A 401 from an upload route now means the session genuinely expired — surface it with
`uploadFailureMessage(resp, data)` rather than echoing the API's bare "Not authenticated",
which reads like a page bug.
