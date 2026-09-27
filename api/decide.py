"""Typed judgment and confidence gate endpoint."""
import json
import os
from http.server import BaseHTTPRequestHandler

import server


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        return self._json(410, {"error": "The old decision prototype is retired. Use /api/research."})

    def _json(self, status, data):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass
