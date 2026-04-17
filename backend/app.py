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
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify, make_response
from flask_cors import CORS, cross_origin
from flask_compress import Compress
import requests as http_requests

from backend.db import (
    init_db,
    get_cursor,
    get_active_events,
    get_event_by_id,
    get_all_events,
    create_event,
    update_event,
    soft_delete_event,
    toggle_featured,
    toggle_wyxr_presents,
    bulk_action,
    bulk_insert_events,
    is_fuzzy_duplicate,
    delete_events_before,
    get_scrape_logs,
    get_scraper_status_summary,
    get_all_venues,
    get_unmapped_venues,
    dismiss_venue_name,
    get_venue_by_id,
    create_venue,
    update_venue,
    delete_venue,
    merge_venues,
    normalize_venue_from_db,
    get_neighborhoods_with_counts,
    backfill_neighborhoods,
    create_submission,
    get_submissions,
    get_submission_by_id,
    update_submission_status,
    delete_submission,
    get_pending_submission_count,
    get_active_sponsors,
    get_all_sponsors,
    get_sponsor_by_id,
    create_sponsor,
    update_sponsor,
    delete_sponsor,
    get_active_calendar_sponsor,
    get_all_calendar_sponsors,
    get_calendar_sponsor_by_id,
    create_calendar_sponsor,
    update_calendar_sponsor,
    delete_calendar_sponsor,
    get_api_key,
    create_api_key,
    list_api_keys,
    update_api_key,
    log_api_request,
    get_api_key_usage,
    get_v1_events,
    create_api_key_request,
    list_api_key_requests,
    update_api_key_request,
    health_events_14d,
    health_recent_build_logs,
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

# Gzip/brotli compression for JSON responses (~70% reduction)
Compress(app)


# ---------------------------------------------------------------------------
# Startup — DB init is deferred so the app can bind the port immediately.
# Render's port scanner needs a fast response; a slow DB connect can cause
# "No open HTTP ports detected" → restart loops.
# ---------------------------------------------------------------------------

_db_ready = False

print("[startup] App loaded (DB init deferred to first request)", flush=True)


@app.before_request
def _ensure_db():
    global _db_ready
    if _db_ready:
        return
    # Skip DB init for health/root check — must respond instantly
    if request.path in ("/health", "/"):
        return
    try:
        print("[startup] Connecting to database...", flush=True)
        init_db()
        _db_ready = True
        print("[startup] Database initialized OK", flush=True)
    except Exception as e:
        # Leave _db_ready False so the next request retries initialization
        print(f"[startup] WARNING: Could not initialize database: {e}", flush=True)


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
    resp = jsonify(serialize_list(events))
    resp.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
    return resp


@app.route("/api/events/<event_id>", methods=["GET"])
def public_event_detail(event_id):
    """Get a single event by ID (must be active)."""
    event = get_event_by_id(event_id)
    if not event or not event.get("is_active", True):
        return jsonify({"error": "Event not found"}), 404
    return jsonify(serialize_event(event))


@app.route("/api/neighborhoods", methods=["GET"])
def public_neighborhoods():
    """Get neighborhoods with event counts."""
    rows = get_neighborhoods_with_counts()
    resp = jsonify([
        {"name": r["neighborhood"], "event_count": r["event_count"]}
        for r in rows
    ])
    resp.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
    return resp


# ---------------------------------------------------------------------------
# Slack Notifications
# ---------------------------------------------------------------------------

def _notify_slack_new_submission(artist_name, venue, event_date, event_time, submitter_name, description=None):
    """Post a new submission notification to Slack. Fails silently."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return

    time_str = f" at {event_time}" if event_time else ""
    desc_str = f"\n> {description}" if description else ""
    admin_url = "https://concert-calendar.wyxr.org/admin/#submissions"

    text = (
        f":musical_note: *New event submission needs review*\n"
        f"*Artist:* {artist_name}\n"
        f"*Venue:* {venue}\n"
        f"*Date:* {event_date}{time_str}\n"
        f"*Submitted by:* {submitter_name}"
        f"{desc_str}\n"
        f"<{admin_url}|Review in Admin UI>"
    )

    try:
        http_requests.post(webhook_url, json={"text": text}, timeout=5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public Submission Endpoint
# ---------------------------------------------------------------------------

@app.route("/api/submissions", methods=["POST"])
def public_submit_event():
    """Accept a community event submission."""
    body = request.get_json(silent=True) or {}

    # Honeypot check — silently discard but return success
    if body.get("website", "").strip():
        return jsonify({
            "success": True,
            "message": "Event submitted successfully. It will appear on the calendar after review.",
        })

    # Validation
    errors = []
    artist_name = (body.get("artist_name") or "").strip()
    venue = (body.get("venue") or "").strip()
    event_date = (body.get("event_date") or "").strip()
    event_time = (body.get("event_time") or "").strip() or None
    description = (body.get("description") or "").strip() or None
    submitter_name = (body.get("submitter_name") or "").strip()
    submitter_email = (body.get("submitter_email") or "").strip()

    if not artist_name:
        errors.append("Artist / band name is required")
    elif len(artist_name) > 200:
        errors.append("Artist name must be 200 characters or less")

    if not venue:
        errors.append("Venue is required")
    elif len(venue) > 200:
        errors.append("Venue must be 200 characters or less")

    if not event_date:
        errors.append("Event date is required")
    else:
        try:
            from datetime import date as _date
            parsed_date = _date.fromisoformat(event_date)
            if parsed_date < _date.today():
                errors.append("Event date must be today or in the future")
        except ValueError:
            errors.append("Invalid date format")

    if not submitter_name:
        errors.append("Your name is required")
    elif len(submitter_name) > 100:
        errors.append("Name must be 100 characters or less")

    if not submitter_email:
        errors.append("Email is required")
    elif "@" not in submitter_email or "." not in submitter_email:
        errors.append("Please enter a valid email address")

    if description and len(description) > 500:
        errors.append("Description must be 500 characters or less")

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    # Save
    create_submission({
        "artist_name": artist_name,
        "venue": venue,
        "event_date": event_date,
        "event_time": event_time,
        "description": description,
        "submitter_name": submitter_name,
        "submitter_email": submitter_email,
        "honeypot": body.get("website", ""),
    })

    _notify_slack_new_submission(
        artist_name, venue, event_date, event_time, submitter_name, description
    )

    return jsonify({
        "success": True,
        "message": "Event submitted successfully. It will appear on the calendar after review.",
    })


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

    if not hmac.compare_digest(password, ADMIN_PASSWORD):
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
    return jsonify(serialize_event(event)), 201


@app.route("/api/admin/events/<event_id>", methods=["PUT"])
@require_auth
def admin_events_update(event_id):
    """Full update of an event. Promotes source to 'manual' (admin-edited = protected)."""
    body = request.get_json(silent=True) or {}

    existing = get_event_by_id(event_id)
    if not existing:
        return jsonify({"error": "Event not found"}), 404

    # Admin edits promote event to "manual" source (protected from scraper overwrite)
    body["source"] = "manual"

    event = update_event(event_id, body)
    return jsonify(serialize_event(event))


@app.route("/api/admin/events/<event_id>", methods=["DELETE"])
@require_auth
def admin_events_delete(event_id):
    """Soft-delete an event (set is_active=false)."""
    existing = get_event_by_id(event_id)
    if not existing:
        return jsonify({"error": "Event not found"}), 404

    event = soft_delete_event(event_id)
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
    return jsonify(serialize_event(event))


@app.route("/api/admin/events/<event_id>/presents", methods=["PATCH"])
@require_auth
def admin_events_toggle_presents(event_id):
    """Toggle WYXR Presents status."""
    body = request.get_json(silent=True) or {}
    is_wyxr_presents = body.get("is_wyxr_presents", False)

    existing = get_event_by_id(event_id)
    if not existing:
        return jsonify({"error": "Event not found"}), 404

    event = toggle_wyxr_presents(event_id, is_wyxr_presents)
    return jsonify(serialize_event(event))


@app.route("/api/admin/events/bulk", methods=["POST"])
@require_auth
def admin_events_bulk():
    """Bulk operations on events."""
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    ids = body.get("ids", [])

    if action not in ("feature", "unfeature", "presents", "unpresents", "deactivate"):
        return jsonify({"error": "action must be feature, unfeature, presents, unpresents, or deactivate"}), 400

    if not ids:
        return jsonify({"error": "ids array is required"}), 400

    count = bulk_action(action, ids)
    return jsonify({"ok": True, "affected": count})


# ---------------------------------------------------------------------------
# Public Venue List (for submit form)
# ---------------------------------------------------------------------------

@app.route("/api/venues", methods=["GET"])
def public_venues_list():
    """Public list of venue names for the submit form autocomplete."""
    venues = get_all_venues()
    return jsonify([v["name"] for v in venues])


# Admin Venue Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/admin/venues", methods=["GET"])
@require_auth
def admin_venues_list():
    """List all venues with neighborhoods and event counts."""
    venues = get_all_venues()
    return jsonify(serialize_list(venues))


@app.route("/api/admin/venues/unmapped", methods=["GET"])
@require_auth
def admin_venues_unmapped():
    """List venue names from events that aren't in the venues table."""
    rows = get_unmapped_venues()
    return jsonify(serialize_list(rows))


@app.route("/api/admin/venues", methods=["POST"])
@require_auth
def admin_venues_create():
    """Create a new venue."""
    body = request.get_json(silent=True) or {}
    if not body.get("name"):
        return jsonify({"error": "name is required"}), 400

    try:
        venue = create_venue(body)
        return jsonify(serialize_event(venue)), 201
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            return jsonify({"error": "A venue with that name already exists"}), 409
        raise


@app.route("/api/admin/venues/<venue_id>", methods=["PUT"])
@require_auth
def admin_venues_update(venue_id):
    """Update a venue's name, neighborhood, or aliases."""
    body = request.get_json(silent=True) or {}

    # Get old venue data before update (for rename propagation)
    from backend.db import get_cursor, get_venue_by_id as _get_venue
    old_venue = _get_venue(venue_id)
    if not old_venue:
        return jsonify({"error": "Venue not found"}), 404

    venue = update_venue(venue_id, body)

    # Propagate changes to events
    with get_cursor() as cur:
        # If name changed, update all events with old name → new name
        if "name" in body and body["name"] != old_venue["name"]:
            cur.execute(
                """UPDATE events SET venue = %s, updated_at = NOW()
                   WHERE LOWER(venue) = LOWER(%s)""",
                (body["name"], old_venue["name"]),
            )
            # Also add old name to aliases if not already there
            aliases = list(venue.get("aliases") or [])
            if old_venue["name"].lower() not in [a.lower() for a in aliases]:
                aliases.append(old_venue["name"])
                update_venue(venue_id, {"aliases": aliases})

        # If neighborhood changed, update matching events
        if "neighborhood" in body:
            cur.execute(
                """UPDATE events SET neighborhood = %s, updated_at = NOW()
                   WHERE LOWER(venue) = LOWER(%s)""",
                (body["neighborhood"], venue["name"]),
            )

    return jsonify(serialize_event(update_venue(venue_id, {}) or venue))


@app.route("/api/admin/venues/<venue_id>", methods=["DELETE"])
@require_auth
def admin_venues_delete(venue_id):
    """Delete a venue."""
    venue = delete_venue(venue_id)
    if not venue:
        return jsonify({"error": "Venue not found"}), 404
    return jsonify({"ok": True, "venue": serialize_event(venue)})


@app.route("/api/admin/venues/merge", methods=["POST"])
@require_auth
def admin_venues_merge():
    """Merge two venues. keep_id absorbs merge_id."""
    body = request.get_json(silent=True) or {}
    keep_id = body.get("keep_id")
    merge_id = body.get("merge_id")

    if not keep_id or not merge_id:
        return jsonify({"error": "keep_id and merge_id are required"}), 400
    if keep_id == merge_id:
        return jsonify({"error": "Cannot merge a venue into itself"}), 400

    result = merge_venues(keep_id, merge_id)
    if not result:
        return jsonify({"error": "One or both venues not found"}), 404

    return jsonify({"ok": True, **result})


@app.route("/api/admin/venues/backfill", methods=["POST"])
@require_auth
def admin_venues_backfill():
    """Backfill neighborhoods on existing events based on venue names."""
    result = backfill_neighborhoods()
    return jsonify({"ok": True, **result})


@app.route("/api/admin/venues/dismiss", methods=["POST"])
@require_auth
def admin_venues_dismiss():
    """Dismiss an unmapped venue name (mark it as not a real venue).

    The name will re-appear if new events are imported with that venue name after this call.
    """
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    dismiss_venue_name(name)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Admin Submission Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/admin/submissions", methods=["GET"])
@require_auth
def admin_submissions_list():
    """List submissions, optionally filtered by status."""
    status = request.args.get("status")
    submissions = get_submissions(status=status)
    return jsonify({
        "submissions": serialize_list(submissions),
        "count": len(submissions),
    })


@app.route("/api/admin/submissions/pending-count", methods=["GET"])
@require_auth
def admin_submissions_pending_count():
    """Get count of pending submissions (for badge)."""
    count = get_pending_submission_count()
    return jsonify({"count": count})


@app.route("/api/admin/submissions/<int:submission_id>/approve", methods=["POST"])
@require_auth
def admin_submission_approve(submission_id):
    """Approve a submission — creates a real event."""
    sub = get_submission_by_id(submission_id)
    if not sub:
        return jsonify({"error": "Submission not found"}), 404
    if sub["status"] != "pending":
        return jsonify({"error": f"Submission already {sub['status']}"}), 400

    # Create the event using the same logic as admin "Add Event"
    event_data = {
        "title": sub["artist_name"],
        "venue": sub["venue"],
        "date": sub["event_date"].isoformat() if hasattr(sub["event_date"], "isoformat") else sub["event_date"],
        "source": "submission",
        "is_active": True,
        "is_featured": False,
    }
    if sub.get("event_time"):
        t = sub["event_time"]
        if hasattr(t, "strftime"):
            event_data["start_time"] = t.strftime("%-I:%M %p").replace(":00 ", " ")
        else:
            event_data["start_time"] = str(t)
    if sub.get("description"):
        event_data["description"] = sub["description"]

    # Look up venue neighborhood from DB
    venue_match = normalize_venue_from_db(sub["venue"])
    if venue_match:
        event_data["venue"] = venue_match[0]  # canonical name
        if venue_match[1]:
            event_data["neighborhood"] = venue_match[1]

    event = create_event(event_data)
    event_id = str(event["id"]) if event else None

    # Mark submission as approved
    update_submission_status(submission_id, "approved", created_event_id=event_id)

    return jsonify(serialize_event(event)), 201


@app.route("/api/admin/submissions/<int:submission_id>/mark-approved", methods=["POST"])
@require_auth
def admin_submission_mark_approved(submission_id):
    """Mark a submission as approved without creating an event.

    Used by the "Edit & Approve" flow where the event is created
    separately via the event edit form.
    """
    sub = get_submission_by_id(submission_id)
    if not sub:
        return jsonify({"error": "Submission not found"}), 404

    created_event_id = (request.get_json(silent=True) or {}).get("event_id")
    update_submission_status(submission_id, "approved", created_event_id=created_event_id)
    return jsonify({"success": True, "message": "Submission marked as approved"})


@app.route("/api/admin/submissions/<int:submission_id>/reject", methods=["POST"])
@require_auth
def admin_submission_reject(submission_id):
    """Reject a submission (soft-delete)."""
    sub = get_submission_by_id(submission_id)
    if not sub:
        return jsonify({"error": "Submission not found"}), 404

    update_submission_status(submission_id, "rejected")
    return jsonify({"success": True, "message": "Submission rejected"})


@app.route("/api/admin/submissions/<int:submission_id>", methods=["DELETE"])
@require_auth
def admin_submission_delete(submission_id):
    """Hard-delete a submission."""
    sub = delete_submission(submission_id)
    if not sub:
        return jsonify({"error": "Submission not found"}), 404
    return jsonify({"success": True, "message": "Submission deleted"})


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
    """Confirm and save parsed events to the database."""
    body = request.get_json(silent=True) or {}
    events_to_import = body.get("events", [])

    if not events_to_import:
        return jsonify({"error": "No events to import"}), 400

    valid = []
    skipped = []
    for evt in events_to_import:
        evt.setdefault("source", "artifact")
        evt.setdefault("is_featured", False)
        evt.setdefault("is_active", True)
        iso_date = _normalize_date_iso(evt.get("date", ""))
        if not iso_date:
            skipped.append(evt.get("title", "?"))
            continue
        evt["date"] = iso_date
        if is_fuzzy_duplicate(evt.get("title", ""), evt.get("venue", ""), iso_date):
            skipped.append(evt.get("title", "?"))
            continue
        valid.append(evt)

    if not valid:
        return jsonify({"error": "No events with valid dates to import", "skipped": skipped}), 400

    # Save to PostgreSQL
    created = bulk_insert_events(valid)

    return jsonify({
        "ok": True,
        "imported": len(created),
        "skipped": skipped,
    })


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
# Sponsor Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/sponsors", methods=["GET"])
def public_sponsors():
    """Get active sponsors for today (public, no auth)."""
    from datetime import date
    today = date.today()
    sponsors = get_active_sponsors(today)
    resp = jsonify(serialize_list(sponsors))
    resp.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
    return resp


@app.route("/api/admin/sponsors", methods=["GET"])
@require_auth
def admin_sponsors_list():
    """List all sponsors for admin view."""
    sponsors = get_all_sponsors()
    return jsonify(serialize_list(sponsors))


@app.route("/api/admin/sponsors", methods=["POST"])
@require_auth
def admin_sponsors_create():
    """Create a new sponsor."""
    body = request.get_json(silent=True) or {}
    required = ["name", "image_url", "display_after_date", "start_date", "end_date"]
    for field in required:
        if not body.get(field):
            return jsonify({"error": f"{field} is required"}), 400
    sponsor = create_sponsor(body)
    return jsonify(serialize_event(sponsor)), 201


@app.route("/api/admin/sponsors/<sponsor_id>", methods=["PUT"])
@require_auth
def admin_sponsors_update(sponsor_id):
    """Update a sponsor."""
    body = request.get_json(silent=True) or {}
    sponsor = get_sponsor_by_id(sponsor_id)
    if not sponsor:
        return jsonify({"error": "Sponsor not found"}), 404
    updated = update_sponsor(sponsor_id, body)
    return jsonify(serialize_event(updated))


@app.route("/api/admin/sponsors/<sponsor_id>", methods=["DELETE"])
@require_auth
def admin_sponsors_delete(sponsor_id):
    """Hard-delete a sponsor."""
    sponsor = delete_sponsor(sponsor_id)
    if not sponsor:
        return jsonify({"error": "Sponsor not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/admin/sponsors/upload-image", methods=["POST"])
@require_auth
def admin_sponsors_upload_image():
    """Upload a sponsor image to docs/sponsors/ in GitHub repo."""
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

    import re as _re
    file_data = f.read()
    # Sanitize: timestamp prefix + alphanumeric/hyphen only — no spaces or special chars
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    base = os.path.splitext(filename)[0]
    clean_base = _re.sub(r'[^a-zA-Z0-9-]', '_', base)
    clean_base = _re.sub(r'_+', '_', clean_base).strip('_') or "sponsor"
    safe_name = f"{ts}_{clean_base}{ext}"

    github_path = f"docs/sponsors/{safe_name}"
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
        "message": f"Upload sponsor image: {safe_name}",
        "content": base64.b64encode(file_data).decode("ascii"),
    }
    if sha:
        put_data["sha"] = sha

    resp = http_requests.put(api_url, headers=gh_headers, json=put_data, timeout=30)

    if resp.status_code in (200, 201):
        image_url = f"https://concert-calendar.wyxr.org/sponsors/{safe_name}"
        return jsonify({"ok": True, "filename": safe_name, "image_url": image_url})
    else:
        return jsonify({"error": f"GitHub API returned {resp.status_code}"}), 502


# ---------------------------------------------------------------------------
# Calendar Sponsor Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/calendar-sponsor", methods=["GET"])
def public_calendar_sponsor():
    """Get the active calendar sponsor for today (public, no auth)."""
    from datetime import date
    today = date.today()
    sponsor = get_active_calendar_sponsor(today)
    resp = jsonify(serialize_event(sponsor) if sponsor else {})
    resp.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
    return resp


@app.route("/api/admin/calendar-sponsor", methods=["GET"])
@require_auth
def admin_calendar_sponsor_list():
    """List all calendar sponsors for admin view."""
    sponsors = get_all_calendar_sponsors()
    return jsonify(serialize_list(sponsors))


@app.route("/api/admin/calendar-sponsor", methods=["POST"])
@require_auth
def admin_calendar_sponsor_create():
    """Create a new calendar sponsor. Returns 409 if date range overlaps an existing active record."""
    body = request.get_json(silent=True) or {}
    required = ["name", "image_url", "start_date", "end_date"]
    for field in required:
        if not body.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    # Singleton enforcement: check for overlapping active records
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT id, name FROM calendar_sponsor
               WHERE is_active = true
                 AND start_date <= %s
                 AND end_date >= %s""",
            (body["end_date"], body["start_date"]),
        )
        overlap = cur.fetchone()
    if overlap:
        return jsonify({"error": f"Date range overlaps existing active sponsor \"{overlap['name']}\". Deactivate or delete it first."}), 409

    sponsor = create_calendar_sponsor(body)
    return jsonify(serialize_event(sponsor)), 201


@app.route("/api/admin/calendar-sponsor/<sponsor_id>", methods=["PUT"])
@require_auth
def admin_calendar_sponsor_update(sponsor_id):
    """Update a calendar sponsor."""
    body = request.get_json(silent=True) or {}
    sponsor = get_calendar_sponsor_by_id(sponsor_id)
    if not sponsor:
        return jsonify({"error": "Calendar sponsor not found"}), 404
    updated = update_calendar_sponsor(sponsor_id, body)
    return jsonify(serialize_event(updated))


@app.route("/api/admin/calendar-sponsor/<sponsor_id>", methods=["DELETE"])
@require_auth
def admin_calendar_sponsor_delete(sponsor_id):
    """Hard-delete a calendar sponsor."""
    sponsor = delete_calendar_sponsor(sponsor_id)
    if not sponsor:
        return jsonify({"error": "Calendar sponsor not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/admin/calendar-sponsor/upload-image", methods=["POST"])
@require_auth
def admin_calendar_sponsor_upload_image():
    """Upload a calendar sponsor image to docs/sponsors/ in GitHub repo."""
    f = request.files.get("image")
    if not f:
        return jsonify({"error": "No image file provided"}), 400

    import base64
    import re as _re
    from datetime import datetime

    github_pat = os.environ.get("GITHUB_PAT", "")
    github_repo = os.environ.get("GITHUB_REPO", "wyxr-memphis/concert-calendar")

    if not github_pat:
        return jsonify({"error": "GITHUB_PAT not configured"}), 500

    file_data = f.read()
    filename = f.filename or "sponsor.jpg"
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    allowed_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    if ext not in allowed_exts:
        return jsonify({"error": "Invalid file type"}), 400

    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    base = os.path.splitext(filename)[0]
    clean_base = _re.sub(r'[^a-zA-Z0-9-]', '_', base)
    clean_base = _re.sub(r'_+', '_', clean_base).strip('_') or "cal_sponsor"
    safe_name = f"{ts}_{clean_base}{ext}"

    github_path = f"docs/sponsors/{safe_name}"
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
        "message": f"Upload calendar sponsor image: {safe_name}",
        "content": base64.b64encode(file_data).decode("ascii"),
    }
    if sha:
        put_data["sha"] = sha

    resp = http_requests.put(api_url, headers=gh_headers, json=put_data, timeout=30)
    if resp.status_code in (200, 201):
        image_url = f"https://concert-calendar.wyxr.org/sponsors/{safe_name}"
        return jsonify({"ok": True, "filename": safe_name, "image_url": image_url})
    else:
        return jsonify({"error": f"GitHub API returned {resp.status_code}"}), 502


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
# Prune Old Events
# ---------------------------------------------------------------------------

@app.route("/api/admin/events/prune", methods=["POST"])
@require_auth
def admin_events_prune():
    """Delete events older than today from PostgreSQL."""
    from datetime import date as _date

    today = _date.today().isoformat()
    db_deleted = delete_events_before(today)

    return jsonify({
        "ok": True,
        "deleted": db_deleted,
        "before_date": today,
    })


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
# Slack Event Handler — image uploads → Claude Vision → DB insert → rebuild
# ---------------------------------------------------------------------------

_SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
_SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
_SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "")


def _verify_slack_signature(raw_body: str, headers) -> bool:
    """Verify Slack request signature using HMAC-SHA256."""
    if not _SLACK_SIGNING_SECRET:
        return False

    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    slack_sig = headers.get("X-Slack-Signature", "")

    if not timestamp or not slack_sig:
        return False

    import time as _time
    try:
        if abs(_time.time() - float(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False

    sig_basestring = f"v0:{timestamp}:{raw_body}"
    expected = "v0=" + hmac.new(
        _SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, slack_sig)


def _slack_post_message(channel_id: str, text: str):
    """Post a message to a Slack channel via chat.postMessage. Fails silently."""
    if not _SLACK_BOT_TOKEN:
        return
    try:
        http_requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {_SLACK_BOT_TOKEN}"},
            json={"channel": channel_id, "text": text},
            timeout=10,
        )
    except Exception:
        pass


def _process_slack_image(file_id: str, channel_id: str):
    """Background thread: download Slack image, extract events via Claude Vision, save, rebuild."""
    try:
        # 1. Get file info
        resp = http_requests.get(
            "https://slack.com/api/files.info",
            headers={"Authorization": f"Bearer {_SLACK_BOT_TOKEN}"},
            params={"file": file_id},
            timeout=10,
        )
        file_info = resp.json().get("file", {})
        download_url = file_info.get("url_private_download") or file_info.get("url_private")
        mimetype = file_info.get("mimetype", "image/jpeg")
        filename = file_info.get("name", "slack_upload.jpg")
        print(f"[slack] file info: name={filename} mimetype={mimetype} url={'yes' if download_url else 'no'}", flush=True)

        if not download_url:
            _slack_post_message(channel_id, "⚠️ Could not retrieve image URL from Slack.")
            return

        # Find message caption via channel history (initial_comment is empty for UI uploads)
        caption = ""
        history_resp = http_requests.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {_SLACK_BOT_TOKEN}"},
            params={"channel": channel_id, "limit": 10},
            timeout=10,
        )
        for msg in history_resp.json().get("messages", []):
            if any(f.get("id") == file_id for f in msg.get("files", [])):
                caption = (msg.get("text") or "").lower()
                break
        print(f"[slack] caption={caption!r}", flush=True)

        # Only process if caption contains "add to calendar"
        if "add to calendar" not in caption:
            print(f"[slack] ignoring — no 'add to calendar' in caption", flush=True)
            return

        if not mimetype.startswith("image/"):
            return  # Not an image, ignore silently

        # 2. Download the image
        img_resp = http_requests.get(
            download_url,
            headers={"Authorization": f"Bearer {_SLACK_BOT_TOKEN}"},
            timeout=30,
        )
        if img_resp.status_code != 200:
            _slack_post_message(channel_id, "⚠️ Could not download image from Slack.")
            return

        image_bytes = img_resp.content

        # 3. Extract events via Claude Vision
        from src.sources.artifacts import extract_events_from_image_bytes
        from src.config import START_DATE, SCRAPER_END_DATE
        events = extract_events_from_image_bytes(image_bytes, filename, mimetype)

        if not events:
            _slack_post_message(
                channel_id,
                "⚠️ No events could be extracted from that image. Try the admin UI for manual entry.",
            )
            return

        # 4. Filter to date range and skip duplicates already in DB (fuzzy match)
        events_to_insert = []
        for event in events:
            if not (START_DATE <= event.date <= SCRAPER_END_DATE):
                continue
            if is_fuzzy_duplicate(event.artist, event.venue, event.date.isoformat()):
                continue
            events_to_insert.append(event)

        if not events_to_insert:
            _slack_post_message(
                channel_id,
                "⚠️ No new events found — all extracted events are already in the calendar.",
            )
            return

        # 5. Insert into DB
        event_dicts = []
        for e in events_to_insert:
            d = {
                "title": e.artist,
                "venue": e.venue,
                "date": e.date.isoformat(),
                "source": "artifact",
                "is_active": True,
                "is_featured": False,
            }
            if e.time:
                d["start_time"] = e.time
            event_dicts.append(d)

        bulk_insert_events(event_dicts)

        # 6. Trigger GitHub Actions rebuild
        github_pat = os.environ.get("GITHUB_PAT", "")
        github_repo = os.environ.get("GITHUB_REPO", "wyxr-memphis/concert-calendar")
        build_triggered = False
        if github_pat:
            build_resp = http_requests.post(
                f"https://api.github.com/repos/{github_repo}/actions/workflows/daily.yml/dispatches",
                headers={
                    "Authorization": f"Bearer {github_pat}",
                    "Accept": "application/vnd.github.v3+json",
                },
                json={"ref": "main"},
                timeout=10,
            )
            build_triggered = build_resp.status_code == 204

        # 7. Post results back to Slack
        n = len(events_to_insert)
        lines = [f"✅ *{n} event{'s' if n != 1 else ''} added from image:*"]
        for e in events_to_insert:
            date_str = e.date.strftime("%a %b %-d")
            lines.append(f"• {e.artist} — {e.venue} — {date_str}")
        if build_triggered:
            lines.append("\n📅 Calendar rebuild triggered — live in ~2 minutes")

        _slack_post_message(channel_id, "\n".join(lines))

    except Exception as exc:
        print(f"[slack] Error processing image: {exc}", flush=True)
        try:
            _slack_post_message(channel_id, f"⚠️ Error processing image: {str(exc)[:100]}")
        except Exception:
            pass


@app.route("/api/slack/events", methods=["POST"])
def slack_events():
    """Handle Slack event webhook (file uploads → Claude Vision → DB insert → rebuild)."""
    raw_body_bytes = request.get_data()
    raw_body = raw_body_bytes.decode("utf-8", errors="replace")

    # Verify Slack request signature before processing any payload
    if not _verify_slack_signature(raw_body, request.headers):
        return jsonify({"error": "Invalid signature"}), 403

    try:
        body = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400

    # URL verification challenge (sent by Slack during app setup)
    if body.get("type") == "url_verification":
        return jsonify({"challenge": body.get("challenge")})

    # Handle file_shared event — caption check happens inside background thread via files.info
    event = body.get("event", {})
    event_type = event.get("type")
    print(f"[slack] event type={event_type} keys={list(event.keys())}", flush=True)

    if event_type == "file_shared":
        channel_id = event.get("channel_id") or event.get("channel")
        file_id = event.get("file_id")
        print(f"[slack] file_shared channel_id={channel_id} file_id={file_id} expected={_SLACK_CHANNEL_ID}", flush=True)

        if _SLACK_CHANNEL_ID and channel_id != _SLACK_CHANNEL_ID:
            print(f"[slack] ignoring — channel mismatch", flush=True)
            return jsonify({"ok": True})

        if file_id and channel_id:
            print(f"[slack] starting background thread for file {file_id}", flush=True)
            threading.Thread(
                target=_process_slack_image,
                args=(file_id, channel_id),
                daemon=True,
            ).start()

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Public API v1 — key-authenticated, CORS open
# ---------------------------------------------------------------------------

def _validate_api_key(req):
    """Returns (key_row, None) on success or (None, error_response) on failure."""
    key = req.headers.get("X-API-Key") or req.args.get("api_key")
    if not key:
        return None, ({"error": "Missing API key. Get one at concert-calendar.wyxr.org/api."}, 401)
    row = get_api_key(key)
    if not row or not row["is_active"]:
        return None, ({"error": "Invalid or revoked API key."}, 401)
    return row, None


def _log_api_request_async(key_id, key_prefix, endpoint, query_params, ip, status_code, duration_ms):
    """Fire-and-forget: log an API request in the background."""
    threading.Thread(
        target=log_api_request,
        args=(key_id, key_prefix, endpoint, query_params, ip, status_code, duration_ms),
        daemon=True,
    ).start()


@app.route("/api/v1/events", methods=["GET"])
@cross_origin()
def v1_events():
    """Authenticated public events API with extended filters."""
    import time as _time
    t0 = _time.time()

    key_row, err = _validate_api_key(request)
    if err:
        return jsonify(err[0]), err[1]

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    featured_only = request.args.get("featured_only", "").lower() == "true"
    neighborhood = request.args.get("neighborhood")
    venue = request.args.get("venue")
    limit = request.args.get("limit", 100, type=int)

    events = get_v1_events(
        start_date=start_date,
        end_date=end_date,
        featured_only=featured_only,
        neighborhood=neighborhood,
        venue=venue,
        limit=limit,
    )

    duration_ms = int((_time.time() - t0) * 1000)
    _log_api_request_async(
        str(key_row["id"]),
        key_row["key"][:12],
        "/api/v1/events",
        request.query_string.decode()[:500],
        request.remote_addr,
        200,
        duration_ms,
    )

    resp = jsonify(serialize_list(events))
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.route("/api/v1/venues", methods=["GET"])
@cross_origin()
def v1_venues():
    """Authenticated venues list."""
    key_row, err = _validate_api_key(request)
    if err:
        return jsonify(err[0]), err[1]

    venues = get_all_venues()
    data = [
        {
            "name": v["name"],
            "neighborhood": v.get("neighborhood"),
        }
        for v in venues
    ]
    _log_api_request_async(
        str(key_row["id"]), key_row["key"][:12],
        "/api/v1/venues", "", request.remote_addr, 200, 0,
    )
    return jsonify(data)


@app.route("/api/v1/neighborhoods", methods=["GET"])
@cross_origin()
def v1_neighborhoods():
    """Authenticated neighborhoods list."""
    key_row, err = _validate_api_key(request)
    if err:
        return jsonify(err[0]), err[1]

    rows = get_neighborhoods_with_counts()
    _log_api_request_async(
        str(key_row["id"]), key_row["key"][:12],
        "/api/v1/neighborhoods", "", request.remote_addr, 200, 0,
    )
    resp = jsonify([
        {"name": r["neighborhood"], "event_count": r["event_count"]}
        for r in rows
    ])
    return resp


# ---------------------------------------------------------------------------
# Admin API Key Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/admin/api-keys", methods=["GET"])
@require_auth
def admin_api_keys_list():
    """List all API keys."""
    keys = list_api_keys()
    result = []
    for k in keys:
        d = serialize_event(k)
        # Mask the key — show prefix only
        if d.get("key"):
            d["key_display"] = d["key"][:16] + "..."
            del d["key"]
        result.append(d)
    return jsonify(result)


@app.route("/api/admin/api-keys", methods=["POST"])
@require_auth
def admin_api_keys_create():
    """Create a new API key."""
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    row = create_api_key(
        name=name,
        email=(body.get("email") or "").strip() or None,
        notes=(body.get("notes") or "").strip() or None,
    )
    d = serialize_event(row)
    # Return the full key once — it cannot be retrieved again
    return jsonify(d), 201


@app.route("/api/admin/api-keys/<key_id>", methods=["PUT"])
@require_auth
def admin_api_keys_update(key_id):
    """Update name/email/notes/is_active on an API key."""
    body = request.get_json(silent=True) or {}
    allowed = ["name", "email", "notes", "is_active"]
    kwargs = {k: body[k] for k in allowed if k in body}
    row = update_api_key(key_id, **kwargs)
    if not row:
        return jsonify({"error": "API key not found"}), 404
    d = serialize_event(row)
    if d.get("key"):
        d["key_display"] = d["key"][:16] + "..."
        del d["key"]
    return jsonify(d)


@app.route("/api/admin/api-keys/<key_id>", methods=["DELETE"])
@require_auth
def admin_api_keys_revoke(key_id):
    """Revoke an API key (set is_active=false)."""
    row = update_api_key(key_id, is_active=False)
    if not row:
        return jsonify({"error": "API key not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/admin/api-keys/<key_id>/usage", methods=["GET"])
@require_auth
def admin_api_keys_usage(key_id):
    """Usage stats for an API key: requests/day last 30 days."""
    days = request.args.get("days", 30, type=int)
    rows = get_api_key_usage(key_id, days=days)
    return jsonify([
        {"day": r["day"].isoformat(), "requests": r["requests"]}
        for r in rows
    ])


# ---------------------------------------------------------------------------
# Public API Key Request Endpoint
# ---------------------------------------------------------------------------

@app.route("/api/request-key", methods=["POST"])
@cross_origin()
def public_request_api_key():
    """Accept a public API key request (pending admin approval)."""
    body = request.get_json(silent=True) or {}

    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    company = (body.get("company") or "").strip() or None
    use_case = (body.get("use_case") or "").strip() or None

    errors = []
    if not name:
        errors.append("Name is required")
    if not email or "@" not in email:
        errors.append("A valid email is required")
    if errors:
        return jsonify({"error": ", ".join(errors)}), 400

    create_api_key_request(name=name, email=email, company=company, use_case=use_case)
    return jsonify({"ok": True}), 201


# ---------------------------------------------------------------------------
# Admin API Key Request Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/admin/api-key-requests", methods=["GET"])
@require_auth
def admin_api_key_requests_list():
    """List API key requests, optionally filtered by status."""
    status = request.args.get("status")
    rows = list_api_key_requests(status=status)
    return jsonify(serialize_list(rows))


@app.route("/api/admin/api-key-requests/<request_id>/approve", methods=["POST"])
@require_auth
def admin_api_key_requests_approve(request_id):
    """Approve a key request — generates a real key and emails the requester."""
    rows = list_api_key_requests()
    req = next((r for r in rows if str(r["id"]) == request_id), None)
    if not req:
        return jsonify({"error": "Request not found"}), 404
    if req["status"] != "pending":
        return jsonify({"error": f"Request already {req['status']}"}), 400

    key_row = create_api_key(
        name=req["name"],
        email=req["email"],
        notes=f"Company: {req['company'] or '—'}  Use case: {req['use_case'] or '—'}",
    )
    update_api_key_request(request_id, "approved", api_key_id=str(key_row["id"]))
    return jsonify({"ok": True, "key": serialize_event(key_row)}), 201


@app.route("/api/admin/api-key-requests/<request_id>/reject", methods=["POST"])
@require_auth
def admin_api_key_requests_reject(request_id):
    """Reject an API key request."""
    update_api_key_request(request_id, "rejected")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Admin health-check — signed read-only aggregation for the nightly audit runner
# ---------------------------------------------------------------------------

def require_health_token(fn):
    """Bearer-token auth for the nightly audit runner.

    Separate from the JWT @require_auth decorator: that one is for interactive
    admin sessions; this one is for a sandboxed server-to-server caller that
    cannot hold a JWT and cannot reach Postgres directly.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = os.environ.get("HEALTH_CHECK_TOKEN")
        if not expected:
            return jsonify({"error": "health endpoint not configured"}), 503
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "unauthorized"}), 401
        provided = auth_header[7:]
        if not secrets.compare_digest(provided, expected):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper


def _now_z():
    """UTC ISO 8601 with a Z suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso_z(dt):
    """Serialize an aware datetime as ISO 8601 with a Z suffix; None passes through."""
    if dt is None:
        return None
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


# Synthetic entries written to scrape_logs.details.sources[] by src/main.py
# that aren't actual data fetchers — "Database" is the post-merge count,
# "Events JSON" is its fallback, "Venue Websites" is a wrapper around the
# individual venue runs. Excluded from the scrapers block.
_SYNTHETIC_SOURCE_NAMES = {"Database", "Events JSON", "Venue Websites"}


def _expected_scraper_source_names():
    """Source names that should appear in scrape_logs.details.sources[].

    Matches the literal source_name values emitted by src/sources/*.py on
    success (scraper:ticketmaster, artifact, Venue: <canonical>), so the
    runner can tell "never logged" from "recently succeeded." Venues with
    scraper='manual_only' are skipped — they don't run.
    """
    from src.config import VENUES
    names = {"scraper:ticketmaster", "artifact"}
    for v in VENUES.values():
        if v.get("scraper") == "manual_only":
            continue
        names.add(f"Venue: {v['name']}")
    return names


def _health_scrapers():
    """Most recent per-source run extracted from calendar-build logs.

    scrape_logs stores one row per entire build (scraper_name='calendar-build')
    with per-source results nested in the details JSONB — mirrors what the
    admin Scrapers tab already does via get_scraper_status_summary().
    """
    recent = health_recent_build_logs(limit=30)
    now_utc = datetime.now(timezone.utc)
    per_source = {}

    for log in recent:
        details = log.get("details")
        if not details:
            continue
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                continue
        for src in details.get("sources", []):
            name = src.get("name") or ""
            if not name or name in _SYNTHETIC_SOURCE_NAMES or name in per_source:
                continue
            started = log.get("started_at")
            hours = round((now_utc - started).total_seconds() / 3600.0, 1) if started else None
            per_source[name] = {
                "name": name,
                "last_run_at": _iso_z(started),
                "last_run_status": "success" if src.get("success") else "failed",
                "last_result_count": src.get("events"),
                "hours_since_last_run": hours,
            }

    for name in _expected_scraper_source_names():
        if name not in per_source:
            per_source[name] = {
                "name": name,
                "last_run_at": None,
                "last_run_status": None,
                "last_result_count": None,
                "hours_since_last_run": None,
            }

    return sorted(per_source.values(), key=lambda x: x["name"])


@app.route("/api/admin/health-check", methods=["GET"])
@require_health_token
def admin_health_check():
    return jsonify({
        "generated_at": _now_z(),
        "events_14d": health_events_14d(),
        "scrapers": _health_scrapers(),
    })


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
@app.route("/", methods=["GET", "HEAD"])
def health():
    return jsonify({"status": "ok"})




if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
