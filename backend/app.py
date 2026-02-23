"""Memphis Concert Calendar — Render Backend API.

Flask application serving public and admin API endpoints.
Connects to PostgreSQL on Render.

Run locally:
    DATABASE_URL=... ADMIN_PASSWORD=... ADMIN_SECRET_KEY=... flask --app backend.app run

Deploy on Render:
    Set environment variables in Render dashboard.
    Start command: gunicorn backend.app:app
"""

import base64
import json
import os
import re
import threading
import uuid
from datetime import datetime

from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import requests as http_requests

from backend.db import (
    init_db,
    get_active_events,
    get_event_by_id,
    get_all_events,
    create_event,
    update_event,
    soft_delete_event,
    toggle_featured,
    bulk_action,
    bulk_insert_events,
    get_scrape_logs,
    get_scraper_status_summary,
)
from backend.auth import (
    ADMIN_PASSWORD,
    create_token,
    require_auth,
)

app = Flask(__name__)

# CORS: allow Vercel frontend and localhost
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=True)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f"Warning: Could not initialize database: {e}")


# ---------------------------------------------------------------------------
# JSON serialization helper
# ---------------------------------------------------------------------------

def serialize_event(row):
    """Convert a database row (RealDictRow) to a JSON-safe dict."""
    if row is None:
        return None
    d = dict(row)
    for key, val in d.items():
        if hasattr(val, "isoformat"):
            d[key] = val.isoformat()
        elif isinstance(val, uuid.UUID):
            d[key] = str(val)
    return d


def serialize_list(rows):
    return [serialize_event(r) for r in rows]


# ---------------------------------------------------------------------------
# events.json write-through helpers
# ---------------------------------------------------------------------------

def _norm_text(text):
    """Normalize text for dedup/matching (title or venue)."""
    t = (text or "").lower().strip()
    t = re.sub(r'^the\s+', '', t)
    t = re.sub(r'\s*(live|concert|tour|show|presents?|featuring|feat\.?|ft\.?)\s*$', '', t)
    t = re.sub(r'[^\w\s]', '', t)
    return re.sub(r'\s+', ' ', t).strip()


def _make_event_key(title, venue, date):
    """Build normalized matching key from title+venue+date."""
    return f"{_norm_text(title)}|{_norm_text(venue)}|{str(date)[:10]}"


def _update_events_json(changes, commit_message="admin: update events"):
    """Update data/events.json on GitHub to reflect admin changes.

    changes: list of dicts with keys:
        action: "upsert" | "deactivate" | "set_featured"
        data: dict with event fields (title, venue, date required)
        match_title, match_venue, match_date: optional overrides for matching
            (used when editing an event whose title/venue/date changed)

    Silently returns on failure — admin operations succeed even if sync fails.
    """
    github_pat = os.environ.get("GITHUB_PAT", "")
    github_repo = os.environ.get("GITHUB_REPO", "wyxr-memphis/concert-calendar")

    if not github_pat:
        print("Warning: GITHUB_PAT not set, skipping events.json sync")
        return

    api_url = f"https://api.github.com/repos/{github_repo}/contents/data/events.json"
    gh_headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        get_resp = http_requests.get(api_url, headers=gh_headers, timeout=10)
        if get_resp.status_code != 200:
            print(f"Warning: Could not fetch events.json: {get_resp.status_code}")
            return

        file_meta = get_resp.json()
        sha = file_meta["sha"]
        events_json = json.loads(base64.b64decode(file_meta["content"]).decode("utf-8"))

        existing = events_json.get("events", [])
        now_iso = datetime.utcnow().isoformat() + "Z"
        modified = False

        for change in changes:
            action = change["action"]
            data = change["data"]

            match_title = change.get("match_title", data.get("title", ""))
            match_venue = change.get("match_venue", data.get("venue", ""))
            match_date = change.get("match_date", str(data.get("date", ""))[:10])
            key = _make_event_key(match_title, match_venue, match_date)

            # Find matching entry in events.json
            match_idx = None
            for i, entry in enumerate(existing):
                entry_key = _make_event_key(
                    entry.get("title", ""),
                    entry.get("venue", ""),
                    entry.get("date", ""),
                )
                if entry_key == key:
                    match_idx = i
                    break

            if action == "deactivate":
                if match_idx is not None:
                    existing[match_idx]["is_active"] = False
                    existing[match_idx]["updated_at"] = now_iso
                    modified = True

            elif action == "set_featured":
                if match_idx is not None:
                    existing[match_idx]["is_featured"] = data.get("is_featured", False)
                    existing[match_idx]["updated_at"] = now_iso
                    modified = True

            elif action == "upsert":
                if match_idx is not None:
                    entry = existing[match_idx]
                    for field in ("title", "venue", "date", "start_time", "doors_time",
                                  "ticket_url", "ticket_price", "image_url",
                                  "description", "genre", "is_featured", "is_active"):
                        if field in data and data[field] is not None:
                            entry[field] = str(data[field])[:10] if field == "date" else data[field]
                    entry["updated_at"] = now_iso
                    modified = True
                else:
                    new_entry = {
                        "id": f"evt_admin_{uuid.uuid4().hex[:12]}",
                        "title": data.get("title", ""),
                        "venue": data.get("venue", ""),
                        "date": str(data.get("date", ""))[:10],
                        "start_time": data.get("start_time"),
                        "doors_time": data.get("doors_time"),
                        "ticket_url": data.get("ticket_url"),
                        "ticket_price": data.get("ticket_price"),
                        "image_url": data.get("image_url"),
                        "description": data.get("description"),
                        "genre": data.get("genre"),
                        "source": data.get("source", "admin"),
                        "is_featured": data.get("is_featured", False),
                        "is_active": data.get("is_active", True),
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    }
                    existing.append(new_entry)
                    modified = True

        if not modified:
            return

        events_json["events"] = existing
        events_json["updated_at"] = now_iso

        updated_content = json.dumps(events_json, indent=2, ensure_ascii=False)
        put_resp = http_requests.put(api_url, headers=gh_headers, json={
            "message": commit_message,
            "content": base64.b64encode(updated_content.encode()).decode("ascii"),
            "sha": sha,
        }, timeout=30)

        if put_resp.status_code not in (200, 201):
            print(f"Warning: events.json commit failed: {put_resp.status_code}")

    except Exception as e:
        print(f"Warning: events.json sync failed: {e}")


def _sync_to_json_background(changes, commit_message):
    """Fire-and-forget events.json sync in a background thread."""
    thread = threading.Thread(
        target=_update_events_json,
        args=(changes, commit_message),
        daemon=True,
    )
    thread.start()


# ---------------------------------------------------------------------------
# Public Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/events", methods=["GET"])
def public_events():
    """Get active events for the public calendar."""
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    featured_only = request.args.get("featured_only", "").lower() == "true"

    events = get_active_events(
        start_date=start_date,
        end_date=end_date,
        featured_only=featured_only,
    )
    return jsonify(serialize_list(events))


@app.route("/api/events/<event_id>", methods=["GET"])
def public_event_detail(event_id):
    """Get a single event by ID (must be active)."""
    event = get_event_by_id(event_id)
    if not event or not event.get("is_active", True):
        return jsonify({"error": "Event not found"}), 404
    return jsonify(serialize_event(event))


# ---------------------------------------------------------------------------
# Auth Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    """Authenticate with admin password, return JWT."""
    if not ADMIN_PASSWORD:
        return jsonify({"error": "ADMIN_PASSWORD not configured"}), 500

    body = request.get_json(silent=True) or {}
    password = body.get("password", "")

    if password != ADMIN_PASSWORD:
        return jsonify({"error": "Invalid password"}), 401

    token = create_token()
    resp = make_response(jsonify({"ok": True, "token": token}))
    resp.set_cookie(
        "admin_token", token,
        httponly=True, secure=True, samesite="None",
        max_age=8 * 60 * 60, path="/",
    )
    return resp


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    """Clear admin token cookie."""
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie(
        "admin_token", "",
        httponly=True, secure=True, samesite="None",
        max_age=0, path="/",
    )
    return resp


@app.route("/api/admin/me", methods=["GET"])
@require_auth
def admin_me():
    """Check if the current token is valid."""
    return jsonify({"ok": True, "user": "admin"})


# ---------------------------------------------------------------------------
# Admin Event Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/admin/events", methods=["GET"])
@require_auth
def admin_events_list():
    """List all events for admin (including inactive)."""
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    include_inactive = request.args.get("include_inactive", "true").lower() != "false"

    events = get_all_events(
        start_date=start_date,
        end_date=end_date,
        include_inactive=include_inactive,
    )
    return jsonify(serialize_list(events))


@app.route("/api/admin/events", methods=["POST"])
@require_auth
def admin_events_create():
    """Create a new event."""
    body = request.get_json(silent=True) or {}

    if not body.get("title") or not body.get("date"):
        return jsonify({"error": "title and date are required"}), 400

    body.setdefault("source", "manual")
    body.setdefault("is_featured", False)
    body.setdefault("is_active", True)

    event = create_event(body)

    _sync_to_json_background([{
        "action": "upsert",
        "data": serialize_event(event),
    }], commit_message=f"admin: add '{event['title']}'")

    return jsonify(serialize_event(event)), 201


@app.route("/api/admin/events/<event_id>", methods=["PUT"])
@require_auth
def admin_events_update(event_id):
    """Full update of an event."""
    body = request.get_json(silent=True) or {}

    existing = get_event_by_id(event_id)
    if not existing:
        return jsonify({"error": "Event not found"}), 404

    event = update_event(event_id, body)

    _sync_to_json_background([{
        "action": "upsert",
        "data": serialize_event(event),
        "match_title": existing["title"],
        "match_venue": existing.get("venue") or "",
        "match_date": str(existing["date"])[:10],
    }], commit_message=f"admin: update '{event['title']}'")

    return jsonify(serialize_event(event))


@app.route("/api/admin/events/<event_id>", methods=["DELETE"])
@require_auth
def admin_events_delete(event_id):
    """Soft-delete an event (set is_active=false)."""
    existing = get_event_by_id(event_id)
    if not existing:
        return jsonify({"error": "Event not found"}), 404

    event = soft_delete_event(event_id)

    _sync_to_json_background([{
        "action": "deactivate",
        "data": serialize_event(event),
    }], commit_message=f"admin: deactivate '{event['title']}'")

    return jsonify({"ok": True, "event": serialize_event(event)})


@app.route("/api/admin/events/<event_id>/featured", methods=["PATCH"])
@require_auth
def admin_events_toggle_featured(event_id):
    """Toggle featured status."""
    body = request.get_json(silent=True) or {}
    is_featured = body.get("is_featured", False)

    existing = get_event_by_id(event_id)
    if not existing:
        return jsonify({"error": "Event not found"}), 404

    event = toggle_featured(event_id, is_featured)

    _sync_to_json_background([{
        "action": "set_featured",
        "data": {"is_featured": is_featured, **serialize_event(event)},
    }], commit_message=f"admin: {'feature' if is_featured else 'unfeature'} '{event['title']}'")

    return jsonify(serialize_event(event))


@app.route("/api/admin/events/bulk", methods=["POST"])
@require_auth
def admin_events_bulk():
    """Bulk operations on events."""
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    ids = body.get("ids", [])

    if action not in ("feature", "unfeature", "deactivate"):
        return jsonify({"error": "action must be feature, unfeature, or deactivate"}), 400

    if not ids:
        return jsonify({"error": "ids array is required"}), 400

    # Fetch events before bulk action for events.json matching
    events_for_sync = []
    for eid in ids:
        evt = get_event_by_id(eid)
        if evt:
            events_for_sync.append(evt)

    count = bulk_action(action, ids)

    # Sync to events.json
    if events_for_sync:
        action_map = {
            "feature": "set_featured",
            "unfeature": "set_featured",
            "deactivate": "deactivate",
        }
        json_action = action_map[action]

        changes = []
        for evt in events_for_sync:
            change = {"action": json_action, "data": serialize_event(evt)}
            if action == "feature":
                change["data"]["is_featured"] = True
            elif action == "unfeature":
                change["data"]["is_featured"] = False
            changes.append(change)

        _sync_to_json_background(
            changes,
            commit_message=f"admin: bulk {action} {len(events_for_sync)} events",
        )

    return jsonify({"ok": True, "affected": count})


# ---------------------------------------------------------------------------
# Import/Upload Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/admin/import/upload", methods=["POST"])
@require_auth
def admin_import_upload():
    """Upload HTML files and/or images for parsing.

    HTML files are parsed to extract event data.
    Image files are committed to the GitHub artifacts/ folder
    for processing by the daily build (Claude Vision API).
    Returns preview data (not saved to DB yet).
    """
    from bs4 import BeautifulSoup

    parsed_events = []
    uploaded_images = []

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files uploaded"}), 400

    github_pat = os.environ.get("GITHUB_PAT", "")
    github_repo = os.environ.get("GITHUB_REPO", "wyxr-memphis/concert-calendar")

    for f in files:
        filename = f.filename or ""
        ext = os.path.splitext(filename)[1].lower()

        if ext in (".html", ".htm", ".mhtml"):
            # Parse HTML for events
            raw_content = f.read()
            if ext == ".mhtml":
                # MHTML uses quoted-printable encoding; extract the HTML part
                import email as _email
                try:
                    msg = _email.message_from_bytes(raw_content)
                    content = ""
                    for part in msg.walk():
                        if part.get_content_type() == "text/html":
                            payload = part.get_payload(decode=True)
                            if payload:
                                charset = part.get_content_charset("utf-8") or "utf-8"
                                content = payload.decode(charset, errors="replace")
                                break
                    if not content:
                        content = raw_content.decode("utf-8", errors="replace")
                except Exception:
                    content = raw_content.decode("utf-8", errors="replace")
            else:
                content = raw_content.decode("utf-8", errors="replace")
            soup = BeautifulSoup(content, "html.parser")
            events = _parse_html_events(soup, filename)
            parsed_events.extend(events)

        elif ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            # Commit image to GitHub artifacts/ folder for build processing
            file_data = f.read()
            safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_ ").strip()
            if not safe_name:
                safe_name = f"upload_{uuid.uuid4().hex[:8]}{ext}"

            if not github_pat:
                uploaded_images.append({
                    "filename": safe_name,
                    "status": "error",
                    "error": "GITHUB_PAT not configured",
                })
                continue

            github_path = f"artifacts/{safe_name}"
            api_url = f"https://api.github.com/repos/{github_repo}/contents/{github_path}"
            gh_headers = {
                "Authorization": f"Bearer {github_pat}",
                "Accept": "application/vnd.github.v3+json",
            }

            # Check if file already exists (to get SHA for update)
            sha = None
            existing = http_requests.get(api_url, headers=gh_headers, timeout=10)
            if existing.status_code == 200:
                sha = existing.json().get("sha")

            put_data = {
                "message": f"Upload artifact: {safe_name}",
                "content": base64.b64encode(file_data).decode("ascii"),
            }
            if sha:
                put_data["sha"] = sha

            resp = http_requests.put(api_url, headers=gh_headers, json=put_data, timeout=30)

            if resp.status_code in (200, 201):
                uploaded_images.append({
                    "filename": safe_name,
                    "status": "committed",
                })
            else:
                uploaded_images.append({
                    "filename": safe_name,
                    "status": "error",
                    "error": f"GitHub API returned {resp.status_code}",
                })

    return jsonify({
        "parsed_events": parsed_events,
        "uploaded_images": uploaded_images,
    })


def _normalize_date_iso(date_str):
    """Convert a human-readable date string to ISO YYYY-MM-DD format."""
    if not date_str:
        return None
    # Already ISO
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str.strip()):
        return date_str.strip()
    # Strip any trailing time like " - 7:00 PM"
    cleaned = re.sub(r'\s*[-–]?\s*\d{1,2}:\d{2}\s*(?:AM|PM)', '', date_str, flags=re.IGNORECASE).strip()
    # Try parsing
    current_year = datetime.now().year
    for fmt in ('%b %d', '%B %d', '%b %d %Y', '%B %d %Y', '%m/%d/%Y', '%m/%d/%y'):
        try:
            dt = datetime.strptime(cleaned, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=current_year)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None  # reject unparseable dates rather than pass bad data to DB


@app.route("/api/admin/import/confirm", methods=["POST"])
@require_auth
def admin_import_confirm():
    """Confirm and save parsed events to the database and events.json."""
    body = request.get_json(silent=True) or {}
    events_to_import = body.get("events", [])

    if not events_to_import:
        return jsonify({"error": "No events to import"}), 400

    valid = []
    skipped = []
    for evt in events_to_import:
        evt.setdefault("source", "import")
        evt.setdefault("is_featured", False)
        evt.setdefault("is_active", True)
        iso_date = _normalize_date_iso(evt.get("date", ""))
        if not iso_date:
            skipped.append(evt.get("title", "?"))
            continue
        evt["date"] = iso_date
        valid.append(evt)

    if not valid:
        return jsonify({"error": "No events with valid dates to import", "skipped": skipped}), 400

    # Save to PostgreSQL
    created = bulk_insert_events(valid)

    # Also write to data/events.json on GitHub so the static calendar picks them up
    github_pat = os.environ.get("GITHUB_PAT", "")
    github_repo = os.environ.get("GITHUB_REPO", "wyxr-memphis/concert-calendar")
    json_warning = None
    duplicates = []

    if github_pat:
        api_url = f"https://api.github.com/repos/{github_repo}/contents/data/events.json"
        gh_headers = {
            "Authorization": f"Bearer {github_pat}",
            "Accept": "application/vnd.github.v3+json",
        }
        try:
            # Fetch current events.json
            get_resp = http_requests.get(api_url, headers=gh_headers, timeout=10)
            if get_resp.status_code == 200:
                file_meta = get_resp.json()
                sha = file_meta["sha"]
                current = base64.b64decode(file_meta["content"]).decode("utf-8")
                events_json = json.loads(current)
            else:
                sha = None
                events_json = {"version": 1, "updated_at": "", "events": []}

            now_iso = datetime.utcnow().isoformat() + "Z"
            existing = events_json.get("events", [])

            # Build dedup key set from existing entries
            existing_keys = {
                _make_event_key(e.get('title',''), e.get('venue',''), e.get('date',''))
                for e in existing
            }

            duplicates = []
            for evt in valid:
                key = _make_event_key(evt.get('title',''), evt.get('venue',''), evt['date'])
                if key in existing_keys:
                    duplicates.append(evt.get("title", "?"))
                    continue
                existing_keys.add(key)
                entry = {
                    "id": f"evt_import_{uuid.uuid4().hex[:12]}",
                    "title": evt.get("title", ""),
                    "venue": evt.get("venue", ""),
                    "date": evt["date"],
                    "start_time": evt.get("start_time") or None,
                    "doors_time": None,
                    "ticket_url": evt.get("ticket_url") or None,
                    "ticket_price": None,
                    "image_url": None,
                    "description": None,
                    "genre": None,
                    "source": evt.get("source", "import"),
                    "is_featured": False,
                    "is_active": True,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                }
                existing.append(entry)

            events_json["events"] = existing
            events_json["updated_at"] = now_iso

            updated = json.dumps(events_json, indent=2, ensure_ascii=False)
            added_count = len(valid) - len(duplicates)
            put_data = {
                "message": f"Import {added_count} events via admin",
                "content": base64.b64encode(updated.encode()).decode("ascii"),
            }
            if sha:
                put_data["sha"] = sha

            put_resp = http_requests.put(api_url, headers=gh_headers, json=put_data, timeout=30)
            if put_resp.status_code not in (200, 201):
                json_warning = f"Saved to DB but could not update events.json (GitHub {put_resp.status_code})"
        except Exception as e:
            json_warning = f"Saved to DB but could not update events.json: {str(e)[:100]}"
    else:
        json_warning = "GITHUB_PAT not set — events saved to DB only, trigger a build to update the calendar"

    result = {
        "ok": True,
        "imported": len(created),
        "skipped": skipped,
        "duplicates": duplicates,
    }
    if json_warning:
        result["warning"] = json_warning
    return jsonify(result)


@app.route("/api/admin/import/image", methods=["POST"])
@require_auth
def admin_import_image():
    """Single image upload — commits to GitHub artifacts/ folder."""
    f = request.files.get("image")
    if not f:
        return jsonify({"error": "No image file provided"}), 400

    filename = f.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return jsonify({"error": f"File type {ext} not allowed"}), 400

    github_pat = os.environ.get("GITHUB_PAT", "")
    github_repo = os.environ.get("GITHUB_REPO", "wyxr-memphis/concert-calendar")

    if not github_pat:
        return jsonify({"error": "GITHUB_PAT not configured"}), 500

    file_data = f.read()
    safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_ ").strip()
    if not safe_name:
        safe_name = f"img_{uuid.uuid4().hex[:8]}{ext}"

    github_path = f"artifacts/{safe_name}"
    api_url = f"https://api.github.com/repos/{github_repo}/contents/{github_path}"
    gh_headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github.v3+json",
    }

    sha = None
    existing = http_requests.get(api_url, headers=gh_headers, timeout=10)
    if existing.status_code == 200:
        sha = existing.json().get("sha")

    put_data = {
        "message": f"Upload artifact: {safe_name}",
        "content": base64.b64encode(file_data).decode("ascii"),
    }
    if sha:
        put_data["sha"] = sha

    resp = http_requests.put(api_url, headers=gh_headers, json=put_data, timeout=30)

    if resp.status_code in (200, 201):
        return jsonify({"ok": True, "filename": safe_name})
    else:
        return jsonify({"error": f"GitHub API returned {resp.status_code}"}), 502


# ---------------------------------------------------------------------------
# Scraper Status Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/admin/scraper/logs", methods=["GET"])
@require_auth
def admin_scraper_logs():
    """Get recent scrape log entries."""
    limit = request.args.get("limit", 20, type=int)
    scraper_name = request.args.get("scraper_name")

    logs = get_scrape_logs(limit=limit, scraper_name=scraper_name)
    return jsonify(serialize_list(logs))


@app.route("/api/admin/scraper/status", methods=["GET"])
@require_auth
def admin_scraper_status():
    """Get scraper status dashboard summary."""
    summary = get_scraper_status_summary()
    return jsonify(summary)


# ---------------------------------------------------------------------------
# HTML parsing helpers for import
# ---------------------------------------------------------------------------

def _parse_html_events(soup, source_filename):
    """Extract events from parsed HTML. Returns list of dicts."""
    events = []

    # Strategy 1: JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in ("Event", "MusicEvent"):
                    evt = _parse_jsonld_event(item, source_filename)
                    if evt:
                        events.append(evt)
        except (json.JSONDecodeError, Exception):
            continue

    if events:
        return events

    # Strategy 2: Common event listing patterns
    selectors = [
        ".event-item", ".event-card", ".event-listing",
        "[class*='event-item']", "[class*='eventItem']",
        "article[class*='event']",
        ".tribe-events-list-event", ".eventlist-event",
    ]
    for selector in selectors:
        listings = soup.select(selector)
        if listings:
            for listing in listings:
                title_el = listing.select_one("h2, h3, h4, [class*='title']")
                date_el = listing.select_one("time, [class*='date']")
                venue_el = listing.select_one("[class*='venue'], [class*='location']")

                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                event_date = None
                if date_el:
                    dt_attr = date_el.get("datetime")
                    if dt_attr:
                        try:
                            event_date = datetime.fromisoformat(
                                dt_attr.replace("Z", "+00:00")
                            ).date().isoformat()
                        except ValueError:
                            pass
                    if not event_date:
                        event_date = date_el.get_text(strip=True)

                venue = venue_el.get_text(strip=True) if venue_el else ""

                events.append({
                    "title": title,
                    "venue": venue,
                    "date": event_date or "",
                    "source": f"import ({source_filename})",
                })

            if events:
                return events

    # Strategy 3: Bandsintown-style links
    event_links = soup.find_all("a", href=lambda h: h and "/e/" in str(h))
    for link in event_links:
        text = link.get_text(separator="|", strip=True)
        parts = [p.strip() for p in text.split("|") if p.strip()]
        if len(parts) >= 3:
            date_str = None
            time_str = None
            for part in parts:
                if re.search(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d', part):
                    # Extract time if present: "Feb 23 - 7:00 PM"
                    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', part, re.IGNORECASE)
                    if time_match:
                        time_str = time_match.group(1)
                        date_str = re.sub(r'\s*[-–]?\s*\d{1,2}:\d{2}\s*(?:AM|PM)', '', part, flags=re.IGNORECASE).strip()
                    else:
                        date_str = part
                    break

            evt = {
                "title": parts[0],
                "venue": parts[1] if len(parts) > 2 else "",
                "date": date_str or "",
                "ticket_url": link.get("href", ""),
                "source": f"import ({source_filename})",
            }
            if time_str:
                evt["start_time"] = time_str
            events.append(evt)

    return events


def _parse_jsonld_event(data, source_filename):
    """Parse a JSON-LD Event object into a dict."""
    name = data.get("name", "").strip()
    start_date = data.get("startDate", "")
    if not name or not start_date:
        return None

    try:
        dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        event_date = dt.date().isoformat()
        time_str = dt.strftime("%-I:%M %p").replace(":00 ", " ")
    except ValueError:
        event_date = start_date
        time_str = None

    location = data.get("location", {})
    venue = location.get("name", "") if isinstance(location, dict) else ""
    url = data.get("url")

    result = {
        "title": name,
        "venue": venue,
        "date": event_date,
        "source": f"import ({source_filename})",
    }
    if time_str:
        result["start_time"] = time_str
    if url:
        result["ticket_url"] = url
    return result


# ---------------------------------------------------------------------------
# Calendar Sync
# ---------------------------------------------------------------------------

@app.route("/api/admin/sync", methods=["POST"])
@require_auth
def admin_sync_events_json():
    """Sync inactive PostgreSQL events to events.json.

    Finds all events marked is_active=false in the DB, locates matching
    entries in data/events.json by normalized title+venue+date, and marks
    them inactive so the next build excludes them.
    """
    github_pat = os.environ.get("GITHUB_PAT", "")
    github_repo = os.environ.get("GITHUB_REPO", "wyxr-memphis/concert-calendar")

    if not github_pat:
        return jsonify({"error": "GITHUB_PAT not configured"}), 500

    # Get all events from PostgreSQL (active + inactive)
    all_db = get_all_events(include_inactive=True)

    if not all_db:
        return jsonify({"ok": True, "synced": 0, "message": "No events in DB"})

    # Build maps: key → is_active status
    db_status = {}
    for e in all_db:
        key = f"{_norm_text(e.get('title',''))}|{_norm_text(e.get('venue',''))}|{str(e.get('date',''))[:10]}"
        # If any DB event with this key is active, treat it as active
        if key not in db_status:
            db_status[key] = bool(e.get("is_active", True))
        elif e.get("is_active", True):
            db_status[key] = True

    # Fetch events.json from GitHub
    api_url = f"https://api.github.com/repos/{github_repo}/contents/data/events.json"
    gh_headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github.v3+json",
    }
    get_resp = http_requests.get(api_url, headers=gh_headers, timeout=10)
    if get_resp.status_code != 200:
        return jsonify({"error": f"Could not fetch events.json: {get_resp.status_code}"}), 502

    file_meta = get_resp.json()
    sha = file_meta["sha"]
    events_json = json.loads(base64.b64decode(file_meta["content"]).decode("utf-8"))

    synced = 0
    for entry in events_json.get("events", []):
        key = f"{_norm_text(entry.get('title',''))}|{_norm_text(entry.get('venue',''))}|{entry.get('date','')}"
        if key not in db_status:
            continue  # scraper-only event — don't touch it
        db_active = db_status[key]
        if entry.get("is_active", True) != db_active:
            entry["is_active"] = db_active
            synced += 1

    if synced == 0:
        return jsonify({"ok": True, "synced": 0, "message": "events.json already in sync with DB"})

    updated = json.dumps(events_json, indent=2, ensure_ascii=False)
    put_resp = http_requests.put(api_url, headers=gh_headers, json={
        "message": f"Sync: deactivate {synced} deleted events",
        "content": base64.b64encode(updated.encode()).decode("ascii"),
        "sha": sha,
    }, timeout=30)

    if put_resp.status_code in (200, 201):
        return jsonify({"ok": True, "synced": synced})
    else:
        return jsonify({"error": f"GitHub API returned {put_resp.status_code}"}), 502


# ---------------------------------------------------------------------------
# Build Trigger
# ---------------------------------------------------------------------------

@app.route("/api/admin/build/trigger", methods=["POST"])
@require_auth
def admin_trigger_build():
    """Trigger the daily build workflow via GitHub Actions API."""

    github_pat = os.environ.get("GITHUB_PAT", "")
    github_repo = os.environ.get("GITHUB_REPO", "wyxr-memphis/concert-calendar")

    if not github_pat:
        return jsonify({"error": "GITHUB_PAT not configured"}), 500

    resp = http_requests.post(
        f"https://api.github.com/repos/{github_repo}/actions/workflows/daily.yml/dispatches",
        headers={
            "Authorization": f"Bearer {github_pat}",
            "Accept": "application/vnd.github.v3+json",
        },
        json={"ref": "main"},
        timeout=10,
    )

    if resp.status_code == 204:
        return jsonify({"ok": True, "message": "Build triggered"})
    else:
        return jsonify({"error": f"GitHub API returned {resp.status_code}"}), 502


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
