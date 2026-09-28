"""Owner-scoped, on-demand rendered screenshot and styleguide capture.

Context.dev is an optional rendering provider. A normal research request never
calls it; the user explicitly requests a visual capture on a completed run.
"""
import base64
import json
import os
import re
import time
import urllib.parse
import urllib.request

import research_store as db
from research import NoRedirect, open_provider

MAX_IMAGE = 1_500_000
MAX_JSON = 400_000


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS collection_visuals (
        run_id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL,
        screenshot TEXT, styleguide TEXT, error TEXT, captured BIGINT NOT NULL,
        lease_until BIGINT NOT NULL DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS collection_visual_budgets (
        bucket TEXT NOT NULL, day TEXT NOT NULL, calls BIGINT NOT NULL,
        PRIMARY KEY(bucket,day))''')


def configured():
    return bool(os.environ.get('CONTEXT_DEV_API_KEY'))


def public(row):
    if not row:
        return None
    return {'status': row['status'], 'captured': row['captured'], 'error': row['error'],
            'retryable': row['status'] in ('failed', 'partial') or (row['status'] == 'running' and row['lease_until'] < time.time()),
            'screenshot': bool(row['screenshot']),
            'image_type': row['screenshot'].split(';',1)[0][5:] if row['screenshot'] else None,
            'styleguide': json.loads(row['styleguide']) if row['styleguide'] else None}


def get(owner, rid):
    with db.connection() as (conn, marker):
        row = db.execute(conn, marker, 'SELECT * FROM collection_visuals WHERE owner=? AND run_id=?', (owner, rid)).fetchone()
        return public(row)


def screenshot_bytes(owner, rid):
    with db.connection() as (conn, marker):
        row = db.execute(conn, marker, 'SELECT screenshot FROM collection_visuals WHERE owner=? AND run_id=?', (owner, rid)).fetchone()
    if not row or not row['screenshot']:
        return None
    mime, payload = row['screenshot'].split(',', 1)
    return mime[5:-7], base64.b64decode(payload, validate=True)


def reserve(owner, rid):
    if not configured():
        raise ValueError('Visual capture requires CONTEXT_DEV_API_KEY in Vercel')
    run = db.get_run(owner, rid)
    if not run or run['status'] != 'complete' or run.get('depth') not in ('scrape', 'crawl') or not run.get('target_url'):
        raise ValueError('Choose a completed page or site collection')
    now = int(time.time())
    day = time.strftime('%Y-%m-%d', time.gmtime(now))
    with db.connection() as (conn, marker):
        row = db.execute(conn, marker, 'SELECT * FROM collection_visuals WHERE owner=? AND run_id=?', (owner, rid)).fetchone()
        if row and row['status'] == 'complete':
            return run, False
        if row and row['status'] == 'running' and row['lease_until'] >= now:
            raise ValueError('Visual capture is already running; inspect the saved result before retrying')
        for bucket, cap in (('visual:global', int(os.environ.get('ZEARCH_DAILY_VISUAL_GLOBAL', '40'))),
                            ('visual:user:' + owner, int(os.environ.get('ZEARCH_DAILY_VISUAL_USER', '3')))):
            db.execute(conn, marker, '''INSERT INTO collection_visual_budgets(bucket,day,calls) VALUES(?,?,0)
                ON CONFLICT(bucket,day) DO NOTHING''', (bucket, day))
            if marker == '%s':
                db.execute(conn, marker, 'SELECT bucket FROM collection_visual_budgets WHERE bucket=? AND day=? FOR UPDATE', (bucket, day)).fetchone()
            used = db.execute(conn, marker, 'SELECT calls FROM collection_visual_budgets WHERE bucket=? AND day=?', (bucket, day)).fetchone()['calls']
            if used >= cap:
                raise ValueError('Visual capture allowance reached for today')
            db.execute(conn, marker, 'UPDATE collection_visual_budgets SET calls=calls+1 WHERE bucket=? AND day=?', (bucket, day))
        db.execute(conn, marker, '''INSERT INTO collection_visuals(run_id,owner,status,captured,lease_until)
            VALUES(?,?,'running',?,?) ON CONFLICT(run_id) DO UPDATE SET status='running',captured=excluded.captured,
            lease_until=excluded.lease_until,error=NULL''', (rid, owner, now, now + 120))
    return run, True


def _json_response(response, limit=MAX_JSON):
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Rendering provider response exceeded its limit')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Rendering provider returned an invalid response')
    return value


def _capture_image(url, key):
    with open_provider('https://api.context.dev/v1/web/scrape',
        {'url': url, 'formats': {'screenshot': True}, 'maxAgeMs': 0}, key, timeout=55) as response:
        data = _json_response(response, 2_400_000)
    output = data.get('screenshot') or {}
    value = output.get('data') if output.get('success') else None
    if not isinstance(value, str):
        raise ValueError('Screenshot capture returned no image')
    match = re.fullmatch(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)', value)
    if not match or len(match[2]) > (MAX_IMAGE * 4 // 3 + 8):
        raise ValueError('Screenshot format or size is unsupported')
    raw = base64.b64decode(match[2], validate=True)
    valid = ((match[1] == 'image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or
             (match[1] == 'image/jpeg' and raw.startswith(b'\xff\xd8\xff')) or
             (match[1] == 'image/webp' and raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'))
    if not raw or len(raw) > MAX_IMAGE or not valid:
        raise ValueError('Screenshot data is invalid')
    return value


def _capture_style(url, key):
    endpoint = 'https://api.context.dev/v1/web/styleguide?' + urllib.parse.urlencode({'directUrl': url, 'maxAgeMs': 0})
    request = urllib.request.Request(endpoint, headers={'Authorization': 'Bearer ' + key, 'User-Agent': 'Zearch/1.0'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=50) as response:
        data = _json_response(response)
    style = data.get('styleguide')
    if data.get('status') != 'ok' or not isinstance(style, dict):
        raise ValueError('No styleguide was returned')
    # Avoid storing arbitrary oversized CSS and provider metadata.
    result = {k: style[k] for k in ('mode', 'colors', 'typography', 'elementSpacing', 'shadows', 'fontLinks', 'components') if k in style}
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded.encode()) > 100_000:
        raise ValueError('Styleguide exceeded its storage limit')
    return encoded


def capture(owner, rid):
    run, fresh = reserve(owner, rid)
    if not fresh:
        return get(owner, rid)
    with db.connection() as (conn, marker):
        prior = db.execute(conn, marker, 'SELECT screenshot,styleguide FROM collection_visuals WHERE owner=? AND run_id=?', (owner, rid)).fetchone()
    screenshot, style = prior['screenshot'], prior['styleguide']
    errors = []
    key = os.environ['CONTEXT_DEV_API_KEY']
    for name, action in (('Screenshot', _capture_image), ('Styleguide', _capture_style)):
        if (name == 'Screenshot' and screenshot) or (name == 'Styleguide' and style):
            continue
        try:
            value = action(run['target_url'], key)
            if name == 'Screenshot': screenshot = value
            else: style = value
        except Exception:
            errors.append(name + ' unavailable')
    status = 'complete' if screenshot and style else 'partial' if screenshot or style else 'failed'
    with db.connection() as (conn, marker):
        db.execute(conn, marker, '''UPDATE collection_visuals SET status=?,screenshot=?,styleguide=?,error=?,lease_until=0
            WHERE owner=? AND run_id=? AND status='running' ''',
            (status, screenshot, style, ', '.join(errors) or None, owner, rid))
    return get(owner, rid)
