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
