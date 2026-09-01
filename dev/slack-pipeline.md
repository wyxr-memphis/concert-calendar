# Slack Image Upload Pipeline

> Tripwires live in `CLAUDE.md`. This file is the detail behind them.

DJs upload venue schedule images to **#wyxr-concert-calendar** in Slack to add events without
touching the admin UI.

## How it works

1. User uploads an image with the caption **"add to calendar"**, optionally naming the venue:
   **"add to calendar B-Side"**
2. Slack fires a `file_shared` event to `POST /api/slack/events`
3. Backend downloads the image, checks the caption via `conversations.history`
4. Claude Vision (`claude-sonnet-4-6`) extracts events from the image
5. The venue is resolved (see below)
6. New events are deduplicated and inserted into PostgreSQL. The uploaded image is attached
   **only when every extracted event is the same show** — same canonical venue, same date. A
   4-act bill on one night gets the flyer; a venue's month schedule does not (it would
   thumbnail the whole flyer onto every row). Venue is canonicalized via
   `normalize_venue_from_db` first, so "Lamplighter Lounge, Memphis, TN" groups with
   "Lamplighter Lounge".
7. GitHub Actions rebuild is triggered
8. Bot replies in the channel listing each added event, with the title linked to
   `{SITE_BASE}/admin/edit?id=<uuid>` for one-click correction

The reply counts and lists only events that **actually inserted** — `bulk_insert_events` uses
`ON CONFLICT DO NOTHING`, so a row that collides returns nothing and is skipped.
`SITE_BASE_URL` overrides the site origin (defaults to `https://concert-calendar.wyxr.org`).

## Venue resolution

A venue's own monthly schedule usually never prints the venue name on it — B-Side's August
flyer is just "AUGUST" over their logo. Vision has nothing to read, so it used to return
"Unknown Venue" and 40 shows landed on the public calendar under that string (2026-08-04).

- **Caption wins.** `_venue_hint_from_caption()` reads whatever follows "add to calendar" and
  resolves it strictly against the DB `venues` table (names + aliases), trimming trailing words
  one at a time so "add to calendar b-side thanks!" still matches. When it resolves, that venue
  is applied to **every** event from the image — one flyer is one venue. Nothing in the caption
  matching a known venue → no hint (chatter can't invent a venue).
- **Placeholders never insert.** `_is_placeholder_venue()` catches "Unknown Venue", "Venue
  TBA", "TBA/TBD", "N/A", empty, etc. Those events are dropped and the reply tells the DJ to
  re-upload with the venue in the caption. Applied **before** the `is_fuzzy_duplicate` check,
  which keys off venue.
- The Vision prompt also asks for an empty venue rather than a guessed placeholder.

### Recovery for rows already inserted under a wrong venue

```bash
python scripts/reassign_venue.py --from "Unknown Venue" --to "B-Side Memphis"
```

Dry-run by default, `--confirm` to write. It sets neighborhood from the venues table,
recomputes `dedup_key`, and skips any row that would collide with an existing event.

⚠️ **Don't use Admin → Venues merge for this** — merge adds the bad string as a permanent
alias, which would silently route every future venue-less flyer to that venue.

## Configuration

Render environment variables:

| Variable | Source |
|---|---|
| `SLACK_BOT_TOKEN` | api.slack.com → OAuth & Permissions → Bot User OAuth Token |
| `SLACK_SIGNING_SECRET` | api.slack.com → Basic Information → Signing Secret |
| `SLACK_CHANNEL_ID` | Right-click channel in Slack → View channel details → Channel ID |

Slack app config (api.slack.com):
- **OAuth scopes:** `files:read`, `chat:write`, `channels:history`
- **Event Subscriptions → Request URL:** `https://concert-calendar-api.onrender.com/api/slack/events`
- **Subscribe to bot events:** `file_shared`
- Bot must be invited to the channel: `/invite @WYXR Concert Calendar`

## Implementation

- `backend/app.py` — `slack_events()` route, `_process_slack_image()` background thread
- `src/sources/artifacts.py` — `extract_events_from_image_bytes()` public entry point

## Debugging

- All Slack activity logs with a `[slack]` prefix in the Render logs
- No `[slack]` lines after an upload: bot not in channel, wrong event subscription, or the app
  needs a reinstall
- "No events extracted": check the Vision response in the logs — year assumptions are a common
  failure for handwritten schedules with no year shown (the prompt instructs Claude to assume
  the current or next year)
- Reinstall after any scope change: api.slack.com → OAuth & Permissions → Reinstall to WYXR
- Large images (>3 MB) must be resized before the Vision API (max ~1024x2048). Vision returns
  markdown-wrapped JSON — parse between `[` and `]`. Period-separated dates ("2.13") need
  explicit format support.
