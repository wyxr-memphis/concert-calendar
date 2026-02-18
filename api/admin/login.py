"""Admin login endpoint — POST with password, returns JWT cookie."""

import json
import os
from http.server import BaseHTTPRequestHandler

# Vercel resolves imports relative to project root
from api._auth import create_token, set_cookie_header


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        admin_password = os.environ.get("ADMIN_PASSWORD", "")
        if not admin_password:
            return self._json(500, {"error": "ADMIN_PASSWORD not configured"})

        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except (json.JSONDecodeError, ValueError):
            return self._json(400, {"error": "Invalid JSON"})

        password = body.get("password", "")
        if password != admin_password:
            return self._json(401, {"error": "Invalid password"})

        token = create_token()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", set_cookie_header(token))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
