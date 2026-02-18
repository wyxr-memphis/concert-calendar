# Admin UI Implementation Log

## Overview
Replaced the Google Sheet manual-entry workflow with a `data/events.json` flat file + password-protected admin UI. The daily build merges automated events into events.json, and the admin can add/edit/feature/deactivate any event.

## Architecture
- **events.json** = single source of truth for all events (manual + automated)
- **Daily build** = fetch automated sources → merge into events.json → generate HTML
- **Admin UI** = vanilla HTML+JS at `/admin/` → Python Vercel API routes → GitHub Contents API
- **Auth** = single password → HMAC-SHA256 JWT in httpOnly cookie

## Environment Variables

### Required for Vercel (server-side only)
| Variable | Purpose | Setup |
|----------|---------|-------|
| `ADMIN_PASSWORD` | Login password | Set in Vercel dashboard |
| `ADMIN_SECRET_KEY` | JWT signing key | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GITHUB_PAT` | GitHub Contents API writes | Already exists |

### Optional overrides
| Variable | Default | Purpose |
|----------|---------|---------|
| `GITHUB_OWNER` | `wyxr-memphis` | GitHub repo owner |
| `GITHUB_REPO` | `concert-calendar` | GitHub repo name |
| `GITHUB_FILE_PATH` | `data/events.json` | Path to events file in repo |

## Setup Steps

1. Generate a secret key:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Add to Vercel environment variables:
   - `ADMIN_PASSWORD` = your chosen admin password
   - `ADMIN_SECRET_KEY` = the generated secret key
   - `GITHUB_PAT` = (should already exist)

3. Run migration to populate events.json from current sources:
   ```bash
   python scripts/migrate_to_events_json.py
   ```

4. Deploy and test:
   - Visit `/admin/login.html` and log in
   - Verify events appear in the dashboard
   - Test add/edit/toggle featured/toggle active
   - Verify public calendar shows featured events with gold border

## File Summary

### New files
| File | Purpose |
|------|---------|
| `data/events.json` | Central event database |
| `scripts/migrate_to_events_json.py` | One-time migration |
| `src/sources/events_json.py` | Source reader for build pipeline |
| `api/_auth.py` | JWT helpers (shared module) |
| `api/admin/login.py` | Login endpoint |
| `api/admin/logout.py` | Logout endpoint |
| `api/admin/me.py` | Auth check endpoint |
| `api/admin/events.py` | CRUD endpoint |
| `docs/admin/login.html` | Login page |
| `docs/admin/index.html` | Event list dashboard |
| `docs/admin/edit.html` | Add/edit form |

### Modified files
| File | Change |
|------|--------|
| `src/models.py` | Added `is_featured`, `event_id` fields |
| `src/main.py` | Rewritten to merge into events.json |
| `src/generate_html.py` | Featured CSS class + admin link |
| `.github/workflows/daily.yml` | Git add `data/events.json` |

## Testing Checklist

- [ ] Run migration: `python scripts/migrate_to_events_json.py`
- [ ] Dry run still works: `python -m src.main --dry-run`
- [ ] Login flow works at `/admin/login.html`
- [ ] Event list loads at `/admin/`
- [ ] Add new event via `/admin/edit.html`
- [ ] Edit existing event via `/admin/edit.html?id=evt_...`
- [ ] Toggle featured (star) works
- [ ] Toggle active (checkmark) works
- [ ] Featured events show gold border on public calendar
- [ ] Inactive events hidden from public calendar
- [ ] No secrets in client code: `grep -r "GITHUB_PAT\|ADMIN_SECRET\|ADMIN_PASSWORD" docs/`
