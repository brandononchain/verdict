"""Evidence retrieval endpoint."""
import json
from http.server import BaseHTTPRequestHandler

import server


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 200_000:
                return self._json(400, {"error": "body too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
            query = (body.get("query") or "").strip()[:1000]
            playbook = body.get("playbook") if body.get("playbook") in server.PLAYBOOKS else "invest"
            if not query:
                return self._json(400, {"error": "query is required"})
            self._json(200, server.pack_evidence(query, playbook))
        except (ValueError, TypeError):
            self._json(400, {"error": "invalid request"})
        except Exception as error:
            self._json(500, {"error": type(error).__name__})

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
