#!/usr/bin/env python3
"""Zearch local development server: static app files plus the shared JSON API handlers.

Stdlib only. Hosted deployments use the api/ functions instead.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8765"))

STATIC_ALLOWED = {"/", "/index.html", "/styles.css", "/app.js", "/renderer.js", "/favicon.svg",
                  "/zearch-mark.svg", "/assets/zearch-horizon.jpg"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _route_api(self, path):
        if path == "/api/account":
            import account_http
            return account_http.handle(self, mutate=self.command == "POST")
        if path == "/api/artifact" and self.command == "GET":
            import artifact
            return artifact.handle(self)
        if path == "/api/workspace":
            import workspace_http
            return workspace_http.handle(self, mutate=self.command == "POST")
        if path == "/api/collection":
            import collection_http
            return collection_http.handle(self, mutate=self.command == "POST")
        if path == "/api/research":
            import research_http
            return research_http.post(self) if self.command == "POST" else research_http.get(self)
        if path == "/api/decide" and self.command == "POST":
            return self._json(410, {"error": "The old decision prototype is retired. Use /api/research."})
        if path.startswith("/api/v/"):
            return self._json(410, {"error": "The legacy result route is retired. Use /api/research."})
        return self._json(404, {"error": "not found"})

    def _static(self, head=False):
        # Only serve the app's own static files; everything else falls back to the app shell.
        path = urllib.parse.urlparse(self.path).path
        if path not in STATIC_ALLOWED:
            self.path = "/"
        return super().do_HEAD() if head else super().do_GET()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self._route_api(path)
        return self._static()

    def do_HEAD(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self._json(405, {"error": "method not allowed"})
        return self._static(head=True)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self._route_api(path)
        return self._json(404, {"error": "not found"})


if __name__ == "__main__":
    import research_store
    research_store.migrate()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Zearch → http://localhost:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
