"""Vercel serverless function for uploading artifacts to GitHub."""

import base64
import json
import os
from http.server import BaseHTTPRequestHandler
import requests

UPLOAD_PASSWORD = os.environ.get("UPLOAD_PASSWORD", "")
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
REPO_OWNER = "robbygrant"
REPO_NAME = "concert-calendar"
ARTIFACTS_PATH = "artifacts"

ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".mhtml", ".html", ".htm",
}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_type = self.headers.get("Content-Type", "")

        if "multipart/form-data" not in content_type:
            return self._json_response(400, {"error": "Expected multipart/form-data"})

        # Parse multipart form data
        try:
            boundary = content_type.split("boundary=")[1].strip()
        except (IndexError, AttributeError):
            return self._json_response(400, {"error": "Missing boundary"})

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > MAX_FILE_SIZE:
            return self._json_response(413, {"error": "File too large (max 20 MB)"})

        body = self.rfile.read(content_length)
        fields = _parse_multipart(body, boundary.encode())

        # Validate password
        password = fields.get("password", b"").decode("utf-8", errors="replace")
        if not UPLOAD_PASSWORD or password != UPLOAD_PASSWORD:
            return self._json_response(401, {"error": "Invalid password"})

        # Get file data
        file_data = fields.get("file")
        filename = fields.get("filename", b"").decode("utf-8", errors="replace")

        if not file_data or not filename:
            return self._json_response(400, {"error": "No file provided"})

        # Validate extension
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return self._json_response(
                400, {"error": f"File type {ext} not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}
            )

        # Sanitize filename - keep only safe characters
        safe_filename = "".join(
            c for c in filename if c.isalnum() or c in ".-_ "
        ).strip()
        if not safe_filename:
            return self._json_response(400, {"error": "Invalid filename"})

        # Upload to GitHub via Contents API
        github_path = f"{ARTIFACTS_PATH}/{safe_filename}"
        api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{github_path}"

        # Check if file already exists (to get its SHA for update)
        headers = {
            "Authorization": f"Bearer {GITHUB_PAT}",
            "Accept": "application/vnd.github.v3+json",
        }

        sha = None
        existing = requests.get(api_url, headers=headers)
        if existing.status_code == 200:
            sha = existing.json().get("sha")

        put_data = {
            "message": f"Upload artifact: {safe_filename}",
            "content": base64.b64encode(file_data).decode("ascii"),
        }
        if sha:
            put_data["sha"] = sha

        resp = requests.put(api_url, headers=headers, json=put_data)

        if resp.status_code in (200, 201):
            return self._json_response(200, {
                "ok": True,
                "filename": safe_filename,
                "updated": sha is not None,
            })
        else:
            return self._json_response(502, {
                "error": "GitHub API error",
                "status": resp.status_code,
            })

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def _json_response(self, status, data):
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def _parse_multipart(body: bytes, boundary: bytes) -> dict:
    """Minimal multipart/form-data parser.

    Returns dict with field names as keys and raw bytes as values.
    For file fields, also stores 'filename' separately.
    """
    fields = {}
    parts = body.split(b"--" + boundary)

    for part in parts:
        if part in (b"", b"--", b"--\r\n", b"\r\n"):
            continue

        # Split headers from body
        if b"\r\n\r\n" not in part:
            continue
        header_section, part_body = part.split(b"\r\n\r\n", 1)

        # Strip trailing \r\n from body
        if part_body.endswith(b"\r\n"):
            part_body = part_body[:-2]

        header_text = header_section.decode("utf-8", errors="replace")

        # Extract field name
        name = None
        filename = None
        for line in header_text.split("\r\n"):
            if "Content-Disposition:" in line:
                for param in line.split(";"):
                    param = param.strip()
                    if param.startswith("name="):
                        name = param.split("=", 1)[1].strip('"')
                    elif param.startswith("filename="):
                        filename = param.split("=", 1)[1].strip('"')

        if name == "file":
            fields["file"] = part_body
            if filename:
                fields["filename"] = filename.encode("utf-8")
        elif name:
            fields[name] = part_body

    return fields
