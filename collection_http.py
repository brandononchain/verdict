"""Private visual collection endpoint. GET metadata/image, POST explicit capture."""
import json
import re
from urllib.parse import parse_qs, urlsplit

import collection_visual as visuals
import research_http as http
import research_store as db


def handle(handler, mutate=False):
    cookie = None
    try:
        if mutate:
            origin = handler.headers.get('Origin')
            if origin and urlsplit(origin).netloc != handler.headers.get('Host'):
                return http.send_json(handler, 403, {'error': 'Request origin is not allowed'})
        params = parse_qs(urlsplit(handler.path).query)
        rid = params.get('id', [''])[0]
        if not re.fullmatch(r'[a-f0-9]{32}', rid):
            return http.send_json(handler, 404, {'error': 'Collection not found'})
        owner, cookie = http.identity(handler.headers, create=mutate)
        db.ensure_schema()
        run = db.get_run(owner, rid) if owner else None
        if not run or run.get('depth') not in ('scrape', 'crawl') or run['status'] != 'complete':
            return http.send_json(handler, 404, {'error': 'Collection not found'}, cookie)
        if mutate:
            length = int(handler.headers.get('Content-Length', '0'))
            if length > 100 or not handler.headers.get('Content-Type', '').startswith('application/json'):
                return http.send_json(handler, 415, {'error': 'Expected a small JSON request'}, cookie)
            if json.loads(handler.rfile.read(length) or b'{}') != {}:
                return http.send_json(handler, 400, {'error': 'Capture takes no options'}, cookie)
            return http.send_json(handler, 200, visuals.capture(owner, rid), cookie)
        if params.get('image') == ['1']:
            image = visuals.screenshot_bytes(owner, rid)
            if not image:
                return http.send_json(handler, 404, {'error': 'Screenshot not found'})
            mime, payload = image
            handler.send_response(200)
            handler.send_header('Content-Type', mime)
            handler.send_header('Content-Length', str(len(payload)))
            handler.send_header('Cache-Control', 'private, no-store')
            handler.send_header('X-Content-Type-Options', 'nosniff')
            handler.end_headers(); handler.wfile.write(payload)
            return
        return http.send_json(handler, 200, {'configured': visuals.configured(),
            'visual': visuals.get(owner, rid)}, cookie)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return http.send_json(handler, 400, {'error': str(exc)}, cookie)
    except Exception:
        return http.send_json(handler, 503, {'error': 'Visual capture is temporarily unavailable'}, cookie)
