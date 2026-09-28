"""Passwordless account sessions. Disabled until SMTP delivery is configured."""
import hashlib
import hmac
import os
import re
import secrets
import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage
from http.cookies import SimpleCookie

import research_store as db


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS zearch_accounts (
        id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, created BIGINT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS account_challenges (
        id TEXT PRIMARY KEY, email TEXT NOT NULL, digest TEXT NOT NULL,
        created BIGINT NOT NULL, expires BIGINT NOT NULL, attempts BIGINT NOT NULL DEFAULT 0,
        used BIGINT NOT NULL DEFAULT 0)''')
    conn.execute('CREATE INDEX IF NOT EXISTS challenge_email_created ON account_challenges(email,created)')
    conn.execute('''CREATE TABLE IF NOT EXISTS account_sessions (
        digest TEXT PRIMARY KEY, account_id TEXT NOT NULL, created BIGINT NOT NULL,
        expires BIGINT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS account_sessions_owner ON account_sessions(account_id)')
    conn.execute('''CREATE TABLE IF NOT EXISTS workspace_claims (
        anonymous_owner TEXT PRIMARY KEY, account_id TEXT NOT NULL, created BIGINT NOT NULL)''')


def enabled():
    required = ('ZEARCH_EMAIL_AUTH_ENABLED', 'ZEARCH_MAIL_HOST', 'ZEARCH_MAIL_USER',
                'ZEARCH_MAIL_PASSWORD', 'ZEARCH_MAIL_FROM', 'ZEARCH_SESSION_SECRET')
    return os.environ.get(required[0]) == '1' and all(os.environ.get(key) for key in required[1:]) \
        and len(os.environ.get('ZEARCH_SESSION_SECRET', '')) >= 32


def normalize(email):
    if not isinstance(email, str):
        raise ValueError('Enter a valid email address')
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+', email):
        raise ValueError('Enter a valid email address')
    return email


def digest(value):
    return hmac.new(os.environ['ZEARCH_SESSION_SECRET'].encode(), value.encode(), hashlib.sha256).hexdigest()


def token_from(headers):
    jar = SimpleCookie()
    try:
        jar.load(headers.get('Cookie', ''))
        token = jar.get('zearch_account').value if jar.get('zearch_account') else ''
    except Exception:
        return None
    return token if re.fullmatch(r'[a-f0-9]{64}', token) else None


def session(headers):
    if not enabled():
        return None
    token = token_from(headers)
    if not token:
        return None
    db.ensure_schema()
    with db.connection() as (conn, marker):
        row = db.execute(conn, marker, '''SELECT a.id,a.email FROM account_sessions s
            JOIN zearch_accounts a ON a.id=s.account_id WHERE s.digest=? AND s.expires>?''',
            (digest(token), int(time.time()))).fetchone()
        return dict(row) if row else None


def cookie(token=None):
    value = token or ''
    result = f'zearch_account={value}; HttpOnly; SameSite=Lax; Path=/; Max-Age={2592000 if token else 0}'
    if os.environ.get('VERCEL'):
        result += '; Secure'
    return result


def send_code(email, code):
    message = EmailMessage()
    message['From'] = os.environ['ZEARCH_MAIL_FROM']
    message['To'] = email
    message['Subject'] = 'Your Zearch sign-in code'
    message.set_content(f'Your Zearch code is {code}. It expires in 10 minutes. If you did not request it, ignore this message.')
    host = os.environ['ZEARCH_MAIL_HOST']
    port = int(os.environ.get('ZEARCH_MAIL_PORT') or '465')
    if port == 465:
        client = smtplib.SMTP_SSL(host, port, timeout=10, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(host, port, timeout=10)
        client.starttls(context=ssl.create_default_context())
    with client:
        client.login(os.environ['ZEARCH_MAIL_USER'], os.environ['ZEARCH_MAIL_PASSWORD'])
        client.send_message(message)


def request_code(email):
    if not enabled():
        raise RuntimeError('Account sign-in is not configured')
    email = normalize(email)
    now = int(time.time())
    code = f'{secrets.randbelow(100_000_000):08d}'
    ident = uuid.uuid4().hex
    with db.connection() as (conn, marker):
        # Serialize same-email requests across instances; global cap limits mail abuse.
        if marker == '%s':
            conn.execute('SELECT pg_advisory_xact_lock(91270420)')
        recent = db.execute(conn, marker, 'SELECT COUNT(*) AS n FROM account_challenges WHERE email=? AND created>?', (email, now - 3600)).fetchone()['n']
        total = db.execute(conn, marker, 'SELECT COUNT(*) AS n FROM account_challenges WHERE created>?', (now - 3600,)).fetchone()['n']
        if recent >= 3 or total >= 30:
            raise ValueError('Too many sign-in requests. Try again later.')
        db.execute(conn, marker, 'DELETE FROM account_challenges WHERE expires<?', (now - 86400,))
        db.execute(conn, marker, 'DELETE FROM account_sessions WHERE expires<?', (now,))
        db.execute(conn, marker, 'INSERT INTO account_challenges(id,email,digest,created,expires) VALUES(?,?,?,?,?)',
                   (ident, email, digest(ident + ':' + code), now, now + 600))
    try:
        send_code(email, code)
    except Exception as exc:
        with db.connection() as (conn, marker):
            db.execute(conn, marker, 'UPDATE account_challenges SET used=1 WHERE id=?', (ident,))
        raise RuntimeError('Sign-in mail is temporarily unavailable') from exc
    return True


def verify(email, code):
    if not enabled():
        raise RuntimeError('Account sign-in is not configured')
    email = normalize(email)
    if not isinstance(code, str) or not re.fullmatch(r'\d{8}', code):
        raise ValueError('Invalid or expired sign-in code')
    now = int(time.time())
    invalid = False
    with db.connection() as (conn, marker):
        if marker == '%s':
            conn.execute('SELECT pg_advisory_xact_lock(91270420)')
        row = db.execute(conn, marker, '''SELECT id,digest,attempts FROM account_challenges
            WHERE email=? AND expires>? AND used=0 ORDER BY created DESC,id DESC LIMIT 1''', (email, now)).fetchone()
        if not row or row['attempts'] >= 5:
            raise ValueError('Invalid or expired sign-in code')
        db.execute(conn, marker, 'UPDATE account_challenges SET attempts=attempts+1 WHERE id=?', (row['id'],))
        invalid = not hmac.compare_digest(row['digest'], digest(row['id'] + ':' + code))
        if not invalid:
            db.execute(conn, marker, 'UPDATE account_challenges SET used=1 WHERE email=?', (email,))
            account = db.execute(conn, marker, 'SELECT id FROM zearch_accounts WHERE email=?', (email,)).fetchone()
            if not account:
                account_id = uuid.uuid4().hex
                db.execute(conn, marker, 'INSERT INTO zearch_accounts(id,email,created) VALUES(?,?,?)', (account_id, email, now))
            else:
                account_id = account['id']
            token = secrets.token_hex(32)
            db.execute(conn, marker, 'INSERT INTO account_sessions(digest,account_id,created,expires) VALUES(?,?,?,?)',
                       (digest(token), account_id, now, now + 30 * 86400))
    if invalid:
        raise ValueError('Invalid or expired sign-in code')
    return token, {'id': account_id, 'email': email}


def revoke(headers):
    token = token_from(headers)
    if token:
        with db.connection() as (conn, marker):
            db.execute(conn, marker, 'DELETE FROM account_sessions WHERE digest=?', (digest(token),))


def prune(now=None):
    now = int(time.time()) if now is None else now
    with db.connection() as (conn, marker):
        challenges = db.execute(conn, marker, 'DELETE FROM account_challenges WHERE expires<?', (now - 86400,)).rowcount
        sessions = db.execute(conn, marker, 'DELETE FROM account_sessions WHERE expires<?', (now,)).rowcount
    return {'expired_challenges': challenges, 'expired_sessions': sessions}


if __name__ == '__main__':
    import json
    db.migrate()
    print(json.dumps(prune()))
