"""Admin auth check — GET returns 200 if authenticated, 401 if not."""

import json
from http.server import BaseHTTPRequestHandler

from api._auth import get_token_from_cookie, verify_token


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        cookie = self.headers.get("Cookie")
        token = get_token_from_cookie(cookie)
        if not token:
            return self._json(401, {"error": "Not authenticated"})

        payload = verify_token(token)
        if not payload:
            return self._json(401, {"error": "Invalid or expired token"})

        self._json(200, {"ok": True})

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
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
