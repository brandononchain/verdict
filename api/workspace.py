from http.server import BaseHTTPRequestHandler
import workspace_http


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        workspace_http.handle(self)

    def do_POST(self):
        workspace_http.handle(self, mutate=True)

    def log_message(self, *_):
        pass
