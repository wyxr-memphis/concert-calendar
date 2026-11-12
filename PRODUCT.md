# Product

<!-- impeccable:product-schema 1 -->

> Written 2026-11-12 from `CLAUDE.md`, `README.md`, the shipped pages, and the redesign
> brief. No interview was held (the brief said to proceed), so anything marked
> **(inferred)** is a reading of the repository, not a confirmed answer. Correct it here.

## Platform

web

## Users

- **Memphis show-goers** on a phone, deciding what to do tonight or this weekend. They scan
  by date, narrow by neighborhood, and open a show for the time, venue and ticket link.
  **(inferred** as the primary audience from GA events, the public domain and the SEO work)
- **WYXR 91.7 FM DJs** reading upcoming shows on air. The calendar was first built for them;
  `/thisweek` is their read-sheet.
- **Station staff** curating the list through `/admin/` and the Slack flyer pipeline.
- **Venues, promoters and artists** adding a show through `/submit`.

## Product Purpose

A daily-updating live music calendar for Memphis, Tennessee, compiled by WYXR 91.7 FM with
Where's the Music Memphis. It gathers shows from Ticketmaster, venue scrapers, flyer OCR and
public submissions into one list, rebuilt twice a day. Success is a visitor finding a show
they did not know about and going.

## Positioning

Every venue in town on one page, curated by a community radio station rather than a ticket
seller: WYXR Picks and WYXR Presents are editorial, and the list includes rooms that no
ticketing platform covers.

## Operating Context

- Served statically from Vercel (`docs/`); events fetched at runtime from the Flask API on
  Render. `docs/index.html` is self-contained: one style block, one script, no build step.
- Shared links use the server-rendered `/e/<id>` page.
- Weekly email (Mailchimp), calendar subscription (`.ics`), and a picks RSS feed hang off the
  same data.

## Capabilities and Constraints

- Month navigation (current month through six months ahead), neighborhood filter, search,
  event detail with add-to-calendar, share link and ticket link.
- Sponsor placements are sold: the monthly calendar sponsor banner and dated sponsor
  callouts must stay visible. The fund-drive banner appears only during a drive.
- All event text and URLs are untrusted (scrapers, OCR, `/submit`).
- Titles arrive in inconsistent case and length; many shows have no image, time or price.
- Tripwires for any change live in `CLAUDE.md` and `dev/`.

## Brand Commitments

- The Concert Calendar logo (Figma `HEADS-UP`, node `1872:3`): flower mascot with a tear-off
  calendar and a ticket, cream / tomato red / marigold / white. It drives the look and the
  palette. The app is a standalone style, not bound to WYXR's brand conventions.
- Display faces, used sparingly and never for UI or long copy: **Irregardless** (Adobe Fonts
  kit `sis1dug`) and **Buinton** (desktop licence: outlined artwork only, no webfont).
- UI faces from the WYXR brand: **Anybody** for headings, **Inter** for copy.
- No dark background.
- Credit both WYXR 91.7 FM and Where's the Music Memphis.

## Evidence on Hand

- Logo vectors: `dev/brand/concert-calendar-logo.figma.svg` (flattened export).
- Live event data through the production API.
- No mascot-only or wordmark-only artwork exists from the designer; the cut-downs in
  `docs/brand/` are derived from the flattened logo.

## Product Principles

1. The list is the product. Decoration never costs a row its legibility or its tap target.
2. Phone first, then spend the extra width on orientation, not on bigger chrome.
3. Editorial picks and paid placements are visibly different from ordinary rows.
4. Nothing from an event record reaches the page unescaped.

## Accessibility & Inclusion

WCAG 2.2 AA: 4.5:1 body text, visible keyboard focus, 44px touch targets, reduced-motion
respected, dialogs trap and return focus. **(inferred** as the bar from "do not sacrifice
accessibility" in the brief)
