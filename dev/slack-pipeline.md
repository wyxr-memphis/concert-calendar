# Slack Image Upload Pipeline

> Tripwires live in `CLAUDE.md`. This file is the detail behind them.

DJs upload venue schedule images to **#wyxr-concert-calendar** in Slack to add events without
touching the admin UI.

## How it works

1. User uploads an image with the caption **"add to calendar"**, optionally naming the venue:
   **"add to calendar B-Side"**
2. Slack fires a `file_shared` event to `POST /api/slack/events`
3. Backend downloads the image, checks the caption via `conversations.history`
4. Claude Vision (`claude-sonnet-4-6`) extracts events from the image. **One show is one
   event**, however many acts are on the bill (since 2026-10-01; before that every act became
   its own row). Vision returns `event_name` + `artists`, and
   `compose_show_title()` in `src/sources/artifacts.py` joins them:
   `MDR Showcase: General Labor, Missed Dunks at Summer League, Carry Ripple` when the flyer
   names the show, `Headliner w/ Opener 1, Opener 2` when it doesn't. A venue's month
   schedule is still one row per show. The same prompt serves the daily build's artifacts
   scan (Admin → Import), so both paths agree.
5. The venue is resolved (see below)
6. New events are inserted into PostgreSQL; **a show already on the calendar is updated, not
   skipped** (since 2026-10-04). `_import_or_enrich()` in `backend/app.py` runs
   `find_fuzzy_duplicate` (exact `dedup_key`, then same-night same-venue with a similar title
   **or a shared bill** — the Vision `lineup` is passed along as `_lineup`, so a poster that
   names the show differently from the venue's schedule still finds it) and hands a
   match to `enrich_event`, which fills only the columns the stored row has **blank** — the
   flyer image, a start time — and never replaces a stored value, never touches
   title/venue/date/`source`, and fills manual rows like any other. See
   `dev/database.md` → "Fill-only enrichment on import". The title-level fuzzy check can't
   see a lone act inside a joined title, so each act is also checked on its own; a hit does
   not block the insert but adds a ⚠️ "may already be on the calendar" line to the reply.
   The uploaded image is attached **only when every extracted event is the same show** —
   same canonical venue, same date. A one-night gig poster gets the flyer; a venue's month
   schedule does not (it would thumbnail the whole flyer onto every row). Venue is
   canonicalized via `normalize_venue_from_db` first, so "Lamplighter Lounge, Memphis, TN"
   groups with "Lamplighter Lounge".
7. GitHub Actions rebuild is triggered
8. Bot replies in the channel listing each added event, with the title linked to
   `{SITE_BASE}/admin/edit?id=<uuid>` for one-click correction

The reply has up to three sections, each omitted when empty, every title deep-linked:

```
✅ *3 events added from image:*
• <edit link|Title> — Venue — Sat Oct 3
🔄 *2 existing events updated:*
• <edit link|Stored title> — Venue — Fri Oct 9 (added image, time)
ℹ️ 4 events already on the calendar — nothing new to add.
```

The 🔄 lines show the **stored** title and link the **existing** row, since that is the one the
DJ will see in the editor. A rebuild is triggered when anything was inserted *or* updated. When
nothing was, the reply is "ℹ️ Nothing new — N events … already on the calendar with nothing to
add." `bulk_insert_events` still uses `ON CONFLICT DO NOTHING` as a race backstop, so a row that
collides on a concurrent insert returns nothing and is left out of the ✅ list.
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
  re-upload with the venue in the caption. Applied **before** the `find_fuzzy_duplicate` match,
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
