"""Durable, bounded discovery jobs. Run `python discovery.py` from a worker.

No automatic retry of an uncertain paid call: stale leases become failed and
require a new explicit refresh. Request IDs prevent duplicate reservation.
"""
import hashlib
import json
import os
import sys
import time
import unicodedata
import uuid
import research
import research_store as db
import workspace_store as workspace


def enabled():
    return os.environ.get('ZEARCH_DISCOVERY_ENABLED') == '1'


def enqueue(owner, iid):
    if not enabled():
        raise ValueError('Discovery worker is not enabled')
    now = int(time.time())
    with db.connection() as (conn, marker):
        workspace.lock_owner(conn, marker, '__scheduler__')
        workspace.lock_owner(conn, marker, owner)
        item = db.execute(conn, marker, 'SELECT * FROM investigations WHERE id=? AND owner=?', (iid, owner)).fetchone()
        if not item or item['expires'] <= now:
            raise ValueError('Investigation not found or expired')
        existing = db.execute(conn, marker, "SELECT id FROM discovery_jobs WHERE owner=? AND investigation_id=? AND status IN ('queued','running')", (owner, iid)).fetchone()
        if existing:
            return existing['id']
        jid = uuid.uuid4().hex
        db.execute(conn, marker, "INSERT INTO discovery_jobs(id,investigation_id,owner,status,created) VALUES(?,?,?,'queued',?)", (jid, iid, owner, now))
        return jid


def schedule(owner, iid, interval):
    if type(interval) is not int or interval not in (0, 24, 168):
        raise ValueError('Choose paused, daily or weekly')
    if interval and not enabled():
        raise ValueError('Discovery worker is not enabled')
    with db.connection() as (conn, marker):
        workspace.lock_owner(conn, marker, '__scheduler__')
        workspace.lock_owner(conn, marker, owner)
        result = db.execute(conn, marker, 'UPDATE investigations SET interval_hours=?,next_run=? WHERE owner=? AND id=? AND expires>?', (interval, int(time.time()) + interval * 3600, owner, iid, int(time.time())))
        if not result.rowcount:
            raise ValueError('Investigation not found or expired')
        if not interval:
            db.execute(conn, marker, "UPDATE discovery_jobs SET status='cancelled' WHERE owner=? AND investigation_id=? AND status='queued'", (owner, iid))


def remove(owner, iid):
    with db.connection() as (conn, marker):
        workspace.lock_owner(conn, marker, '__scheduler__')
        workspace.lock_owner(conn, marker, owner)
        active = db.execute(conn, marker, "SELECT id FROM discovery_jobs WHERE owner=? AND investigation_id=? AND status='running'", (owner, iid)).fetchone()
        if active:
            raise ValueError('Wait for the active refresh to finish before removing it')
        db.execute(conn, marker, 'DELETE FROM discovery_jobs WHERE owner=? AND investigation_id=?', (owner, iid))
        db.execute(conn, marker, 'DELETE FROM investigation_targets WHERE investigation_id=?', (iid,))
        return db.execute(conn, marker, 'DELETE FROM investigations WHERE owner=? AND id=?', (owner, iid)).rowcount > 0


def tick():
    """Queue due work, then claim one job. Safe for concurrent worker processes."""
    if not enabled() or not research.ready():
        return None
    now = int(time.time())
    with db.connection() as (conn, marker):
        # Global scheduler mutex uses the same DB locking convention on Postgres/SQLite.
        workspace.lock_owner(conn, marker, '__scheduler__')
        stale = db.execute(conn, marker, "SELECT run_id,owner FROM discovery_jobs WHERE status='running' AND lease_until<?", (now,)).fetchall()
        for job in stale:
            if job['run_id']:
                db.execute(conn, marker, "UPDATE research_runs SET status='interrupted',error='Worker lease expired',updated=? WHERE id=? AND owner=? AND status IN ('pending','streaming')", (now, job['run_id'], job['owner']))
        db.execute(conn, marker, "UPDATE discovery_jobs SET status='failed',error='Worker lease expired; inspect the saved run before retrying' WHERE status='running' AND lease_until<?", (now,))
        # Also reconcile interactive work left behind by function termination.
        db.execute(conn, marker, "UPDATE research_runs SET status='interrupted',error='Research timed out',updated=? WHERE status IN ('pending','streaming') AND updated<?", (now, now - 600))
        due = db.execute(conn, marker, 'SELECT * FROM investigations WHERE interval_hours>0 AND next_run<=? AND expires>? ORDER BY next_run LIMIT 20', (now, now)).fetchall()
        for item in due:
            active = db.execute(conn, marker, "SELECT id FROM discovery_jobs WHERE investigation_id=? AND status IN ('queued','running')", (item['id'],)).fetchone()
            if not active:
                db.execute(conn, marker, "INSERT INTO discovery_jobs(id,investigation_id,owner,status,created) VALUES(?,?,?,'queued',?)", (uuid.uuid4().hex, item['id'], item['owner'], now))
            db.execute(conn, marker, 'UPDATE investigations SET next_run=? WHERE id=?', (now + item['interval_hours'] * 3600, item['id']))
        suffix = ' FOR UPDATE OF j SKIP LOCKED' if marker == '%s' else ''
        while True:
            row = db.execute(conn, marker, """SELECT j.*,i.query,i.depth,i.last_run,i.expires,t.target_url
                FROM discovery_jobs j JOIN investigations i ON i.id=j.investigation_id
                LEFT JOIN investigation_targets t ON t.investigation_id=i.id
                WHERE j.status='queued' ORDER BY j.created,j.id LIMIT 1""" + suffix).fetchone()
            if not row:
                return None
            job = dict(row)
            if job['expires'] <= now:
                # An expired investigation must not stall the jobs queued behind it.
                db.execute(conn, marker, "UPDATE discovery_jobs SET status='cancelled',error='Investigation expired' WHERE id=?", (job['id'],))
                continue
            job['lease_token'] = uuid.uuid4().hex
            db.execute(conn, marker, "UPDATE discovery_jobs SET status='running',lease_until=?,lease_token=? WHERE id=?", (now + 300, job['lease_token'], job['id']))
            return job


def changes(previous, current):
    def normalized(value):
        return ' '.join(unicodedata.normalize('NFKC', value or '').split())
    def snapshot(run):
        # Compare what Jev selected as evidence, not raw page text, so ads,
        # navigation and timestamps elsewhere on a page do not look like changes.
        rows = {}
        for s in (run or {}).get('sources', []):
            if not s.get('url') or not isinstance(s.get('text'), str):
                continue
            text, span = s['text'], s.get('evidence_span')
            if (isinstance(span, (list, tuple)) and len(span) == 2 and all(type(n) is int for n in span)
                    and 0 <= span[0] < span[1] <= len(text)):
                text = text[span[0]:span[1]]
            rows[s['url']] = hashlib.sha256(normalized(text).encode()).hexdigest()
        return rows
    old, new = snapshot(previous), snapshot(current)
    before = normalized((previous or {}).get('answer'))
    after = normalized((current or {}).get('answer'))
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    changed = sorted(k for k in new.keys() & old.keys() if old[k] != new[k])
    answer_changed = bool(previous and before != after)
    return {'added': added, 'removed': removed, 'changed': changed,
            'answer_changed': answer_changed,
            'review_status': 'pending' if previous and (added or removed or changed or answer_changed) else 'none',
            'check': 'Source and answer differences are review candidates, not verified fact changes. No notification was sent.'}


def finish(job, run=None, error=None):
    now = int(time.time())
    previous = db.get_run(job['owner'], job['last_run']) if job['last_run'] else None
    diff = changes(previous, run) if run else {}
    with db.connection() as (conn, marker):
        cursor = db.execute(conn, marker, "UPDATE discovery_jobs SET status=?,run_id=?,error=? WHERE id=? AND status='running' AND lease_token=? AND lease_until>=?", ('complete' if run else 'failed', run['id'] if run else job.get('run_id'), error, job['id'], job['lease_token'], now))
        if cursor.rowcount and run:
            db.execute(conn, marker, 'UPDATE investigations SET last_run=?,last_changes=? WHERE id=? AND owner=?', (run['id'], json.dumps(diff), job['investigation_id'], job['owner']))


def work_once():
    job = tick()
    if not job:
        return False
    try:
        record, fresh, history = research.prepare(job['owner'], {'query': job['query'], 'request_id': 'discovery-' + job['id'],
            'depth': job['depth'], **({'target_url': job['target_url']} if job['target_url'] else {})})
        job['run_id'] = record['id']
        with db.connection() as (conn, marker):
            db.execute(conn, marker, 'UPDATE discovery_jobs SET run_id=? WHERE id=? AND lease_token=?', (record['id'], job['id'], job['lease_token']))
        if fresh:
            for _ in research.run(job['owner'], record, history):
                pass
        result = db.get_run(job['owner'], record['id'])
        if result and result['status'] == 'complete':
            finish(job, result)
        else:
            finish(job, error='Research did not complete; inspect the saved run')
    except Exception:
        finish(job, error='Refresh failed or allowance reached; no automatic paid retry')
    return True


if __name__ == '__main__':
    if not enabled():
        raise SystemExit('Set ZEARCH_DISCOVERY_ENABLED=1 after configuring the worker and spend caps')
    if len(sys.argv) != 1:
        raise SystemExit('Run python discovery.py; each invocation claims at most one job')
    db.ensure_schema()
    import collection_batch
    import collection_visual
    print('Processed one job.' if work_once() or collection_batch.work_once() or collection_visual.work_once() else 'No eligible work.')
