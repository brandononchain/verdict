"""Playbook and server engine status endpoint."""
import json
import os
from http.server import BaseHTTPRequestHandler

import server


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {
            "playbooks": {
                key: {field: value[field] for field in (
                    "name", "blurb", "primary", "threshold", "min_sources", "questions"
                )}
                for key, value in server.PLAYBOOKS.items()
            },
            "server_key": bool(os.environ.get("TYPESAFE_API_KEY")),
            "model": server.MODEL,
        }
        self._json(200, body)

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
