"""Private session workspace. All data access requires an owner."""
import json
import time
import uuid
import research_store as db


def migrate(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS research_options (
        run_id TEXT PRIMARY KEY, depth TEXT NOT NULL, use_knowledge BIGINT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_notes (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
        body TEXT NOT NULL, created BIGINT NOT NULL)""")
    conn.execute('CREATE INDEX IF NOT EXISTS knowledge_owner ON knowledge_notes(owner)')
    conn.execute("""CREATE TABLE IF NOT EXISTS investigations (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, query TEXT NOT NULL,
        depth TEXT NOT NULL, interval_hours BIGINT NOT NULL DEFAULT 0,
        next_run BIGINT NOT NULL, expires BIGINT NOT NULL, last_run TEXT,
        last_changes TEXT NOT NULL DEFAULT '{}', created BIGINT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS discovery_jobs (
        id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL, owner TEXT NOT NULL,
        status TEXT NOT NULL, created BIGINT NOT NULL, lease_until BIGINT NOT NULL DEFAULT 0,
        lease_token TEXT, run_id TEXT, error TEXT)""")
    conn.execute('CREATE INDEX IF NOT EXISTS discovery_status ON discovery_jobs(status,created)')


def lock_owner(conn, marker, owner):
    # Same global lock convention used by reservations, but no provider work under lock.
    db.execute(conn, marker, "INSERT INTO research_budgets(bucket,day,calls,reserved) VALUES(?, 'workspace',0,0) ON CONFLICT(bucket,day) DO NOTHING", ('user:' + owner,))
    if marker == '%s':
        db.execute(conn, marker, "SELECT bucket FROM research_budgets WHERE bucket=? AND day='workspace' FOR UPDATE", ('user:' + owner,)).fetchone()


def notes(owner, include_body=False):
    with db.connection() as (conn, marker):
        fields = 'id,title,created' + (',body' if include_body else '')
        return [dict(r) for r in db.execute(conn, marker, 'SELECT ' + fields + ' FROM knowledge_notes WHERE owner=? ORDER BY created DESC,id', (owner,)).fetchall()]


def add_note(owner, title, body):
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120 or not isinstance(body, str) or not 1 <= len(body.strip()) <= 40000:
        raise ValueError('Use a title up to 120 characters and text up to 40,000 characters')
    if '\x00' in body:
        raise ValueError('Only plain text is supported')
    with db.connection() as (conn, marker):
        lock_owner(conn, marker, owner)
        if db.execute(conn, marker, 'SELECT COUNT(*) AS n FROM knowledge_notes WHERE owner=?', (owner,)).fetchone()['n'] >= 20:
            raise ValueError('Your workspace supports up to 20 notes')
        note = dict(id=uuid.uuid4().hex, title=title.strip(), created=int(time.time()))
        db.execute(conn, marker, 'INSERT INTO knowledge_notes(id,owner,title,body,created) VALUES(?,?,?,?,?)', (note['id'], owner, note['title'], body.strip(), note['created']))
        return note


def delete_note(owner, nid):
    with db.connection() as (conn, marker):
        return db.execute(conn, marker, 'DELETE FROM knowledge_notes WHERE owner=? AND id=?', (owner, nid)).rowcount > 0


def knowledge(owner, query):
    from retrieval import tokens
    terms = set(tokens(query))
    chunks = []
    for note in notes(owner, True):
        for at in range(0, len(note['body']), 2000):
            text = note['body'][at:at + 2400]
            score = len(terms.intersection(tokens(note['title'] + ' ' + text)))
            if score:
                chunks.append((score, {'note_id': note['id'], 'title': note['title'], 'text': text,
                    'domain': 'Private knowledge', 'content_type': 'note', 'excerpt': text[:450]}))
    chunks.sort(key=lambda item: -item[0])
    return [row for _, row in chunks[:3]]


def history(owner):
    with db.connection() as (conn, marker):
        return [dict(row) for row in db.execute(conn, marker, 'SELECT id,query,status,created FROM research_runs WHERE owner=? ORDER BY created DESC,id DESC LIMIT 100', (owner,)).fetchall()]


def delete_run(owner, rid):
    with db.connection() as (conn, marker):
        lock_owner(conn, marker, owner)
        row = db.execute(conn, marker, 'SELECT status FROM research_runs WHERE owner=? AND id=?', (owner, rid)).fetchone()
        if not row:
            return False
        if row['status'] in ('pending', 'streaming'):
            raise ValueError('Wait for this research to finish before deleting it')
        db.execute(conn, marker, 'UPDATE research_runs SET parent_id=NULL WHERE owner=? AND parent_id=?', (owner, rid))
        db.execute(conn, marker, 'UPDATE investigations SET last_run=NULL WHERE owner=? AND last_run=?', (owner, rid))
        db.execute(conn, marker, 'DELETE FROM research_options WHERE run_id=?', (rid,))
        db.execute(conn, marker, 'DELETE FROM research_runs WHERE owner=? AND id=?', (owner, rid))
        return True


def allowance(owner):
    import research
    day = time.strftime('%Y-%m-%d', time.gmtime())
    with db.connection() as (conn, marker):
        row = db.execute(conn, marker, 'SELECT calls FROM research_budgets WHERE bucket=? AND day=?', ('user:' + owner, day)).fetchone()
    cap = research.limits()['user_calls']
    return {'plan': 'Research beta', 'used': row['calls'] if row else 0, 'daily_limit': cap,
            'reset': '00:00 UTC', 'billing_enabled': False}


def saved(owner):
    with db.connection() as (conn, marker):
        rows = db.execute(conn, marker, 'SELECT * FROM investigations WHERE owner=? ORDER BY created DESC,id', (owner,)).fetchall()
        result = []
        for row in rows:
            item = dict(row); item.pop('owner'); item['last_changes'] = json.loads(item['last_changes'])
            job = db.execute(conn, marker, 'SELECT status,error FROM discovery_jobs WHERE owner=? AND investigation_id=? ORDER BY created DESC,id DESC LIMIT 1', (owner, item['id'])).fetchone()
            item['job'] = dict(job) if job else None
            result.append(item)
        return result


def save_investigation(owner, rid):
    now = int(time.time())
    with db.connection() as (conn, marker):
        lock_owner(conn, marker, owner)
        run = db.execute(conn, marker, 'SELECT r.query,r.status,o.depth FROM research_runs r LEFT JOIN research_options o ON o.run_id=r.id WHERE r.owner=? AND r.id=?', (owner, rid)).fetchone()
        if not run or run['status'] != 'complete':
            raise ValueError('Save a completed answer as an investigation')
        count = db.execute(conn, marker, 'SELECT COUNT(*) AS n FROM investigations WHERE owner=?', (owner,)).fetchone()['n']
        if count >= 20:
            raise ValueError('Your workspace supports up to 20 investigations')
        ident = uuid.uuid4().hex
        db.execute(conn, marker, "INSERT INTO investigations(id,owner,query,depth,next_run,expires,last_run,created) VALUES(?,?,?,?,?,?,?,?)", (ident, owner, run['query'], run['depth'] or 'standard', now, now + 29 * 86400, rid, now))
        return ident
