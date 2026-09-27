from http.server import BaseHTTPRequestHandler
import research_http


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        research_http.get(self)

    def do_POST(self):
        research_http.post(self)

    def log_message(self, *_):
        pass
