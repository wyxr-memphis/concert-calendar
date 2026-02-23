# Calendar Sync Overhaul Plan

## The Problem

There are **two disconnected data stores** for events:

| Store | Used by | Updated by |
|-------|---------|------------|
| `data/events.json` (GitHub) | Build pipeline, static calendar | Scrapers, import confirm |
| PostgreSQL (Render) | Admin UI (list, edit, delete) | Admin CRUD, import confirm |

When you edit or delete an event in the admin, it only changes PostgreSQL. The calendar reads from `events.json`. To get changes to the calendar, you currently need **three manual steps**: edit in admin -> Sync to Calendar -> Trigger Build. This is fragile, confusing, and leads to the stores drifting apart.

### Current flow (broken)

```
Admin deletes event
  -> PostgreSQL: is_active = false
  -> events.json: unchanged
  -> Calendar: still shows it

Admin clicks "Sync to Calendar"
  -> events.json: is_active synced from PostgreSQL
  -> Calendar: still shows it (HTML not rebuilt)

Admin clicks "Trigger Build"
  -> HTML regenerated from events.json
  -> Calendar: finally updated
```

Three steps, each can fail independently, and the sync uses fuzzy matching that can produce false positives.

---

## Proposed Solution: Write-Through to events.json

**Every admin operation that changes an event should immediately update `events.json` on GitHub.** PostgreSQL stays as a fast read cache for the admin UI, but `events.json` is the single source of truth.

### New flow

```
Admin deletes event
  -> PostgreSQL: is_active = false
  -> events.json: is_active = false (automatic, same request)
  -> Calendar: updated on next build (auto-triggered)
```

One click. No sync step. No manual build trigger.

---

## Implementation Plan

### Phase 1: Auto-sync on every admin write

Modify these backend endpoints to also write to `events.json` via GitHub Contents API:

**1. DELETE `/api/admin/events/<id>`** (soft-delete)
- After `soft_delete_event(event_id)` in PostgreSQL
- Find matching entry in events.json by event title+venue+date
- Set `is_active: false`
- Commit to GitHub

**2. PUT `/api/admin/events/<id>`** (edit)
- After `update_event(event_id, body)` in PostgreSQL
- Find matching entry in events.json
- Update the same fields (title, venue, date, start_time, etc.)
- Commit to GitHub

**3. PATCH `/api/admin/events/<id>/featured`** (toggle featured)
- After `toggle_featured(event_id, is_featured)` in PostgreSQL
- Find matching entry in events.json
- Set `is_featured` to match
- Commit to GitHub

**4. POST `/api/admin/events/bulk`** (bulk deactivate/feature)
- After `bulk_action(action, ids)` in PostgreSQL
- Find all matching entries in events.json
- Apply the same action
- Single commit to GitHub

**5. POST `/api/admin/events`** (create new event)
- After `create_event(body)` in PostgreSQL
- Append new entry to events.json
- Commit to GitHub

This replaces the current "Sync to Calendar" button entirely.

### Phase 2: Auto-trigger build after writes

After any events.json commit from Phase 1, automatically trigger a GitHub Actions build. This eliminates the "Trigger Build" button for routine operations.

Options (pick one):
- **Option A**: Call workflow_dispatch after every events.json commit. Simple but slow (~2 min per build). Could batch by debouncing (only trigger if no build in last 5 min).
- **Option B**: Skip the full build entirely. Since we're already writing to events.json via the API, we could also regenerate `docs/index.html` directly from events.json on the server and commit it. No need for the full scraper pipeline just to reflect admin changes.
- **Option C (recommended)**: Auto-trigger build, but add a 30-second delay on the frontend. After any admin action, show "Changes saved. Calendar will update in ~2 minutes." No manual button needed.

### Phase 3: Clean up dead code

Once Phase 1 is done:
- Remove `POST /api/admin/sync` endpoint (no longer needed)
- Remove "Sync to Calendar" button from scrapers.html
- Optionally remove "Trigger Build" button (if Phase 2 auto-triggers)
- Simplify the admin UI messaging

---

## Helper Function: `_update_events_json`

Extract a shared helper so all endpoints use the same logic:

```python
def _update_events_json(action, event_data):
    """Update data/events.json on GitHub to match a PostgreSQL change.

    action: "upsert" | "deactivate" | "set_featured"
    event_data: dict with at minimum title, venue, date

    1. Fetch current events.json from GitHub
    2. Find matching entry by normalized title+venue+date
    3. Apply the action
    4. Commit back to GitHub
    """
```

Key design decisions for this function:
- **Match by normalized key** (title|venue|date) — same as current dedup logic
- **If no match found for "upsert"**: append a new entry
- **If no match found for "deactivate"**: no-op (event only existed in PostgreSQL)
- **Batch mode**: accept a list of changes and do one GitHub commit (for bulk ops)
- **Error handling**: if GitHub API fails, log warning but don't fail the admin request. The admin UI should still work even if events.json sync fails.

---

## What Stays the Same

- **Build pipeline** (`src/main.py`): Still runs 2x daily, fetches scrapers, merges into events.json, generates HTML. No changes needed.
- **Import confirm** (`/api/admin/import/confirm`): Already writes to both PostgreSQL and events.json. No changes needed.
- **Static calendar**: Still served from `docs/index.html` on Vercel. No changes needed.
- **Scraper logs**: Still written to PostgreSQL by the build. No changes needed.

---

## Migration Steps

1. Implement `_update_events_json` helper in `backend/app.py`
2. Wire it into DELETE, PUT, PATCH, POST, and bulk endpoints
3. Test each operation: verify both PostgreSQL and events.json update
4. Remove sync endpoint and button
5. (Optional) Add auto-build trigger after events.json commits
6. Update MEMORY.md with new architecture

---

## Estimated Effort

| Phase | Work | Time |
|-------|------|------|
| Phase 1 (auto-sync) | Implement helper + wire 5 endpoints | 1-2 hours |
| Phase 2 (auto-build) | Add build trigger after commits | 30 min |
| Phase 3 (cleanup) | Remove sync button, dead code | 15 min |

---

## Risk: GitHub API Rate Limits

GitHub Contents API has a rate limit of 5,000 requests/hour for authenticated users. Each admin operation would use 2 calls (GET + PUT). At normal admin usage this is not a concern. Bulk operations should batch into a single commit.

## Risk: Race Conditions

If two admin operations happen simultaneously, the second PUT could fail (SHA mismatch). Handle this by retrying once with fresh SHA. The build pipeline also commits to events.json, so there's a small window where an admin commit could conflict with a build commit. Same retry logic applies.

---

## UI Changes After This Overhaul

### What changes for the admin user

After the write-through is implemented, the admin workflow gets dramatically simpler. The goal: **every action in the admin instantly updates the calendar data**. No extra buttons, no manual sync, no guessing.

### Scrapers Page — Simplified

**Remove these buttons:**
- "Sync to Calendar" — no longer needed (every admin action already syncs)

**Keep these buttons:**
- "Trigger Build" — still useful for forcing a full scraper re-run (fetches new events from Ticketmaster, venues, etc.)
- "Refresh" — refreshes the scraper status cards on the page

**Change the "Trigger Build" label and messaging:**
- Rename to **"Run Scrapers"** so it's clear this fetches *new* events from external sources
- After clicking, show: *"Scrapers running — new events will appear in ~2 minutes."*

**After Phase 2 (auto-build):**
- After any admin edit/delete/feature toggle, show a brief toast: *"Saved. Calendar updates in ~2 minutes."*
- No manual button needed for admin changes — only "Run Scrapers" remains for pulling new data

### Events Page — No Changes Needed

The events list (`/admin/index.html`) already works well. After the overhaul, the star toggle, active toggle, and row-click-to-edit all work exactly the same — but now they also update `events.json` behind the scenes. No new buttons or UI changes needed here.

**One small improvement:** After toggling an event's active/featured status, show a brief success toast (e.g., *"Updated"*) so the user has confirmation it worked. Currently the toggle is silent.

### Edit Page — No Changes Needed

The add/edit form (`/admin/edit.html`) works the same. Save, deactivate, and cancel all work as before — the backend just also writes to `events.json` now. No UI changes needed.

### Import Page — Minor Messaging Update

After confirming an import, the current message says: *"X events imported. Trigger a build to refresh the HTML."*

**Change to:** *"X events imported. Calendar will update in ~2 minutes."* (since the build auto-triggers after Phase 2)

If Phase 2 isn't done yet, keep the current message with the "Trigger Build" button.

---

## Admin User Guide (for someone new)

### Getting Started

1. **Log in** at `https://concert-calendar-eight.vercel.app/admin/login.html`
2. Enter the admin password (ask the project owner if you don't have it)
3. You'll land on the **Events** page — this is the main dashboard

### The Three Admin Pages

The admin has three tabs across the top: **Events**, **Import**, and **Scrapers**.

#### Events Tab — View & Manage All Events

This is where you spend most of your time. It shows every event in the system.

**Searching and filtering:**
- Type in the search box to filter by title or venue
- Use the filter pills: **All** | **Active** | **Inactive** | **Featured** | **Upcoming** | **Past**
- "Active" events appear on the public calendar. "Inactive" ones are hidden.

**Quick actions (no page reload needed):**
- Click the **star** icon to toggle "Featured" — featured events get a gold highlight on the public calendar
- Click the **checkmark/X** icon to toggle "Active" — turning off Active hides the event from the calendar

**Editing an event:**
- Click any row to open the edit form
- Change any fields, then click **Save**
- To hide an event from the calendar, click the red **Deactivate** button at the bottom

**Adding a new event:**
- Click **"+ Add Event"** in the top right
- Fill in at least Title and Date, then click **Save**
- The event immediately appears in the admin and will show on the calendar after the next build

#### Import Tab — Bulk-Add Events from Files

Use this when you have event flyers (images) or HTML pages with event listings.

**Importing images (event flyers):**
1. Drag & drop image files (JPG, PNG, WebP) onto the upload zone, or click to browse
2. Images are committed to the GitHub `artifacts/` folder — you'll see "Committed to GitHub" status
3. Click **"Trigger Build"** — the build pipeline uses AI (Claude Vision) to read the flyer and extract event details
4. After ~2 minutes, the extracted events appear on the calendar
5. Note: artifacts are automatically cleaned up after 24 hours

**Importing HTML files:**
1. Drag & drop `.html` or `.mhtml` files (e.g., saved Bandsintown pages)
2. The system parses them and shows a **preview table** of extracted events
3. Review the events — you can **edit** any field inline (title, venue, date, time)
4. Uncheck any events you don't want to import
5. Click **"Confirm Import"** — events are added to both the database and calendar data
6. Duplicates are automatically detected and skipped

#### Scrapers Tab — Monitor Automated Sources

This shows the status of automated event scrapers (Ticketmaster, venue websites, etc.).

**What you see:**
- Status cards for each scraper — green dot = healthy, red dot = failed, yellow = partial
- A log table of recent scraper runs with counts: found, added, updated, skipped
- Click any log row to expand and see error details

**Buttons:**
- **"Run Scrapers"** (currently "Trigger Build"): Kicks off a full scraper run that fetches new events from all external sources. Takes ~2 minutes. You don't need to press this for your own edits — it's only for pulling in *new* events from Ticketmaster, venue sites, etc.
- **"Refresh"**: Reloads the status cards and logs on this page

### Common Tasks — Step by Step

#### "I need to remove an event from the calendar"

1. Go to **Events** tab
2. Find the event (search or scroll)
3. Click the **X** icon in the "Active" column — it toggles to inactive
4. Done. The calendar updates on the next build (~2 minutes after Phase 2, or click "Run Scrapers" manually before Phase 2).

Alternatively: click the event row → Edit page → click **Deactivate** → confirm.

#### "I want to feature an event (gold highlight)"

1. Go to **Events** tab
2. Find the event
3. Click the **star** icon — it turns gold
4. Done.

#### "I have a flyer image for upcoming shows"

1. Go to **Import** tab
2. Drop the image file(s) onto the upload area
3. Wait for "Committed to GitHub" status
4. Click **"Trigger Build"**
5. Wait ~2 minutes — the AI reads the flyer and adds events automatically

#### "I want to add a show manually"

1. Click **"+ Add Event"** (top right of Events tab)
2. Fill in: Title (required), Venue, Date (required), Start Time
3. Optionally: ticket URL, price, genre, description, image
4. Check "Featured" if you want it highlighted
5. Click **Save**

#### "I imported events and see duplicates"

The system checks for duplicates automatically by matching title + venue + date. If you still see duplicates (different sources may list titles slightly differently):
1. Go to **Events** tab
2. Filter by **Active**
3. Find the duplicate
4. Click its **X** (Active toggle) to deactivate the duplicate

#### "The calendar doesn't reflect my changes"

Before Phase 1 is complete, changes require a few extra steps:
1. Make your edit/delete in the admin
2. Go to **Scrapers** tab
3. Click **"Sync to Calendar"** — this pushes your admin changes to the calendar data file
4. Click **"Trigger Build"** — this regenerates the public HTML

**After Phase 1 (this plan):** Steps 2-4 are eliminated. Your changes sync automatically.

### Understanding the Build Pipeline

The calendar updates through a **build pipeline** that runs automatically twice a day (midnight and noon Central) or when you manually trigger it.

What the build does:
1. Fetches new events from Ticketmaster, venue websites, and other scrapers
2. Merges new events into the central event database (`events.json`)
3. Generates the public HTML calendar page
4. Commits everything to GitHub, which deploys to Vercel

**You don't need to trigger builds for routine edits** (after Phase 1). Builds are mainly for pulling in *new* events from external sources.

### Glossary

| Term | Meaning |
|------|---------|
| **Active** | Event is visible on the public calendar |
| **Inactive** | Event is hidden from the public calendar (soft-deleted) |
| **Featured** | Event gets a gold highlight on the public calendar |
| **events.json** | The central data file that the calendar reads from |
| **Build / Scraper run** | The automated process that fetches new events and regenerates the calendar HTML |
| **Artifacts** | Uploaded images stored temporarily in GitHub for AI processing |
| **Sync** | (Pre-overhaul) Manual step to push admin changes to events.json |
