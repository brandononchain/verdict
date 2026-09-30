"""Private session workspace. All data access requires an owner."""
import json
import time
import uuid
import research_store as db


def migrate(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS research_options (
        run_id TEXT PRIMARY KEY, depth TEXT NOT NULL, use_knowledge BIGINT NOT NULL)""")
    conn.execute('''CREATE TABLE IF NOT EXISTS research_targets (
        run_id TEXT PRIMARY KEY, target_url TEXT NOT NULL)''')
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_notes (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
        body TEXT NOT NULL, created BIGINT NOT NULL)""")
    conn.execute('CREATE INDEX IF NOT EXISTS knowledge_owner ON knowledge_notes(owner)')
    conn.execute('''CREATE TABLE IF NOT EXISTS knowledge_documents (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, filename TEXT NOT NULL,
        kind TEXT NOT NULL, content_hash TEXT NOT NULL, byte_count BIGINT NOT NULL,
        text TEXT NOT NULL, created BIGINT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS documents_owner ON knowledge_documents(owner)')
    conn.execute("""CREATE TABLE IF NOT EXISTS investigations (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, query TEXT NOT NULL,
        depth TEXT NOT NULL, interval_hours BIGINT NOT NULL DEFAULT 0,
        next_run BIGINT NOT NULL, expires BIGINT NOT NULL, last_run TEXT,
        last_changes TEXT NOT NULL DEFAULT '{}', created BIGINT NOT NULL)""")
    conn.execute('''CREATE TABLE IF NOT EXISTS investigation_targets (
        investigation_id TEXT PRIMARY KEY, target_url TEXT NOT NULL)''')
    conn.execute("""CREATE TABLE IF NOT EXISTS discovery_jobs (
        id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL, owner TEXT NOT NULL,
        status TEXT NOT NULL, created BIGINT NOT NULL, lease_until BIGINT NOT NULL DEFAULT 0,
        lease_token TEXT, run_id TEXT, error TEXT)""")
    conn.execute('CREATE INDEX IF NOT EXISTS discovery_status ON discovery_jobs(status,created)')
    import collection_batch
    collection_batch.migrate(conn)
    import collection_visual
    collection_visual.migrate(conn)


def lock_owner(conn, marker, owner):
    # Same global lock convention used by reservations, but no provider work under lock.
    db.execute(conn, marker, "INSERT INTO research_budgets(bucket,day,calls,reserved) VALUES(?, 'workspace',0,0) ON CONFLICT(bucket,day) DO NOTHING", ('user:' + owner,))
    if marker == '%s':
        db.execute(conn, marker, "SELECT bucket FROM research_budgets WHERE bucket=? AND day='workspace' FOR UPDATE", ('user:' + owner,)).fetchone()
    if owner.startswith('acct:') and not db.execute(conn, marker,
            'SELECT 1 FROM zearch_accounts WHERE id=?', (owner[5:],)).fetchone():
        raise ValueError('Account is no longer available')


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
        lock_owner(conn, marker, owner)
        if not db.execute(conn, marker, 'SELECT 1 FROM knowledge_notes WHERE owner=? AND id=?', (owner, nid)).fetchone():
            return False
        block_active(conn, marker, owner)
        db.execute(conn, marker, 'DELETE FROM knowledge_notes WHERE owner=? AND id=?', (owner, nid))
        redact_private(conn, marker, owner, 'note_id', nid)
        return True


def block_active(conn, marker, owner):
    if db.execute(conn, marker, "SELECT 1 FROM research_runs WHERE owner=? AND status IN ('pending','streaming') AND updated>? LIMIT 1", (owner, db.active_cutoff())).fetchone():
        raise ValueError('Wait for active research to finish before deleting knowledge')


def redact_private(conn, marker, owner, field, ident):
    rows = db.execute(conn, marker, 'SELECT id,parent_id,sources FROM research_runs WHERE owner=?', (owner,)).fetchall()
    affected = {row['id'] for row in rows if any(source.get(field) == ident for source in json.loads(row['sources']))}
    # Follow-ups can repeat facts from a private source without carrying that
    # source in their own snapshot. Remove the descendants as well.
    while True:
        more = {row['id'] for row in rows if row['parent_id'] in affected}
        if more.issubset(affected): break
        affected.update(more)
    for row in rows:
        if row['id'] in affected:
            db.execute(conn, marker, '''UPDATE research_runs SET status='redacted',answer=?,sources='[]',
                usage='{"redacted_knowledge":true}',error=NULL,updated=? WHERE owner=? AND id=?''',
                ('This answer is unavailable because private knowledge was deleted.', int(time.time()), owner, row['id']))
            db.execute(conn, marker, 'UPDATE investigations SET last_run=NULL,last_changes=? WHERE owner=? AND last_run=?', ('{}', owner, row['id']))


def documents(owner):
    with db.connection() as (conn, marker):
        return [dict(row) for row in db.execute(conn, marker, '''SELECT id,filename,kind,content_hash,byte_count,created
            FROM knowledge_documents WHERE owner=? ORDER BY created DESC,id''', (owner,)).fetchall()]


def add_document(owner, filename, encoded):
    from document_ingest import extract
    text, meta = extract(filename, encoded)
    with db.connection() as (conn, marker):
        lock_owner(conn, marker, owner)
        if db.execute(conn, marker, 'SELECT COUNT(*) AS n FROM knowledge_documents WHERE owner=?', (owner,)).fetchone()['n'] >= 20:
            raise ValueError('Your workspace supports up to 20 documents')
        item = dict(id=uuid.uuid4().hex, filename=meta['filename'], kind=meta['kind'],
                    content_hash=meta['sha256'], byte_count=meta['bytes'], created=int(time.time()))
        db.execute(conn, marker, '''INSERT INTO knowledge_documents(id,owner,filename,kind,content_hash,byte_count,text,created)
            VALUES(?,?,?,?,?,?,?,?)''', (item['id'], owner, item['filename'], item['kind'],
            item['content_hash'], item['byte_count'], text, item['created']))
        return item


def delete_document(owner, ident):
    with db.connection() as (conn, marker):
        lock_owner(conn, marker, owner)
        found = db.execute(conn, marker, 'SELECT id FROM knowledge_documents WHERE owner=? AND id=?', (owner, ident)).fetchone()
        if not found:
            return False
        block_active(conn, marker, owner)
        db.execute(conn, marker, 'DELETE FROM knowledge_documents WHERE owner=? AND id=?', (owner, ident))
        redact_private(conn, marker, owner, 'document_id', ident)
        return True


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
                    'domain': 'Private knowledge', 'source_tier': 'private', 'content_type': 'note', 'excerpt': text[:450]}))
    with db.connection() as (conn, marker):
        docs = db.execute(conn, marker, 'SELECT id,filename,text,content_hash FROM knowledge_documents WHERE owner=?', (owner,)).fetchall()
    for document in docs:
        for at in range(0, len(document['text']), 2000):
            text = document['text'][at:at + 2400]
            score = len(terms.intersection(tokens(document['filename'] + ' ' + text)))
            if score:
                chunks.append((score, {'document_id': document['id'], 'note_id': document['id'],
                    'title': document['filename'], 'text': text, 'domain': 'Private document',
                    'document_hash': document['content_hash'],
                    'source_tier': 'private', 'content_type': 'document', 'excerpt': text[:450]}))
    chunks.sort(key=lambda item: -item[0])
    return [row for _, row in chunks[:3]]


def history(owner):
    with db.connection() as (conn, marker):
        return [dict(row) for row in db.execute(conn, marker, 'SELECT id,query,status,created FROM research_runs WHERE owner=? ORDER BY created DESC,id DESC LIMIT 100', (owner,)).fetchall()]


def has_workspace(owner):
    if not owner:
        return False
    with db.connection() as (conn, marker):
        for table in ('research_runs', 'knowledge_notes', 'knowledge_documents', 'investigations', 'collection_batches'):
            if db.execute(conn, marker, f'SELECT 1 FROM {table} WHERE owner=? LIMIT 1', (owner,)).fetchone():
                return True
    return False


def export_page(owner, cursor=None):
    """Owner-scoped, bounded snapshot export. No provider calls or public cache."""
    with db.connection() as (conn, marker):
        boundary = None
        if cursor is not None:
            if not isinstance(cursor, str) or len(cursor) != 32:
                raise ValueError('Invalid export cursor')
            boundary = db.execute(conn, marker, 'SELECT created,id FROM research_runs WHERE owner=? AND id=?', (owner, cursor)).fetchone()
            if not boundary:
                raise ValueError('Invalid export cursor')
        query = 'SELECT * FROM research_runs WHERE owner=?'
        args = [owner]
        if boundary:
            query += ' AND (created<? OR (created=? AND id<?))'
            args.extend((boundary['created'], boundary['created'], boundary['id']))
        query += ' ORDER BY created DESC,id DESC LIMIT 5'
        rows = db.execute(conn, marker, query, tuple(args)).fetchall()
        runs = []
        for row in rows:
            item = db.public(row)
            options = db.execute(conn, marker, 'SELECT depth,use_knowledge FROM research_options WHERE run_id=?', (item['id'],)).fetchone()
            item.update(dict(options) if options else {'depth': 'standard', 'use_knowledge': 0})
            target = db.execute(conn, marker, 'SELECT target_url FROM research_targets WHERE run_id=?', (item['id'],)).fetchone()
            item['target_url'] = target['target_url'] if target else None
            runs.append(item)
        first = cursor is None
        notes = [dict(row) for row in db.execute(conn, marker,
            'SELECT id,title,body,created FROM knowledge_notes WHERE owner=? ORDER BY created DESC,id', (owner,)).fetchall()] if first else []
        documents = [dict(row) for row in db.execute(conn, marker,
            'SELECT id,filename,kind,content_hash,byte_count,text,created FROM knowledge_documents WHERE owner=? ORDER BY created DESC,id', (owner,)).fetchall()] if first else []
        investigations = [dict(row) for row in db.execute(conn, marker,
            '''SELECT i.id,i.query,i.depth,i.interval_hours,i.next_run,i.expires,i.last_run,i.last_changes,i.created,t.target_url
               FROM investigations i LEFT JOIN investigation_targets t ON t.investigation_id=i.id
               WHERE i.owner=? ORDER BY i.created DESC,i.id''', (owner,)).fetchall()] if first else []
        batches = []
        if first:
            # Use the same transaction for the owner-scoped export snapshot.
            for batch in db.execute(conn, marker, 'SELECT id,query,status,created FROM collection_batches WHERE owner=? ORDER BY created DESC LIMIT 20', (owner,)).fetchall():
                entry = dict(batch)
                entry['items'] = [dict(r) for r in db.execute(conn, marker,
                    'SELECT position,target_url,status,run_id,error FROM collection_batch_items WHERE batch_id=? ORDER BY position', (entry['id'],)).fetchall()]
                batches.append(entry)
        account = db.execute(conn, marker, 'SELECT email,created FROM zearch_accounts WHERE id=?', (owner[5:],)).fetchone() if first and owner.startswith('acct:') else None
        return {'version': 1, 'account': dict(account) if account else None,
                'notes': notes, 'documents': documents, 'investigations': investigations, 'batches': batches,
                'runs': runs, 'next_cursor': runs[-1]['id'] if len(rows) == 5 else None}


def delete_workspace(owner):
    """Erase this session's private records, retaining metering to prevent cap resets."""
    with db.connection() as (conn, marker):
        lock_owner(conn, marker, owner)
        erase_private(conn, marker, owner)
        return True


def erase_private(conn, marker, owner):
    active = db.execute(conn, marker, "SELECT 1 FROM research_runs WHERE owner=? AND status IN ('pending','streaming') AND updated>? LIMIT 1", (owner, db.active_cutoff())).fetchone()
    worker = db.execute(conn, marker, "SELECT 1 FROM discovery_jobs WHERE owner=? AND status='running' LIMIT 1", (owner,)).fetchone()
    batch = db.execute(conn, marker, """SELECT 1 FROM collection_batch_items p JOIN collection_batches b ON b.id=p.batch_id
        WHERE b.owner=? AND p.status='running' LIMIT 1""", (owner,)).fetchone()
    if active or worker or batch:
        raise ValueError('Wait for active research to finish before deleting your workspace')
    db.execute(conn, marker, 'DELETE FROM discovery_jobs WHERE owner=?', (owner,))
    db.execute(conn, marker, 'DELETE FROM investigation_targets WHERE investigation_id IN (SELECT id FROM investigations WHERE owner=?)', (owner,))
    db.execute(conn, marker, 'DELETE FROM collection_batch_items WHERE batch_id IN (SELECT id FROM collection_batches WHERE owner=?)', (owner,))
    db.execute(conn, marker, 'DELETE FROM collection_batches WHERE owner=?', (owner,))
    db.execute(conn, marker, 'DELETE FROM collection_visuals WHERE owner=?', (owner,))
    db.execute(conn, marker, 'DELETE FROM investigations WHERE owner=?', (owner,))
    db.execute(conn, marker, 'DELETE FROM knowledge_notes WHERE owner=?', (owner,))
    db.execute(conn, marker, 'DELETE FROM knowledge_documents WHERE owner=?', (owner,))
    db.execute(conn, marker, 'DELETE FROM research_options WHERE run_id IN (SELECT id FROM research_runs WHERE owner=?)', (owner,))
    db.execute(conn, marker, 'DELETE FROM research_targets WHERE run_id IN (SELECT id FROM research_runs WHERE owner=?)', (owner,))
    db.execute(conn, marker, 'DELETE FROM research_runs WHERE owner=?', (owner,))


def claim_workspace(anonymous_owner, account_id):
    """Explicitly attach the current browser's anonymous data to an authenticated account."""
    if not anonymous_owner or not isinstance(account_id, str):
        raise ValueError('A browser workspace and account are required')
    owner = 'acct:' + account_id
    if anonymous_owner == owner:
        raise ValueError('Invalid workspace claim')
    with db.connection() as (conn, marker):
        for subject in sorted((anonymous_owner, owner)):
            lock_owner(conn, marker, subject)
        prior = db.execute(conn, marker, 'SELECT account_id FROM workspace_claims WHERE anonymous_owner=?', (anonymous_owner,)).fetchone()
        if prior:
            if prior['account_id'] != account_id:
                raise ValueError('This browser workspace belongs to another account')
            return False
        if db.execute(conn, marker, "SELECT 1 FROM research_runs WHERE owner=? AND status IN ('pending','streaming') AND updated>? LIMIT 1", (anonymous_owner, db.active_cutoff())).fetchone():
            raise ValueError('Wait for browser research to finish before claiming it')
        if db.execute(conn, marker, "SELECT 1 FROM discovery_jobs WHERE owner=? AND status='running' LIMIT 1", (anonymous_owner,)).fetchone():
            raise ValueError('Wait for browser refreshes to finish before claiming it')
        if db.execute(conn, marker, """SELECT 1 FROM collection_batch_items p JOIN collection_batches b ON b.id=p.batch_id
            WHERE b.owner=? AND p.status='running' LIMIT 1""", (anonymous_owner,)).fetchone():
            raise ValueError('Wait for the active batch page before claiming it')
        for table in ('research_runs', 'knowledge_notes', 'knowledge_documents', 'investigations', 'discovery_jobs'):
            db.execute(conn, marker, f'UPDATE {table} SET owner=? WHERE owner=?', (owner, anonymous_owner))
        db.execute(conn, marker, 'UPDATE collection_batches SET owner=? WHERE owner=?', (owner, anonymous_owner))
        db.execute(conn, marker, 'UPDATE collection_visuals SET owner=? WHERE owner=?', (owner, anonymous_owner))
        rows = db.execute(conn, marker, 'SELECT day,calls,reserved FROM research_budgets WHERE bucket=? AND day<>?',
                          ('user:' + anonymous_owner, 'workspace')).fetchall()
        for row in rows:
            db.execute(conn, marker, '''INSERT INTO research_budgets(bucket,day,calls,reserved) VALUES(?,?,?,?)
                ON CONFLICT(bucket,day) DO UPDATE SET calls=research_budgets.calls+excluded.calls,
                reserved=research_budgets.reserved+excluded.reserved''',
                ('user:' + owner, row['day'], row['calls'], row['reserved']))
        db.execute(conn, marker, 'INSERT INTO workspace_claims(anonymous_owner,account_id,created) VALUES(?,?,?)',
                   (anonymous_owner, account_id, int(time.time())))
        return True


def delete_run(owner, rid):
    with db.connection() as (conn, marker):
        lock_owner(conn, marker, owner)
        row = db.execute(conn, marker, 'SELECT status,updated FROM research_runs WHERE owner=? AND id=?', (owner, rid)).fetchone()
        if not row:
            return False
        if row['status'] in ('pending', 'streaming') and row['updated'] > db.active_cutoff():
            raise ValueError('Wait for this research to finish before deleting it')
        rows = db.execute(conn, marker, 'SELECT id,parent_id,status,updated FROM research_runs WHERE owner=?', (owner,)).fetchall()
        descendants = {rid}
        while True:
            more = {item['id'] for item in rows if item['parent_id'] in descendants}
            if more.issubset(descendants): break
            descendants.update(more)
        if any(item['id'] in descendants and item['status'] in ('pending','streaming') and item['updated'] > db.active_cutoff() for item in rows):
            raise ValueError('Wait for follow-up research to finish before deleting this answer')
        for child in descendants - {rid}:
            db.execute(conn, marker, '''UPDATE research_runs SET status='redacted',answer=?,sources='[]',
                usage='{"redacted_parent":true}',error=NULL,updated=? WHERE owner=? AND id=?''',
                ('This answer is unavailable because earlier research was deleted.', int(time.time()), owner, child))
            db.execute(conn, marker, 'UPDATE investigations SET last_run=NULL,last_changes=? WHERE owner=? AND last_run=?', ('{}', owner, child))
        db.execute(conn, marker, 'UPDATE research_runs SET parent_id=NULL WHERE owner=? AND parent_id=?', (owner, rid))
        db.execute(conn, marker, 'UPDATE investigations SET last_run=NULL WHERE owner=? AND last_run=?', (owner, rid))
        db.execute(conn, marker, 'UPDATE collection_batch_items SET run_id=NULL,error=? WHERE run_id=?', ('Saved page was deleted', rid))
        db.execute(conn, marker, 'DELETE FROM research_options WHERE run_id=?', (rid,))
        db.execute(conn, marker, 'DELETE FROM research_targets WHERE run_id=?', (rid,))
        db.execute(conn, marker, 'DELETE FROM research_runs WHERE owner=? AND id=?', (owner, rid))
        db.execute(conn, marker, 'DELETE FROM collection_visuals WHERE owner=? AND run_id=?', (owner, rid))
        return True


def allowance(owner):
    import research
    day = time.strftime('%Y-%m-%d', time.gmtime())
    with db.connection() as (conn, marker):
        row = db.execute(conn, marker, 'SELECT calls FROM research_budgets WHERE bucket=? AND day=?', ('user:' + owner, day)).fetchone()
    try:
        cap = research.limits()['user_calls']
    except (ValueError, ArithmeticError):
        cap = 10  # malformed limit settings fall back to the documented default
    return {'plan': 'Research beta', 'used': row['calls'] if row else 0, 'daily_limit': cap,
            'reset': '00:00 UTC', 'billing_enabled': False}


def saved(owner):
    with db.connection() as (conn, marker):
        rows = db.execute(conn, marker, '''SELECT i.*,t.target_url FROM investigations i
            LEFT JOIN investigation_targets t ON t.investigation_id=i.id WHERE i.owner=? ORDER BY i.created DESC,i.id''', (owner,)).fetchall()
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
        run = db.execute(conn, marker, '''SELECT r.query,r.status,o.depth,t.target_url FROM research_runs r
            LEFT JOIN research_options o ON o.run_id=r.id LEFT JOIN research_targets t ON t.run_id=r.id
            WHERE r.owner=? AND r.id=?''', (owner, rid)).fetchone()
        if not run or run['status'] != 'complete':
            raise ValueError('Save a completed answer as an investigation')
        if run['depth'] not in (None, 'standard', 'deep', 'compare', 'scrape', 'crawl'):
            raise ValueError('Unsupported investigation mode')
        if run['depth'] in ('scrape', 'crawl') and not run['target_url']:
            raise ValueError('Collection target is missing')
        existing = db.execute(conn, marker, 'SELECT id FROM investigations WHERE owner=? AND last_run=?', (owner, rid)).fetchone()
        if existing:
            return existing['id']
        count = db.execute(conn, marker, 'SELECT COUNT(*) AS n FROM investigations WHERE owner=?', (owner,)).fetchone()['n']
        if count >= 20:
            raise ValueError('Your workspace supports up to 20 investigations')
        ident = uuid.uuid4().hex
        db.execute(conn, marker, "INSERT INTO investigations(id,owner,query,depth,next_run,expires,last_run,created) VALUES(?,?,?,?,?,?,?,?)", (ident, owner, run['query'], run['depth'] or 'standard', now, now + 29 * 86400, rid, now))
        if run['target_url']:
            db.execute(conn, marker, 'INSERT INTO investigation_targets(investigation_id,target_url) VALUES(?,?)', (ident, run['target_url']))
        return ident
