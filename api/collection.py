from http.server import BaseHTTPRequestHandler
import collection_http


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        collection_http.handle(self)

    def do_POST(self):
        collection_http.handle(self, mutate=True)

    def log_message(self, *_):
        pass
