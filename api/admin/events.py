"""Admin event CRUD endpoint — GET/POST/PUT/PATCH via GitHub Contents API.

All methods require valid JWT cookie. Events are stored in data/events.json
in the GitHub repo and committed directly via the Contents API.
"""

import base64
import json
import os
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

from api._auth import get_token_from_cookie, verify_token

GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "wyxr-memphis")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "concert-calendar")
GITHUB_FILE_PATH = os.environ.get("GITHUB_FILE_PATH", "data/events.json")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")


def _github_headers():
    pat = os.environ.get("GITHUB_PAT", "")
    return {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github.v3+json",
    }


def _api_url():
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"


def _read_events():
    """Read events.json from GitHub. Returns (events_data dict, sha str)."""
    params = {"ref": GITHUB_BRANCH}
    resp = requests.get(_api_url(), headers=_github_headers(), params=params)
    resp.raise_for_status()
    data = resp.json()
    sha = data["sha"]
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), sha


def _write_events(events_data, sha, commit_msg):
    """Write events.json to GitHub via Contents API."""
    put_data = {
        "message": commit_msg,
        "content": base64.b64encode(
            json.dumps(events_data, indent=2).encode()
        ).decode(),
        "sha": sha,
        "branch": GITHUB_BRANCH,
    }
    resp = requests.put(_api_url(), headers=_github_headers(), json=put_data)
    resp.raise_for_status()
    return resp.json()


class handler(BaseHTTPRequestHandler):
    def _auth_check(self):
        """Returns True if authenticated, sends 401 and returns False if not."""
        cookie = self.headers.get("Cookie")
        token = get_token_from_cookie(cookie)
        if not token or not verify_token(token):
            self._json(401, {"error": "Not authenticated"})
            return False
        return True

    def do_GET(self):
        if not self._auth_check():
            return
        try:
            events_data, _ = _read_events()
            self._json(200, {"ok": True, "data": events_data})
        except Exception as e:
            self._json(500, {"error": f"Failed to read events: {str(e)[:200]}"})

    def do_POST(self):
        """Add a new event."""
        if not self._auth_check():
            return
        try:
            body = self._read_body()
            events_data, sha = _read_events()

            event_id = f"evt_{int(time.time() * 1000)}_{len(events_data['events'])}"
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            new_event = {
                "id": event_id,
                "title": body.get("title", "").strip(),
                "venue": body.get("venue", "").strip(),
                "date": body.get("date", ""),
                "start_time": body.get("start_time"),
                "doors_time": body.get("doors_time"),
                "ticket_url": body.get("ticket_url"),
                "ticket_price": body.get("ticket_price"),
                "image_url": body.get("image_url"),
                "description": body.get("description"),
                "genre": body.get("genre"),
                "source": "admin",
                "is_featured": body.get("is_featured", False),
                "is_active": body.get("is_active", True),
                "created_at": now,
                "updated_at": now,
            }

            if not new_event["title"] or not new_event["venue"] or not new_event["date"]:
                return self._json(400, {"error": "title, venue, and date are required"})

            events_data["events"].append(new_event)
            events_data["updated_at"] = now

            title = new_event["title"]
            _write_events(events_data, sha, f"admin: add '{title}'")
            self._json(201, {"ok": True, "event": new_event})

        except Exception as e:
            self._json(500, {"error": f"Failed to add event: {str(e)[:200]}"})

    def do_PUT(self):
        """Replace an event entirely."""
        if not self._auth_check():
            return
        try:
            body = self._read_body()
            event_id = body.get("id")
            if not event_id:
                return self._json(400, {"error": "id is required"})

            events_data, sha = _read_events()
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            idx = _find_event_index(events_data["events"], event_id)
            if idx is None:
                return self._json(404, {"error": f"Event {event_id} not found"})

            old = events_data["events"][idx]
            updated = {
                "id": event_id,
                "title": body.get("title", "").strip(),
                "venue": body.get("venue", "").strip(),
                "date": body.get("date", ""),
                "start_time": body.get("start_time"),
                "doors_time": body.get("doors_time"),
                "ticket_url": body.get("ticket_url"),
                "ticket_price": body.get("ticket_price"),
                "image_url": body.get("image_url"),
                "description": body.get("description"),
                "genre": body.get("genre"),
                "source": body.get("source", old.get("source", "admin")),
                "is_featured": body.get("is_featured", False),
                "is_active": body.get("is_active", True),
                "created_at": old.get("created_at", now),
                "updated_at": now,
            }

            if not updated["title"] or not updated["venue"] or not updated["date"]:
                return self._json(400, {"error": "title, venue, and date are required"})

            events_data["events"][idx] = updated
            events_data["updated_at"] = now

            title = updated["title"]
            _write_events(events_data, sha, f"admin: update '{title}'")
            self._json(200, {"ok": True, "event": updated})

        except Exception as e:
            self._json(500, {"error": f"Failed to update event: {str(e)[:200]}"})

    def do_PATCH(self):
        """Partial update — merge fields into existing event."""
        if not self._auth_check():
            return
        try:
            body = self._read_body()
            event_id = body.get("id")
            if not event_id:
                return self._json(400, {"error": "id is required"})

            events_data, sha = _read_events()
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            idx = _find_event_index(events_data["events"], event_id)
            if idx is None:
                return self._json(404, {"error": f"Event {event_id} not found"})

            entry = events_data["events"][idx]

            # Merge provided fields (skip id, created_at)
            for key in ("title", "venue", "date", "start_time", "doors_time",
                        "ticket_url", "ticket_price", "image_url", "description",
                        "genre", "source", "is_featured", "is_active"):
                if key in body:
                    entry[key] = body[key]

            entry["updated_at"] = now
            events_data["updated_at"] = now

            # Build commit message
            title = entry.get("title", event_id)
            if "is_featured" in body:
                msg = f"admin: toggle featured for '{title}'"
            elif "is_active" in body:
                msg = f"admin: toggle active for '{title}'"
            else:
                msg = f"admin: update '{title}'"

            _write_events(events_data, sha, msg)
            self._json(200, {"ok": True, "event": entry})

        except Exception as e:
            self._json(500, {"error": f"Failed to patch event: {str(e)[:200]}"})

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def _find_event_index(events, event_id):
    """Find index of event by id, or None."""
    for i, e in enumerate(events):
        if e.get("id") == event_id:
            return i
    return None
