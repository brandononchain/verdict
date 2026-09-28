"""Bounded URL batches processed by the existing Railway discovery cron.

Each invocation claims at most one URL. An uncertain provider call is never
retried automatically; its saved research run remains inspectable.
"""
import time
import uuid

import discovery
import research
import research_store as db
import workspace_store as workspace
from web_ingest import target


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS collection_batches (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, query TEXT NOT NULL,
        status TEXT NOT NULL, created BIGINT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS collection_batch_items (
        id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, position BIGINT NOT NULL,
        target_url TEXT NOT NULL, status TEXT NOT NULL, run_id TEXT, error TEXT,
        lease_until BIGINT NOT NULL DEFAULT 0, lease_token TEXT)''')
    conn.execute('CREATE INDEX IF NOT EXISTS collection_batch_status ON collection_batch_items(status,batch_id,position)')


def create(owner, urls, query):
    if not discovery.enabled():
        raise ValueError('Background worker is not enabled')
    if not isinstance(urls, list) or not 2 <= len(urls) <= 10:
        raise ValueError('Choose 2–10 public HTTPS URLs')
    clean = [target(url) for url in urls]
    if len(set(clean)) != len(clean):
        raise ValueError('Remove duplicate URLs')
    if not isinstance(query, str) or len(query) > 2000:
        raise ValueError('Use a question up to 2,000 characters')
    question = query.strip() or 'Summarize this page and extract its key facts.'
    now, batch_id = int(time.time()), uuid.uuid4().hex
    with db.connection() as (conn, marker):
        workspace.lock_owner(conn, marker, owner)
        active = db.execute(conn, marker, "SELECT COUNT(*) AS n FROM collection_batches WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()['n']
        if active >= 2:
            raise ValueError('Finish or cancel an active batch before creating another')
        db.execute(conn, marker, "INSERT INTO collection_batches(id,owner,query,status,created) VALUES(?,?,?,'queued',?)", (batch_id, owner, question, now))
        for i, url in enumerate(clean):
            db.execute(conn, marker, "INSERT INTO collection_batch_items(id,batch_id,position,target_url,status) VALUES(?,?,?,?,'queued')",
                       (uuid.uuid4().hex, batch_id, i, url))
    return batch_id


def list_for(owner):
    with db.connection() as (conn, marker):
        rows = db.execute(conn, marker, 'SELECT * FROM collection_batches WHERE owner=? ORDER BY created DESC,id DESC LIMIT 20', (owner,)).fetchall()
        result = []
        for row in rows:
            item = dict(row); item.pop('owner')
            item['items'] = [dict(part) for part in db.execute(conn, marker,
                'SELECT position,target_url,status,run_id,error FROM collection_batch_items WHERE batch_id=? ORDER BY position', (item['id'],)).fetchall()]
            result.append(item)
        return result


def cancel(owner, batch_id):
    with db.connection() as (conn, marker):
        workspace.lock_owner(conn, marker, owner)
        row = db.execute(conn, marker, 'SELECT status FROM collection_batches WHERE id=? AND owner=?', (batch_id, owner)).fetchone()
        if not row:
            raise ValueError('Batch not found')
        db.execute(conn, marker, "UPDATE collection_batch_items SET status='cancelled' WHERE batch_id=? AND status='queued'", (batch_id,))
        if not db.execute(conn, marker, "SELECT 1 FROM collection_batch_items WHERE batch_id=? AND status='running'", (batch_id,)).fetchone():
            db.execute(conn, marker, "UPDATE collection_batches SET status='cancelled' WHERE id=?", (batch_id,))
    return True


def _rollup(conn, marker, batch_id):
    counts = {row['status']: row['n'] for row in db.execute(conn, marker,
        'SELECT status,COUNT(*) AS n FROM collection_batch_items WHERE batch_id=? GROUP BY status', (batch_id,)).fetchall()}
    if counts.get('queued') or counts.get('running'):
        state = 'running'
    elif counts.get('cancelled') and not counts.get('complete') and not counts.get('failed'):
        state = 'cancelled'
    else:
        state = 'complete' if not counts.get('failed') and not counts.get('cancelled') else 'partial'
    db.execute(conn, marker, 'UPDATE collection_batches SET status=? WHERE id=?', (state, batch_id))


def tick():
    if not discovery.enabled() or not research.ready():
        return None
    now = int(time.time())
    with db.connection() as (conn, marker):
        workspace.lock_owner(conn, marker, '__scheduler__')
        stale = db.execute(conn, marker, "SELECT id,batch_id,run_id FROM collection_batch_items WHERE status='running' AND lease_until<?", (now,)).fetchall()
        for item in stale:
            if item['run_id']:
                db.execute(conn, marker, "UPDATE research_runs SET status='interrupted',error='Worker lease expired',updated=? WHERE id=? AND status IN ('pending','streaming')", (now, item['run_id']))
            db.execute(conn, marker, "UPDATE collection_batch_items SET status='failed',error='Worker lease expired; inspect the saved run before retrying' WHERE id=?", (item['id'],))
            _rollup(conn, marker, item['batch_id'])
        suffix = ' FOR UPDATE OF p SKIP LOCKED' if marker == '%s' else ''
        item = db.execute(conn, marker, """SELECT p.*,b.owner,b.query FROM collection_batch_items p
            JOIN collection_batches b ON b.id=p.batch_id WHERE p.status='queued' AND b.status IN ('queued','running')
            ORDER BY b.created,p.position LIMIT 1""" + suffix).fetchone()
        if not item:
            return None
        job = dict(item); job['lease_token'] = uuid.uuid4().hex
        db.execute(conn, marker, "UPDATE collection_batch_items SET status='running',lease_until=?,lease_token=? WHERE id=?",
                   (now + 300, job['lease_token'], job['id']))
        _rollup(conn, marker, job['batch_id'])
        return job


def finish(job, run=None, error=None):
    with db.connection() as (conn, marker):
        changed = db.execute(conn, marker, '''UPDATE collection_batch_items SET status=?,run_id=?,error=?
            WHERE id=? AND status='running' AND lease_token=? AND lease_until>=?''',
            ('complete' if run else 'failed', run['id'] if run else job.get('run_id'), error,
             job['id'], job['lease_token'], int(time.time())))
        if changed.rowcount:
            _rollup(conn, marker, job['batch_id'])


def work_once():
    job = tick()
    if not job:
        return False
    try:
        record, fresh, history = research.prepare(job['owner'], {'query': job['query'],
            'request_id': 'batch-' + job['id'], 'depth': 'scrape', 'target_url': job['target_url']})
        job['run_id'] = record['id']
        with db.connection() as (conn, marker):
            db.execute(conn, marker, 'UPDATE collection_batch_items SET run_id=? WHERE id=? AND lease_token=?',
                       (record['id'], job['id'], job['lease_token']))
        if fresh:
            for _ in research.run(job['owner'], record, history):
                pass
        result = db.get_run(job['owner'], record['id'])
        finish(job, result if result and result['status'] == 'complete' else None,
               None if result and result['status'] == 'complete' else 'Research did not complete; inspect the saved run')
    except Exception:
        finish(job, error='Collection failed or allowance reached; no automatic paid retry')
    return True
