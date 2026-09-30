"""Same-origin, private workspace API. Never accepts an owner from the client."""
import json
from urllib.parse import urlsplit, parse_qs
import discovery
import collection_batch
import research_http as http
import research_store as db
import workspace_store as store


def handle(handler, mutate=False):
    cookie = None
    try:
        origin = handler.headers.get('Origin')
        if mutate and origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            return http.send_json(handler, 403, {'error': 'Request origin is not allowed'})
        owner, cookie = http.identity(handler.headers, create=True)
        db.ensure_schema()
        if not mutate:
            params = parse_qs(urlsplit(handler.path).query)
            if params.get('export') == ['1']:
                return http.send_json(handler, 200, store.export_page(owner, params.get('cursor', [None])[0]), cookie)
            return http.send_json(handler, 200, {'history': store.history(owner), 'notes': store.notes(owner),
                'documents': store.documents(owner),
                'investigations': store.saved(owner), 'allowance': store.allowance(owner),
                'batches': collection_batch.list_for(owner), 'discovery_enabled': discovery.enabled()}, cookie)
        try:
            length = http.content_length(handler.headers, 200000)
        except ValueError:
            raise ValueError('Expected a JSON request up to 200 KB')
        if not handler.headers.get('Content-Type', '').startswith('application/json'):
            raise ValueError('Expected a JSON request up to 200 KB')
        body = json.loads(handler.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError('Expected an object')
        action = body.get('action')
        ident = body.get('id')
        if action not in ('add_note', 'add_document', 'create_batch', 'delete_workspace') and (not isinstance(ident, str) or len(ident) != 32):
            raise ValueError('Invalid record identifier')
        if action == 'add_note':
            result = store.add_note(owner, body.get('title'), body.get('body'))
        elif action == 'add_document':
            result = store.add_document(owner, body.get('filename'), body.get('content_base64'))
        elif action == 'delete_note':
            result = store.delete_note(owner, ident)
        elif action == 'delete_document':
            result = store.delete_document(owner, ident)
        elif action == 'delete_run':
            result = store.delete_run(owner, ident)
        elif action == 'save_investigation':
            result = store.save_investigation(owner, ident)
        elif action == 'monitor_collection':
            if not discovery.enabled():
                raise ValueError('The Railway discovery worker must be enabled before scheduling monitors')
            run = db.get_run(owner, ident)
            if not run or run.get('depth') not in ('scrape', 'crawl'):
                raise ValueError('Choose a completed page or site collection')
            result = store.save_investigation(owner, ident)
            discovery.schedule(owner, result, 24)
        elif action == 'create_batch':
            result = collection_batch.create(owner, body.get('urls'), body.get('query'))
        elif action == 'cancel_batch':
            result = collection_batch.cancel(owner, ident)
        elif action == 'refresh':
            result = discovery.enqueue(owner, ident)
        elif action == 'schedule':
            result = discovery.schedule(owner, ident, body.get('hours'))
        elif action == 'delete_investigation':
            result = discovery.remove(owner, ident)
        elif action == 'delete_workspace':
            result = store.delete_workspace(owner)
        else:
            raise ValueError('Unknown action')
        return http.send_json(handler, 200, {'result': result}, cookie)
    except (ValueError, TypeError) as exc:
        return http.send_json(handler, 400, {'error': str(exc)}, cookie)
    except Exception:
        return http.send_json(handler, 503, {'error': 'Your workspace is not configured yet. Please check back shortly.'}, cookie)
