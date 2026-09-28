"""Same-origin account API; no email code is returned to the browser."""
import json
from urllib.parse import urlsplit

import account_store as accounts
import billing_store
import research_http as http
import research_store as db
import workspace_store as workspace


def handle(handler, mutate=False):
    try:
        db.ensure_schema()
        if not mutate:
            account = accounts.session(handler.headers)
            anonymous_owner, _ = http.anonymous_identity(handler.headers)
            return http.send_json(handler, 200, {'enabled': accounts.enabled(),
                'account': {'email': account['email']} if account else None,
                'claim_available': bool(account and workspace.has_workspace(anonymous_owner))}, None)
        origin = handler.headers.get('Origin')
        if origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            return http.send_json(handler, 403, {'error': 'Request origin is not allowed'})
        length = int(handler.headers.get('Content-Length', '0'))
        if not 1 <= length <= 2048 or not handler.headers.get('Content-Type', '').startswith('application/json'):
            raise ValueError('Expected a small JSON request')
        body = json.loads(handler.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError('Expected an object')
        action = body.get('action')
        if action == 'request_code':
            accounts.request_code(body.get('email'))
            return http.send_json(handler, 200, {'result': 'If mail delivery is available, a sign-in code is on its way.'})
        if action == 'verify_code':
            token, account = accounts.verify(body.get('email'), body.get('code'))
            return http.send_json(handler, 200, {'account': {'email': account['email']}}, accounts.cookie(token))
        account = accounts.session(handler.headers)
        if not account:
            return http.send_json(handler, 401, {'error': 'Sign in first'})
        if action == 'sign_out':
            accounts.revoke(handler.headers)
            return http.send_json(handler, 200, {'result': True}, accounts.cookie())
        if action == 'claim_workspace':
            anonymous_owner, _ = http.anonymous_identity(handler.headers)
            result = workspace.claim_workspace(anonymous_owner, account['id'])
            return http.send_json(handler, 200, {'result': result}, http.new_anonymous_cookie())
        if action == 'delete_account':
            owner = 'acct:' + account['id']
            with db.connection() as (conn, marker):
                if marker == '%s':
                    conn.execute('SELECT pg_advisory_xact_lock(91270420)')
                workspace.lock_owner(conn, marker, owner)
                workspace.erase_private(conn, marker, owner)
                billing_store.erase_account(conn, marker, account['id'])
                db.execute(conn, marker, 'DELETE FROM workspace_claims WHERE account_id=?', (account['id'],))
                db.execute(conn, marker, 'DELETE FROM account_challenges WHERE email=?', (account['email'],))
                db.execute(conn, marker, 'DELETE FROM account_sessions WHERE account_id=?', (account['id'],))
                db.execute(conn, marker, 'DELETE FROM zearch_accounts WHERE id=?', (account['id'],))
            return http.send_json(handler, 200, {'result': True}, accounts.cookie())
        raise ValueError('Unknown account action')
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return http.send_json(handler, 400, {'error': str(exc)})
    except Exception:
        return http.send_json(handler, 503, {'error': 'Account service is temporarily unavailable'})
