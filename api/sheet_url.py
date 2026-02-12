"""Vercel serverless function to return the Google Sheet URL."""

import json
import os
from http.server import BaseHTTPRequestHandler

GOOGLE_SHEET_URL = os.environ.get("GOOGLE_SHEET_URL", "")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if GOOGLE_SHEET_URL:
            self._json_response(200, {"url": GOOGLE_SHEET_URL})
        else:
            self._json_response(404, {"error": "Google Sheet URL not configured"})

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
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
