from http.server import BaseHTTPRequestHandler
import artifact


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        artifact.handle(self)

    def log_message(self, *_):
        pass
