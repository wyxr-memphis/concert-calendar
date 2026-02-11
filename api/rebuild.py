"""Vercel serverless function to trigger a GitHub Actions rebuild."""

import json
import os
from http.server import BaseHTTPRequestHandler

import requests

UPLOAD_PASSWORD = os.environ.get("UPLOAD_PASSWORD", "")
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
REPO_OWNER = "robbygrant"
REPO_NAME = "concert-calendar"
WORKFLOW_FILE = "daily.yml"


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return self._json_response(400, {"error": "Invalid JSON"})

        password = data.get("password", "")
        if not UPLOAD_PASSWORD or password != UPLOAD_PASSWORD:
            return self._json_response(401, {"error": "Invalid password"})

        # Trigger workflow dispatch
        api_url = (
            f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
            f"/actions/workflows/{WORKFLOW_FILE}/dispatches"
        )
        headers = {
            "Authorization": f"Bearer {GITHUB_PAT}",
            "Accept": "application/vnd.github.v3+json",
        }

        resp = requests.post(api_url, headers=headers, json={"ref": "main"})

        if resp.status_code == 204:
            return self._json_response(200, {"ok": True})
        else:
            return self._json_response(502, {
                "error": "GitHub API error",
                "status": resp.status_code,
            })

    def do_OPTIONS(self):
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
