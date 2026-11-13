---
name: Memphis Concert Calendar
description: "The front of a neighborhood theater, printed in the logo's three inks. Tonight is on the marquee; the days after it hang beneath as tear-off calendar leaves."
colors:
  cream: "#FCE2B6"
  cream-deep: "#F6D19A"
  paper: "#FFF8EA"
  white: "#FFFFFF"
  red: "#D53727"
  brick: "#B02A1C"
  marigold: "#FCB91A"
  oxblood: "#3A1510"
  umber: "#6B3A2E"
  rule: "rgb(213 55 39 / 0.28)"
  scrim: "rgb(58 21 16 / 0.6)"
typography:
  display:
    fontFamily: '"irregardless-variable", "Anybody", sans-serif'
    fontSize: "clamp(2.25rem, 12.4vw, 4.75rem)"
    fontWeight: 800
    lineHeight: 0.92
    letterSpacing: "normal"
  display-date:
    fontFamily: '"irregardless-variable", "Anybody", sans-serif'
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.02em"
  display-numeral:
    fontFamily: '"irregardless-variable", "Anybody", sans-serif'
    fontSize: "1.625rem"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "normal"
  headline:
    fontFamily: '"Anybody", "Inter", system-ui, sans-serif'
    fontSize: "1.5rem"
    fontWeight: 800
    lineHeight: 1.15
    letterSpacing: "0.01em"
    fontVariation: "'wdth' 82"
  title:
    fontFamily: '"Anybody", "Inter", system-ui, sans-serif'
    fontSize: "1.0625rem"
    fontWeight: 800
    lineHeight: 1.15
    letterSpacing: "0.03em"
    fontVariation: "'wdth' 82"
  act-name:
    fontFamily: '"Anybody", "Inter", system-ui, sans-serif'
    fontSize: "1rem"
    fontWeight: 700
    lineHeight: 1.22
    letterSpacing: "0.01em"
    fontVariation: "'wdth' 82"
  label:
    fontFamily: '"Anybody", "Inter", system-ui, sans-serif'
    fontSize: "0.875rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.04em"
    fontVariation: "'wdth' 82"
  body:
    fontFamily: '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  body-small:
    fontFamily: '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.35
    letterSpacing: "normal"
  time:
    fontFamily: '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
    fontSize: "0.9375rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "normal"
    fontFeature: "'tnum'"
rounded:
  s: "8px"
  m: "12px"
  l: "20px"
  pill: "999px"
spacing:
  s-1: "4px"
  s-2: "8px"
  s-3: "12px"
  s-4: "16px"
  s-5: "24px"
  s-6: "32px"
  s-7: "48px"
  s-8: "64px"
components:
  button-solid:
    backgroundColor: "{colors.red}"
    textColor: "{colors.white}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "44px"
  button-solid-hover:
    backgroundColor: "{colors.brick}"
    textColor: "{colors.white}"
  button-line:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.brick}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "44px"
  button-line-hover:
    backgroundColor: "{colors.red}"
    textColor: "{colors.white}"
  chip:
    textColor: "{colors.oxblood}"
    rounded: "{rounded.pill}"
    padding: "0 14px"
  chip-hover:
    backgroundColor: "{colors.paper}"
  chip-active:
    backgroundColor: "{colors.marigold}"
    textColor: "{colors.oxblood}"
  search-input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.oxblood}"
    typography: "{typography.body}"
    rounded: "{rounded.pill}"
    padding: "0 14px 0 42px"
    height: "44px"
  leaf:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.red}"
    typography: "{typography.display-numeral}"
    rounded: "{rounded.s}"
    width: "46px"
  leaf-month:
    backgroundColor: "{colors.red}"
    textColor: "{colors.white}"
  marquee:
    backgroundColor: "{colors.red}"
    textColor: "{colors.white}"
    typography: "{typography.display-date}"
    rounded: "{rounded.l}"
    padding: "14px"
  marquee-board:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.oxblood}"
  event-row:
    textColor: "{colors.oxblood}"
    typography: "{typography.act-name}"
    padding: "10px 8px"
  event-row-hover:
    backgroundColor: "{colors.paper}"
  pick-ticket:
    backgroundColor: "{colors.marigold}"
    textColor: "{colors.oxblood}"
    rounded: "{rounded.m}"
    padding: "0 6px 4px"
  presents-panel:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.oxblood}"
    rounded: "{rounded.m}"
  presents-header:
    backgroundColor: "{colors.red}"
    textColor: "{colors.white}"
    padding: "8px 14px"
  detail-card:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.oxblood}"
    rounded: "{rounded.l}"
  sponsor-slot:
    rounded: "{rounded.m}"
    padding: "10px 12px"
  pledge-band:
    backgroundColor: "{colors.oxblood}"
    textColor: "{colors.cream}"
  pledge-donate:
    backgroundColor: "{colors.marigold}"
    textColor: "{colors.oxblood}"
    rounded: "{rounded.pill}"
    padding: "0 22px"
---

# Design System: Memphis Concert Calendar

## Overview

**Creative North Star: "The Neighborhood Marquee"**

The public calendar is the front of a neighborhood theater, printed in the three inks of the Concert Calendar logo: cream stock, tomato red, marigold. Tonight's bill is up on a red marquee ringed with bulbs. The days after it hang beneath as tear-off calendar leaves, the same leaf the flower mascot holds in the logo, and the station's picks are cut like the ticket in its other hand. Everything else is a ruled list on cream.

It is flat print. Depth comes from keylines, rules and the order things are stacked in, never from shadow or tonal blend. Colour is rationed by meaning: red draws the structure, marigold says something is lit, a red-brown ink carries the reading. The list is the product, so the theater dressing stops at the marquee, the leaves and the tickets; rows stay plain, dense and tappable. The page has no dark mode and no dark ground (a brand commitment in `PRODUCT.md`), and it does not use the dark event-app grid of thumbnail cards under a gradient hero.

Motion is one authored moment and a few settling moves. The marquee bulbs chase once when the page first draws tonight's bill; the detail sheet, drawer and dock ease into place; a leaf's numeral gains weight while its day is the one stuck at the top. All of it collapses to an instant change under `prefers-reduced-motion`.

The system lives as CSS custom properties in three layers inside the page's single style block: **inks** (`--ink-*`, raw values sampled from the logo), **roles** (`--ground`, `--surface`, `--text`, `--accent`, `--lit`, `--line` and the font, space, shape, motion, layout and layer tokens), then **parts** (the components). Components read roles, not inks: besides the core roles there are `--field` (text inputs on paper), `--band` / `--on-band` (the fund-drive band, the one dark fill), `--bright` (type, hovers and focus rings on red or dark fills) and `--on-accent-soft` (the cream Tonight script on red).

**Key Characteristics:**
- Cream ground, paper surfaces, red keylines; no shadows, no tonal gradients, no dark ground.
- Marigold only where something is lit.
- Three faces with fixed jobs: Irregardless for the few poster words, Anybody caps for act names and headings, Inter for everything read or operated.
- A weight axis that carries state, and times in a tight tabular column.
- Phone-first single column; extra width goes to orientation (a rail, a leaf column, a docked detail), and the list keeps its measure.
- Pills for controls, logo-badge corners for containers, a ticket notch for picks.

## Colors

Three logo inks on cream stock, plus two darkened reading inks pulled from the same red.

### Primary
- **Tomato Red** (`red`, #D53727): the logo's red. Roles `--accent` and `--line`. Fills (solid buttons, the marquee, leaf month bands, the Presents header), every 2px keyline, and type at 24px and up (the lockup words, leaf numerals). 3.79:1 on cream, so it is never small text on the ground.
- **Brick** (`brick`, #B02A1C): the same red darkened until small text passes. Role `--accent-text`. Times, line-button labels, icons, links, error text, and the hover fill of a solid button.

### Secondary
- **Marigold** (`marigold`, #FCB91A): the petals. Role `--lit`. See The Lit Rule.

### Neutral
- **Cream Stock** (`cream`, #FCE2B6): the logo's background and the page. Role `--ground`. Also the browser `theme-color`.
- **Shaded Cream** (`cream-deep`, #F6D19A): one step into shade. Role `--ground-sunk`: image wells behind thumbnails and letterboxed flyers, the scrollbar track.
- **Leaf Paper** (`paper`, #FFF8EA): warm white. Role `--surface`: leaves, panels, the marquee board, sheets and dialogs, the phone search field, hover on cream.
- **White** (`white`, #FFFFFF): role `--on-accent`, the only text colour on red. Also the fill of a text field that sits on a paper panel.
- **Oxblood Ink** (`oxblood`, #3A1510): red taken almost to black. Roles `--text`, `--on-lit` and `--focus`.
- **Umber Ink** (`umber`, #6B3A2E): role `--text-soft`: venue lines, counts, captions, placeholders.
- **Row Rule** (`rule`, red at 28%): the 1px hairline between rows. On marigold the rule switches to oxblood at 22%.
- **Scrim** (`scrim`, oxblood at 60%): behind the sheet, the drawer and the subscribe dialog.

### Measured pairs
- Oxblood on cream 12.89, on paper 15.35, on marigold 9.34.
- Umber on cream 7.35, on paper 8.75, on marigold 5.33.
- Brick on cream 5.23, on paper 6.22; brick on marigold 3.79 (fails small text).
- Red on cream 3.79, on paper 4.51 (large text and UI only); red on marigold 2.75.
- White on red 4.77; cream on red 3.79.

### Named Rules
**The Lit Rule.** Marigold means something is on, and nothing else. In the shipped pages that is: a WYXR pick (the ticket, the pick badge, a month-grid day that has a pick), an active state (the selected neighborhood chip, the open search toggle), the marquee bulbs, the fund-drive meter with its percent and Donate button, and text selection. It is never a section background, a decoration or a second brand colour.

**The Red Under 24 Rule.** Red type smaller than 24px is brick, not red. On marigold neither red passes: time and labels on a pick go oxblood, secondary text goes umber. Nothing relies on red against marigold.

**The White On Red Rule.** Text on a red fill is white. Cream on red measures 3.79 and is reserved for the outlined "Tonight" script, which is artwork with a screen-reader equivalent beside it.

**The Three Layers Rule.** A new colour need is met by a role. If no role says what you mean, add a role that points at an ink; add an ink only if the logo has it. The inks and roles are copied by hand into four files (`docs/index.html`, `docs/submit.html`, `src/generate_html.py`, `backend/event_page.py`), so a changed ink changes in all four.

## Typography

**Display Font:** Irregardless (`irregardless-variable`, Adobe Fonts kit `sis1dug`, weight axis 300 to 800), falling back to Anybody
**Heading Font:** Anybody (Google Fonts, width axis 50 to 100, weights 600 to 800), falling back to Inter
**Body Font:** Inter (Google Fonts, 400 / 500 / 600 / 700), falling back to system-ui
**Script:** Buinton, as outlined SVG words only (see The Outlined Script Rule)

**Character:** A poster face for a handful of words, a narrow grotesque in caps for the bill, and a neutral sans for everything a person reads or operates. The poster face is tall and condensed by design; the bill is Anybody narrowed on its width axis to 82% (`--head-narrow`, set with `font-stretch`) so long act names hold a line.

### Hierarchy
- **Display** (Irregardless 800, `clamp(2.25rem, 12.4vw, 4.75rem)`, line-height 0.92, uppercase, red): the CONCERT CALENDAR lockup words on phones and on `/thisweek`. On desktop the full logo replaces them.
- **Display date** (Irregardless 700, 1.875rem phone / 2.75rem desktop, line-height 1, 0.02em, uppercase, white on red): the marquee date.
- **Display numeral** (Irregardless 400 at rest, 800 when current; 1.625rem phone / 4.25rem desktop, red): the day number on a leaf. The leaf's month band is Irregardless 700 (0.875rem phone / 1.375rem desktop, 0.08em, white on red).
- **Headline** (Anybody 800 at 82% width, 1.5rem phone / 1.75rem desktop, line-height 1.15, 0.01em, uppercase, balanced wrap): the show title in the detail. Dialog and empty-state titles use the same face at 1.25rem to 1.375rem.
- **Title** (Anybody 800 at 82%, 1rem to 1.125rem, 0.03em, uppercase): the weekday beside a phone leaf (1.0625rem), the month switcher, the bottom search label.
- **Act name** (Anybody 700 at 82%, 1rem phone / 1.0625rem desktop, line-height 1.22, 0.01em, uppercase, `overflow-wrap: anywhere`): every row's artist line.
- **Label** (Anybody 700 to 800, 0.6875rem to 0.875rem, 0.04em to 0.1em, uppercase): button text, the WYXR PICKS and WYXR PRESENTS headers, the Neighborhood filter label, badges. Badges and captions at 0.75rem and under run at Anybody's full width.
- **Body** (Inter 400, 1rem, line-height 1.5): the default. Descriptions are 0.9375rem at 1.6, capped at 65ch.
- **Body small** (Inter 400 to 600, 0.8125rem phone / 0.875rem desktop, line-height 1.35, umber): the venue and neighborhood line under an act. The venue name is 600.
- **Time** (Inter 700, 0.9375rem phone / 1rem desktop, tabular figures, brick, right-aligned in a 3.25rem / 4rem column): the hour, with am/pm at 0.6875rem 600 uppercase. A time that is words ("Doors 7, Show 8") drops to 0.6875rem uppercase and wraps inside the column.

The smallest text on any surface is 0.6875rem (11px), and only as an uppercase label at weight 600 or more.

### Named Rules
**The Poster Face Rule.** Irregardless sets the lockup words, the leaf month and numeral, and the marquee date; on `/thisweek` it also sets the day headings. It never sets a control, a sentence or an act name. It has no width axis: the `font-stretch: 50%` beside it narrows the Anybody fallback so the layout holds if Adobe Fonts does not load. `/e/<id>` loads no Adobe font (its CSP allows Google Fonts only) and uses Anybody throughout.

**The Weight Is State Rule.** A leaf's numeral rests at weight 400 and goes to 800 while its day is the one stuck at the top of the list (240ms). Weight changes mean a state changed; they are not used for emphasis inside the display face.

**The Outlined Script Rule.** Buinton (the script of "Memphis", "Tonight" and "See you at the show") is licensed for desktop use only. It is never served as a webfont and the font file never enters the repository, which is public. The script exists only as outlined paths in `docs/brand/word-memphis.svg`, `word-tonight.svg` and `word-see-you.svg`. A new script word comes from the designer, or from `dev/brand/build_brand_assets.py --buinton <path to the locally licensed .otf>`.

## Layout

Phone first. One column capped at 720px with a 16px gutter (`--gutter`). The credit strip and masthead scroll away; the filter bar (month switcher, search, neighborhood chips) sticks to the top with a 2px red rule beneath it, and each day's heading sticks directly under it at `--bar-h`, which script keeps equal to the bar's current height. Scrolling down tucks the chip row out of the stuck bar by clipping it (240ms); scrolling up or focusing the bar brings it back, and nothing below moves. At 360px and under, buttons tighten and the masthead buttons lose their icons.

From 1024px the page is a two-column grid capped at 1280px with a 32px gutter: a 320px left rail (`--rail-w`) holding the full logo, the two masthead buttons and a sticky paper panel with the month grid open, search, and the neighborhoods as a counted list; then the stage, capped at 880px, with a `clamp(32px, 4vw, 64px)` gap between them. Inside the stage each day is its own two-column grid: a 112px leaf column (`--leaf-col`) whose leaf sticks 24px from the top, and the day's rows beside it under a 2px red rule. The marquee and the Presents panel span the full stage. Sponsor and subscribe callouts indent to the row column.

`/thisweek` (generated by `src/generate_html.py`, no JS) takes the same shape from 1024px: the full logo, tagline and a Full calendar button in a sticky 320px rail, then each day as a 120px column holding its weekday, date and show count beside a ruled list, capped at 880px. Its rows are the home page's: time column, act name, venue beneath; a venue with several acts is named once above them; picks are marigold blocks at the top of the day and are never folded into a venue group.

From 1680px the body reserves a third column on the right, `clamp(420px, 27vw, 520px)` wide, and the event detail docks there instead of covering the list.

The spacing scale is 4, 8, 12, 16, 24, 32, 48, 64 (`--s-1` to `--s-8`). Days are separated by 24px on phones and 48px on desktop; rows are at least 56px tall with 10px (phone) or 12px (desktop) block padding. Touch targets take `--tap` (44px): buttons, icon buttons, the month switcher, text fields.

Layers are a named scale: day heading 5, dock 50, filter bar 100, subscribe footer 120, admin pill 150, subscribe dialog 200, event detail 300, admin notice 310.

### Named Rules
**The Measure Rule.** The list never grows past 880px. Extra width is spent on orientation (the rail, the leaf column, the docked detail) and then on margin, not on wider rows or larger chrome.

**The One Detail, Three Homes Rule.** The event detail is one piece of markup. Under 1024px it is a bottom sheet; from 1024px to 1679px a right drawer; from 1680px a docked, non-modal column. A new overlay follows the same three homes rather than adding a fourth pattern.

## Elevation & Depth

Flat. There is no drop shadow and no blur anywhere in the system. Layering is conveyed by fill (paper on cream, red on cream, marigold on paper), by the 2px keyline around anything laid on the page, by the scrim behind a sheet or drawer, and by the z-index scale above. Sticky headings stay legible by carrying the ground colour and a keyline, not by lifting.

### Named Rules
**The Flat Ink Rule.** No drop shadows, no blurred shadows, no tonal gradient fills. Two CSS devices that share those property names are native to this world and stay: hard-stop radial gradients draw printed dots and punches (the marquee bulbs, the binding holes along a leaf's month band, the notches masked out of a pick ticket), and a zero-blur inset `box-shadow` draws the 2px ring around today in the month grid. The test: if it has a soft edge or implies a light source, it does not belong.

## Shapes

Corners are rounded like the URL badge in the logo. Three radii and a pill: 8px (`--r-s`) for phone leaves, thumbnails, hover and focus fills on rows; 12px (`--r-m`) for the pick ticket, the Presents panel, sponsor slots and the desktop leaf; 20px (`--r-l`) for the marquee, the rail panel, dialogs and the top of the bottom sheet; a full pill for every button, chip and text field. Icon buttons, month-grid days and the close button are circles.

Lines come in three weights, all red unless noted. The 2px keyline (`--keyline`) outlines containers and primary controls and rules off sticky bars and day lists. A 1.5px line outlines secondary things: chips, thumbnails, the small detail actions. A 1px hairline at 28% separates rows. Dashed lines mark things that are not a show: the sponsor slot and the subscribe callout (1.5px dashed red), admin-only actions, the upload drop zone on `/submit`, and the perforation under a pick ticket's header (2px dashed oxblood at 45%).

Recurring silhouettes: the leaf (a red month band over a paper body, with binding holes and a 2 degree counter-clockwise tilt on desktop), the ticket (semicircular notches of 8px radius punched from both edges, level with the perforation), and the bulb ring (marigold dots of 3px to 3.5px radius on a 28px or 44px tile around the marquee). The "Memphis" script on the phone lockup tilts 3 degrees counter-clockwise.

## Components

Controls are plain and printed: a keyline, a fill swap on hover (120ms, ease-out), a 1px press. Hover fills follow the surface: paper on cream, cream on paper, white at 40% on marigold, brick on red. Focus is a 3px oxblood outline offset 2px; on red or oxblood grounds it turns white; on a row it sits inside the row.

### Buttons
- **Shape:** pill (999px), 2px red keyline, 44px tall, 18px side padding, Anybody 700 at 82% width, 0.875rem, 0.04em, uppercase, optional 20px icon with an 8px gap.
- **Solid:** red fill, white label. Hover: brick fill and brick keyline. The primary action of a region (Subscribe, Buy tickets, Get the List).
- **Line:** paper fill, brick label. Hover: red fill, white label. The secondary action (Submit an event, Add to Google Calendar).
- **Detail and form actions** are the same two buttons at 48px tall (0.9375rem in the event detail and on `/e/<id>`, 1rem for the `/submit` button).
- **Icon button:** a 44px circle, brick icon, no border; hover fills paper. The close button adds a 2px keyline and a paper fill.
- **Text button:** underlined Inter 600, 0.875rem, brick; hover oxblood (Clear filters).
- **Disabled:** 55% opacity, no press.

### Chips
- **Style (phone):** a horizontally scrolling row of pills with a 1.5px red outline, no fill, Inter 500 0.875rem in oxblood, each followed by its count in umber tabular figures. They ship 40px tall, under the 44px floor; that height is not a size to copy.
- **Style (desktop rail):** the same buttons become a counted list: 32px rows, 8px corners, no outline, the count right-aligned.
- **Selected:** marigold fill, oxblood text and count, weight 700. On desktop the selected row also takes the 1.5px red outline.

### Cards / Containers
- **Corner Style:** 12px for panels in the list, 20px for the rail panel and dialogs.
- **Background:** paper, on the cream ground.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 2px red keyline.
- **Presents panel:** a paper panel with a red header band (Anybody 800, 0.8125rem, 0.1em, white, with the star icon) over rows of a 56px thumbnail, act name and date line, separated by row rules.
- **Thumbnails:** 48px (56px desktop) squares, 8px corners, 1.5px red outline, shaded-cream well. Rows without an image simply have none; there is no placeholder art.
- Containers are not nested: rows inside a panel are ruled, never boxed.

### Inputs / Fields
- **Search:** a 44px pill with the 2px red keyline, paper fill (white inside the rail panel), a brick search icon inset at the left, umber placeholder, 16px text so iOS does not zoom. The browser's clear button is redrawn as a brick cross.
- **Email (subscribe dialog):** the same pill with a white fill.
- **Form fields (`/submit`):** white fill, a 1.5px umber line and 10px corners rather than the red keyline, because a column of red-edged inputs reads as a column of errors. Focus turns the line red; an error is a 2.5px brick line with brick 600 text beneath.

### Navigation
- **Credit strip:** one centred line at the very top crediting WYXR 91.7 FM and Where's the Music Memphis (Inter 500 0.75rem, umber, a red dot between), over a row rule.
- **Month switcher:** previous and next icon buttons around the month name (Title style) with a chevron that turns over when the month grid is open. On phones a search icon button sits at the end and fills marigold while search is open.
- **Rail (desktop):** logo, the two masthead buttons, then the sticky paper panel described in Layout.
- **Footer:** the outlined "See you at the show" script (up to 320px wide), a credit line, then centred text links with icons at 0.875rem; a quieter second row in umber.
- **Subscribe footer:** a paper bar fixed to the bottom with a 2px red top rule that slides up (350ms) and can be dismissed.

### Tonight Marquee
The first day in the list when it is today. A red block with 20px corners whose padding is a ring of marigold bulbs: two interleaved layers of hard-edged dots on one tile (ring 14px and dots 3px on phones; 22px and 3.5px on desktop). Inside, a red head carries the outlined "Tonight" script in cream (7.75rem wide on phones, 13rem on desktop), the date in the Display date style and the show count in white; below it a paper board with 10px corners holds the rows. Row hover on the board is cream.

On first arrival the two bulb layers alternate, 0.7s per step for six steps and half a step apart, then rest fully lit. It runs once per page load. Under reduced motion the bulbs are simply lit.

### Date Leaf
A tear-off calendar leaf for every day after tonight: paper body, 2px red keyline, red month band with a white abbreviated month, the day numeral below in red. On phones it is 46px wide with 8px corners and sits in the sticky day heading beside the weekday (Title style), the date (0.8125rem umber) and the day's show count at the right. On desktop it is 104px wide with 12px corners, tilted 2 degrees, with binding holes punched in cream along the top of the band, the weekday abbreviation beneath the numeral (Anybody 800, 0.75rem, 0.14em) and the count under the leaf; it sticks in its own column while its rows scroll past. The numeral follows The Weight Is State Rule.

### Event Row
Time column, then the act name over the venue line, then an optional thumbnail. No box: rows are separated by the row rule, and the last row of a day has none. The whole row is the target; hover fills it paper, and the row whose detail is open stays filled with 8px corners. The venue and neighborhood share a line separated by a centred dot and wrap as whole items. Several acts at one venue are grouped: the venue is named once above them and the rows beneath drop to 44px with no rules between.

### WYXR Pick Ticket
The station's picks for a day, gathered at the top of that day. A marigold block with 12px corners and a semicircular notch cut from each side. A header 32px tall (39px desktop) carries the star icon and WYXR PICKS (Anybody 800, 0.8125rem, 0.08em) over a dashed perforation level with the notches. Rows inside follow Event Row with oxblood times and oxblood rules; hover is white at 40%. On `/thisweek` a pick is a plain marigold block with 12px corners labelled WYXR PICK; in print it becomes an outlined block.

A show WYXR presents carries a small red badge with white Anybody 800 caps (0.6875rem). In the detail, Pick and Presents are pill badges in marigold and red.

### Month Grid
A seven-column grid of 40px circles (36px in the rail). Days with shows are oxblood 700 and are buttons that jump to that day; hover fills red with a white numeral. Days without shows are not buttons; they are dimmed, weight 400, and hidden from assistive technology. A day that has a WYXR pick is filled marigold; today takes a 2px red ring. A one-line key under the grid explains the marigold dot. Closed by default on phones, open in the rail.

### Event Detail
One card in three homes (see Layout). As a sheet: up to 640px wide and 92dvh tall, 20px top corners, keyline on three sides, entering 32px upward over 420ms. As a drawer: 480px wide, full height, a keyline on its left edge only, entering 40px from the right. Docked: full column height with a left keyline, no scrim, rising 8px over 420ms; before anything is opened the column shows the red note mark, "Pick a show" and one line of help. The flyer is letterboxed on shaded cream and never cropped (up to 56dvh, 64vh on desktop) with a keyline beneath. Then the Headline title, venue (600), date and time in brick, badges, meta in umber, the description, and three action groups. Buy tickets is a notched ticket stub (red fill, white label, dashed perforation, arrow), the one primary. Under a rule, "Add to your calendar" names a row: a tear-off leaf (binding holes, tilted 2 degrees, weekday showing, numeral going to weight 800 while a choice in the row is hovered or focused) beside three equal line buttons — Google and Outlook with the shared calendar icon, Apple with the download icon, since that one saves an .ics file — Anybody 800 caps, 12px corners, 72px tall. Below 360px the leaf sits above those buttons so the names stay whole. Copy link is its own text row beneath, with a link icon that swaps to a check for two seconds. The admin pick control, when present, is a dashed pill under that, never inside the calendar row. The row that opened the detail stays filled while it is open.

The subscribe dialog is a centred paper card (max 420px, 20px corners, keyline) on the scrim, rising 8px over 240ms.

### Sponsor and Promo Slots
Paid and promotional placements are visibly not shows: a 1.5px dashed red outline with 12px corners, a small uppercase umber label (Inter 600, 0.6875rem, 0.05em) naming the placement, the sponsor's artwork with 8px corners, and a line of umber copy. Sponsor artwork keeps its own colours. The subscribe callout between days uses the same dashed outline with a brick icon and call to action.

### Fund-Drive Band
Shown only during a drive, above the page: an oxblood band with cream copy, a white Anybody 800 headline, a meter (a white 20% track, 12px tall, with a marigold fill that slides in over 600ms), the percent in marigold tabular figures and a marigold Donate pill that turns white on hover. It is the one dark band on any surface, so a drive reads as an announcement and not as a sponsor slot; oxblood is not a fill anywhere else.

### Icons
One inline sprite, a 24px grid, a 2px stroke with round caps and joins, no fill, drawn at 1.25em in the current text colour. The star is the same outline filled. New icons are added to the sprite in the same weight.

### Brand Artwork
`docs/brand/` holds `logo.svg` (the full lockup, used in the desktop rail and for the social card), `mascot.svg` (the flower with its leaf and ticket, used beside the phone lockup, on `/submit`, `/e/<id>` and `/thisweek`), `note.svg` (the red music note in the docked detail's empty state) and `star.svg` (the logo's red star; shipped, not yet placed on any page), the three outlined script words, and three rasters (`og-image.png` 1200x630 on cream, `apple-touch-icon.png` on marigold, `favicon-32.png`). The cut-downs are derived from the designer's flattened export in `dev/brand/` by `build_brand_assets.py`; nothing is redrawn. Rasters are produced by `dev/brand/rasterize.sh`.

Vercel serves every `.svg` and `.png` as immutable for 30 days. A changed brand asset ships under a new filename or with a `?v=` on every tag that loads it.

## Do's and Don'ts

### Do:
- **Do** read roles (`--ground`, `--surface`, `--text`, `--accent`, `--accent-text`, `--lit`, `--line`) in component CSS, and add a role before reaching for an ink.
- **Do** keep marigold for lit things and put oxblood on it for text, umber for secondary text.
- **Do** use brick for any red text under 24px, and white for any text on red.
- **Do** outline anything laid on the page with the 2px red keyline and separate rows with the 1px rule.
- **Do** set act names and headings in Anybody caps at 82% width, and everything read or operated in Inter.
- **Do** give every new control the 44px `--tap` floor and a visible 3px focus outline (white on red or oxblood).
- **Do** keep the list at its 880px measure and spend extra width on orientation.
- **Do** mark paid and promotional placements with the dashed outline and a label.
- **Do** make any new motion collapse under `prefers-reduced-motion`, and use the existing durations (120ms, 240ms, 420ms) and `--ease-out`.
- **Do** rename or version a brand asset when it changes.
- **Do** change the ink and role block in all four files that carry it.

### Don't:
- **Don't** use a dark page background or a dark mode. The fund-drive band is the only dark fill.
- **Don't** add drop shadows, blurred shadows or tonal gradients. Hard-stop gradients for printed dots and punches are the exception the world is built on.
- **Don't** serve Buinton as a webfont or commit its font file. Script words are outlined SVG only.
- **Don't** set controls, sentences or act names in Irregardless.
- **Don't** put red or brick text on marigold, or cream text on red.
- **Don't** use marigold as a decorative fill, a section background or a second accent.
- **Don't** box ordinary rows into cards or nest one container in another.
- **Don't** crop a flyer; letterbox it.
- **Don't** widen rows or enlarge chrome to fill a wide screen.
- **Don't** overwrite a file in `docs/brand/` in place and expect browsers to see it within 30 days.
