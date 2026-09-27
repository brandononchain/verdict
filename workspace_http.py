"""Same-origin, private workspace API. Never accepts an owner from the client."""
import json
from urllib.parse import urlsplit
import discovery
import research_http as http
import workspace_store as store


def handle(handler, mutate=False):
    cookie = None
    try:
        origin = handler.headers.get('Origin')
        if mutate and origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            return http.send_json(handler, 403, {'error': 'Request origin is not allowed'})
        owner, cookie = http.identity(handler.headers, create=True)
        if not mutate:
            return http.send_json(handler, 200, {'history': store.history(owner), 'notes': store.notes(owner),
                'investigations': store.saved(owner), 'allowance': store.allowance(owner),
                'discovery_enabled': discovery.enabled()}, cookie)
        length = int(handler.headers.get('Content-Length', '0'))
        if not 1 <= length <= 200000 or not handler.headers.get('Content-Type', '').startswith('application/json'):
            raise ValueError('Expected a JSON request up to 200 KB')
        body = json.loads(handler.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError('Expected an object')
        action = body.get('action')
        ident = body.get('id')
        if action != 'add_note' and (not isinstance(ident, str) or len(ident) != 32):
            raise ValueError('Invalid record identifier')
        if action == 'add_note':
            result = store.add_note(owner, body.get('title'), body.get('body'))
        elif action == 'delete_note':
            result = store.delete_note(owner, ident)
        elif action == 'delete_run':
            result = store.delete_run(owner, ident)
        elif action == 'save_investigation':
            result = store.save_investigation(owner, ident)
        elif action == 'refresh':
            result = discovery.enqueue(owner, ident)
        elif action == 'schedule':
            result = discovery.schedule(owner, ident, body.get('hours'))
        elif action == 'delete_investigation':
            result = discovery.remove(owner, ident)
        else:
            raise ValueError('Unknown action')
        return http.send_json(handler, 200, {'result': result}, cookie)
    except (ValueError, TypeError) as exc:
        return http.send_json(handler, 400, {'error': str(exc)}, cookie)
    except Exception:
        return http.send_json(handler, 503, {'error': 'Your workspace is not configured yet. Please check back shortly.'}, cookie)
