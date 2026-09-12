# Sponsors, Subscribe Modal & GA4

> Tripwires live in `CLAUDE.md`. This file is the detail behind them.

## Calendar Sponsor

A single featured sponsor banner above the event list (below the filter bar). One active
sponsor per date range — POST returns 409 on overlap.

- DB table: `calendar_sponsor` (name, image_url, link_url, copy_line, start_date, end_date, is_active)
- Recommended image **600 × 120px** (5:1 horizontal). Any aspect ratio works — the image
  displays at natural proportions, max-width 600px, no cropping.
- Public API: `GET /api/calendar-sponsor` → single object or `{}` (`Cache-Control: max-age=120`)
- Admin API: `GET/POST /api/admin/calendar-sponsor`, `PUT/DELETE /api/admin/calendar-sponsor/<id>`,
  `POST /api/admin/calendar-sponsor/upload-image`
- Managed in Admin → Sponsors tab → "Calendar Sponsor" section (top of tab)
- `renderCalendarSponsor()` in `docs/index.html` is called once on load, **not** on filter or
  month changes

## Sponsor Callouts

Inline promotional cards between day sections in the calendar and RSS feed. Admin → Sponsors →
"Sponsor Callouts" (bottom of tab, separated by `<hr>`).

- DB table: `sponsors` (name, image_url, link_url, display_after_date, start_date, end_date, is_active)
- Public API: `GET /api/sponsors`
- Admin API: `GET/POST /api/admin/sponsors`, `PUT/DELETE /api/admin/sponsors/<id>`,
  `POST /api/admin/sponsors/upload-image`

## Pledge Drive Banner

A date-bounded, admin-toggled banner under the header image (above the sticky filter bar) with
the fund-drive headline, a progress meter, and a Donate button. It coexists with the paid
Calendar Sponsor banner — it never displaces it.

- **Where the percent comes from.** WYXR's WordPress thermometer block publishes the goal at
  `https://wyxr.org/wp-json/wyxr-blocks/v1/thermostat-goal` → `{"percentage": 5}`. Public, no
  auth. The number is *edited* on wyxr.org through a password-protected stepper page; that URL
  is private to Robby and **must never be committed, put in an env var, or pasted into Slack** —
  this repo only reads the public endpoint.
- **Storage:** one JSON blob under key `pledge_drive` in the existing `admin_settings` table
  (`enabled`, `headline` ≤80, `copy` ≤200, `donate_url` https-only, `start_date`/`end_date`
  optional ISO). No DDL, so nothing to register in the schema fast path.
- **Logic:** `backend/pledge_drive.py` — `is_active()` (inclusive window), `validate_settings()`,
  `parse_percentage()` (int, clamped 0–100), `fetch_percentage()` (60 s per-worker cache, 4 s
  timeout, returns the **last good value** on any failure so a wyxr.org hiccup never blanks the
  meter).
- **Public API:** `GET /api/pledge-drive` → `{"active": false}` (without calling wyxr.org) or
  `{active, headline, copy, donate_url, percentage, goal_url}`. `Cache-Control: max-age=60`.
- **Admin API:** `GET/PUT /api/admin/pledge-drive` (`@require_auth`; JSON body, so no bearer-only
  guard needed). Writes are picked up by the audit after-request hook automatically.
- **Admin UI:** Admin → Sponsors → "Pledge Drive" (top of tab). Shows the live percent and
  whether the banner is active today.
- **Frontend:** `renderPledgeDrive()` in `docs/index.html`, fetched in the same `Promise.all`
  as the sponsors. All text via `textContent`, href via `safeUrl()`; a non-integer or
  out-of-range percentage hides the meter but keeps the headline and Donate button. Fires GA4
  `pledge_donate_click` with `percentage`.
- **Tests:** `scripts/test_pledge_drive.py` (pure logic), `test_admin_auth.py` (route auth,
  storage and fetch stubbed), `test_xss_browser.py` (hostile fixture + clean 42% pass).

## Subscribe Modal

Email signup (Mailchimp). Was a full-width yellow `.signup-banner`; now a compact "📧
Subscribe" button in the header that opens a dark modal with the Mailchimp iframe form.
sessionStorage key `wyxr_signup_banner_success` — if set, the button shows "✓ Subscribed"
(disabled).

## GA4 Analytics

Measurement ID: **`G-9866JXK4ND`** (gtag.js in the `<head>` of `docs/index.html`).

All tracking calls go through one helper in the page script:

```javascript
function trackEvent(name, params) {
    if (typeof gtag === 'function') gtag('event', name, params);
}
```

The `typeof gtag` guard prevents errors in local dev where the gtag script isn't loaded.

### Custom events & parameters

| Event name | Parameters | Fired when |
|---|---|---|
| `modal_open` | `event_id`, `event_title`, `venue`, `event_date` (YYYY-MM-DD), `has_ticket_url` (bool) | User opens an event detail modal |
| `modal_close` | `event_id`, `close_method` ("x" / "esc" / "overlay") | User closes the modal |
| `add_to_calendar` | `event_id`, `event_title`, `service` ("google" / "apple" / "outlook") | User clicks a calendar button |
| `external_link_click` | `event_id`, `event_title`, `destination_url` | User clicks "Buy Tickets" |
| `pledge_donate_click` | `percentage` | User clicks Donate on the pledge-drive banner |

### Custom dimensions (must be registered in GA4 Admin)

These parameters are sent correctly by the code but are only visible in GA4 reports after
being registered as **Event-scoped Custom Dimensions** in GA4 Admin → Data display → Custom
definitions:

`event_title`, `venue`, `event_date`, `has_ticket_url`, `close_method`, `service`,
`destination_url`

**Note:** the GA4 dropdown only shows parameters it has already indexed (24–48 hr delay).
Type the parameter name directly into the field — it accepts free text.

⚠️ The CSP host list for GA4 was found empirically — see `dev/security.md` before touching it.

### Verified behaviour (tested 2026-04-24)

- All 38 distinct `start_time` formats in production parse correctly (0 failures), including
  narrow no-break space variants and range formats (`6:30 PM - 8:30 PM` → uses the start time)
- `event_title`, `venue`, and `event_date` are always populated
- `has_ticket_url` is `true` for ~51% of events (74/144 in the dataset at the time)
