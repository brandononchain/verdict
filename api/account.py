from http.server import BaseHTTPRequestHandler
import account_http


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        account_http.handle(self)

    def do_POST(self):
        account_http.handle(self, mutate=True)

    def log_message(self, *_):
        pass
