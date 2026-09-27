"""Compatibility route for legacy local result IDs."""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

import server


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result_id = urlparse(self.path).path.rsplit("/", 1)[-1]
        verdict = server.get_verdict(result_id)
        status = 200 if verdict else 404
        self._json(status, verdict if verdict else {"error": "not found"})

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
