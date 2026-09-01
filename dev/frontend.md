# Frontend Internals (`docs/index.html`)

> Tripwires live in `CLAUDE.md`. This file is the detail behind them.

`docs/index.html` is **fully self-contained** — all CSS in one `<style>` block, all JS in one
`<script>` block at the bottom. No build step, no bundler, no separate CSS/JS files for the
public calendar. Admin pages have their own JS files under `docs/admin/`.

## Structure

- CSS variables at `:root` (lines ~34–43): `--wyxr-yellow`, `--wyxr-charcoal`, `--wyxr-border`, etc.
- Subscribe modal: `#subscribeModal`, card class `.subscribe-modal-card` (background `#1A1A1A`,
  `border-radius: 8px`, overlay `rgba(0,0,0,0.75)`) — **reuse these patterns for any new modal**
- Event Detail Modal: `#eventModal` — opened by clicking any `[data-event-id]` element
- All JS lives inside one IIFE `(function() { 'use strict'; ... })()` starting around line 800
- Events are fetched from the **production Render API** at runtime — static, not server-rendered
- `allEvents` holds all fetched events; `eventsById` (`{id: event}`) is built in `showEvents()`
- Event rows use `data-event-id` + event delegation on `#eventList` (no per-row listeners)

## The three escaping helpers

Picking the wrong one is a live XSS bug. All three are near the bottom of the script.

| Helper | Use for | Why not the others |
|---|---|---|
| `esc()` | text **between tags** only | Sets `textContent` and reads `innerHTML` back, which encodes `&`, `<`, `>` but **leaves quotes** — so it does not terminate a quoted attribute |
| `escAttr()` | any value going into a **quoted attribute** | 136 of ~3100 event titles contain a quote character, so `esc()` in an attribute breaks on real data, not just on attacks |
| `safeUrl()` | any value reaching **`href` / `src`** | Escaping does not stop a `javascript:` URL. Scraper ticket URLs and OCR'd image URLs are untrusted. No-op for `http(s):`, returns `""` otherwise |

Compose them: `escAttr(safeUrl(cldImg(ev.image_url, 600)))`.

**Never strip markup with the detached-`innerHTML` idiom.** Assigning to `innerHTML` on a
detached div and reading `textContent` back looks safe because a detached element does not run
`<script>` — but the parser still **builds the nodes**, so `<img src=x onerror=…>` fires
immediately. Use `DOMParser` (its documents have no browsing context). This was a real sink in
`_buildCalendarData`, found only by driving the page in a browser.

`scripts/test_escaping.mjs` **extracts the helper sources from the shipped files** rather than
copying them, so it fails if the implementation regresses, and it asserts no attribute site
reverts to `esc()`.

## Event Detail Modal

- `openEventModal(eventId, triggerEl)` / `closeEventModal(method)` — module-scope functions
- `_buildCalendarData(ev)` — builds Google Calendar URL, Outlook.com URL, and Apple `.ics` Blob
- GA4: fires `modal_open`, `modal_close`, `add_to_calendar`, `external_link_click`
- Visual style matches the subscribe modal: `#1A1A1A` card, `border-radius: 12px`, yellow CTA
- Accessibility: `role="dialog"`, `aria-modal`, focus trap, focus returns to the trigger row
- `_parseEventStartTime()` mirrors `time_format.parse_start_time` — see `dev/database.md`
  for why the two must agree. Defaults: 8 PM start, 3 hour duration, `America/Chicago` via
  `Intl.DateTimeFormat` `shortOffset` for Outlook ISO strings.

## Deep links

The page keeps the URL in step with the modal. Three distinct paths, all covered by
`scripts/test_deeplink_browser.py`:

| How the modal opened | What closing it must do |
|---|---|
| clicked a row (we pushed an entry) | `history.back()` — and the browser's Back must close the modal |
| loaded straight onto `#event=…` | `replaceState` to strip the hash **in place**; `back()` would leave the site |
| a Back/Forward navigation | neither push nor pop — `_emSuppressHistory` guards it, or Back becomes an inescapable loop |

`syncModalToHash()` runs at the end of `showEvents()`, because `eventsById` does not exist any
earlier. The modal's **Copy link** button copies the `/e/<id>` permalink, not `location.href` —
the hash URL does not unfurl.

## Cloudinary URL handling

`cldImg()` must handle three URL shapes — see `dev/images.md`.
