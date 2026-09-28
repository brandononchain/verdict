"""Owner-scoped visual jobs rendered by Zearch's Railway browser worker."""
import base64
import json
import os
import time
import research_store as db
import workspace_store as workspace
from web_ingest import target

MAX_IMAGE = 1_500_000


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS collection_visuals (
        run_id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL,
        screenshot TEXT, styleguide TEXT, error TEXT, captured BIGINT NOT NULL,
        lease_until BIGINT NOT NULL DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS collection_visual_budgets (
        bucket TEXT NOT NULL, day TEXT NOT NULL, calls BIGINT NOT NULL,
        PRIMARY KEY(bucket,day))''')


def configured():
    return os.environ.get('ZEARCH_VISUAL_CAPTURE_ENABLED') == '1'


def public(row):
    if not row:
        return None
    screenshot = row['screenshot']
    return {'status': row['status'], 'captured': row['captured'], 'error': row['error'],
            'retryable': row['status'] in ('failed', 'partial') or
            (row['status'] == 'running' and row['lease_until'] < time.time()),
            'screenshot': bool(screenshot),
            'image_type': screenshot.split(';', 1)[0][5:] if screenshot else None,
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


def capture(owner, rid):
    """Queue a capture; never open a browser in a web request."""
    if not configured():
        raise ValueError('Visual worker is not enabled')
    run = db.get_run(owner, rid)
    if not run or run['status'] != 'complete' or run.get('depth') not in ('scrape', 'crawl') or not run.get('target_url'):
        raise ValueError('Choose a completed page or site collection')
    target(run['target_url'])
    now = int(time.time())
    day = time.strftime('%Y-%m-%d', time.gmtime(now))
    with db.connection() as (conn, marker):
        workspace.lock_owner(conn, marker, '__scheduler__')
        row = db.execute(conn, marker, 'SELECT * FROM collection_visuals WHERE owner=? AND run_id=?', (owner, rid)).fetchone()
        if row and row['status'] == 'complete':
            return public(row)
        if row and (row['status'] == 'queued' or
                    row['status'] == 'running' and row['lease_until'] >= now):
            return public(row)
        for bucket, cap in (('visual:global', int(os.environ.get('ZEARCH_DAILY_VISUAL_GLOBAL', '40'))),
                            ('visual:user:' + owner, int(os.environ.get('ZEARCH_DAILY_VISUAL_USER', '3')))):
            db.execute(conn, marker, '''INSERT INTO collection_visual_budgets(bucket,day,calls) VALUES(?,?,0)
                ON CONFLICT(bucket,day) DO NOTHING''', (bucket, day))
            used = db.execute(conn, marker, 'SELECT calls FROM collection_visual_budgets WHERE bucket=? AND day=?', (bucket, day)).fetchone()['calls']
            if used >= cap:
                raise ValueError('Visual capture allowance reached for today')
            db.execute(conn, marker, 'UPDATE collection_visual_budgets SET calls=calls+1 WHERE bucket=? AND day=?', (bucket, day))
        db.execute(conn, marker, '''INSERT INTO collection_visuals(run_id,owner,status,captured,lease_until)
            VALUES(?,?,'queued',?,0) ON CONFLICT(run_id) DO UPDATE SET status='queued',captured=excluded.captured,
            lease_until=0,error=NULL''', (rid, owner, now))
    return get(owner, rid)


def claim():
    if not configured():
        return None
    now = int(time.time())
    with db.connection() as (conn, marker):
        workspace.lock_owner(conn, marker, '__scheduler__')
        db.execute(conn, marker, "UPDATE collection_visuals SET status='failed',error='Worker lease expired; retry explicitly' WHERE status='running' AND lease_until<?", (now,))
        suffix = ' FOR UPDATE OF v SKIP LOCKED' if marker == '%s' else ''
        row = db.execute(conn, marker, """SELECT v.run_id,v.owner,t.target_url FROM collection_visuals v
            JOIN research_runs r ON r.id=v.run_id AND r.owner=v.owner
            JOIN research_targets t ON t.run_id=v.run_id
            WHERE v.status='queued' AND r.status='complete' ORDER BY v.captured,v.run_id LIMIT 1""" + suffix).fetchone()
        if not row:
            return None
        job = dict(row)
        job['lease_until'] = now + 180
        db.execute(conn, marker, "UPDATE collection_visuals SET status='running',lease_until=? WHERE run_id=? AND status='queued'", (job['lease_until'], job['run_id']))
        return job


def finish(job, image=None, guide=None, error=None):
    if image is not None:
        if not isinstance(image, bytes) or len(image) > MAX_IMAGE or not image.startswith(b'\xff\xd8\xff'):
            raise ValueError('Screenshot data is invalid')
        screenshot = 'data:image/jpeg;base64,' + base64.b64encode(image).decode()
    else:
        screenshot = None
    style = json.dumps(guide, ensure_ascii=False) if isinstance(guide, dict) else None
    if style and len(style.encode()) > 100_000:
        raise ValueError('Styleguide exceeded its storage limit')
    status = 'complete' if screenshot and style else 'partial' if screenshot or style else 'failed'
    with db.connection() as (conn, marker):
        db.execute(conn, marker, '''UPDATE collection_visuals SET status=?,screenshot=COALESCE(?,screenshot),
            styleguide=COALESCE(?,styleguide),error=?,lease_until=0 WHERE owner=? AND run_id=?
            AND status='running' AND lease_until=? AND lease_until>=?''',
            (status, screenshot, style, error, job['owner'], job['run_id'], job['lease_until'], int(time.time())))


def work_once():
    job = claim()
    if not job:
        return False
    try:
        from visual_browser import render
        image, style = render(job['target_url'])
        finish(job, image, style)
    except Exception:
        finish(job, error='Browser capture failed; retry explicitly')
    return True
