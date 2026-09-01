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
