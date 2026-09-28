"""Owned, bounded extracted-page cache. No domain is enabled by default."""
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

POLICY = Path(__file__).with_name('source_cache_policy.json')


def migrate(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS source_extract_cache (
        url TEXT PRIMARY KEY, version_id TEXT NOT NULL, content_hash TEXT NOT NULL,
        text TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
        captured_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
        published_date TEXT NOT NULL, published_date_provenance TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS source_tombstones (
        url TEXT PRIMARY KEY, deleted_at BIGINT NOT NULL)""")
    conn.execute('CREATE INDEX IF NOT EXISTS source_extract_expiry ON source_extract_cache(expires_at)')


def version_id(source):
    from retrieval import canonical
    identity = canonical(source['url']) if source.get('url') else 'note:' + source['note_id']
    payload = '\0'.join((identity, str(source.get('retrieved_at') or ''), source['text']))
    return hashlib.sha256(payload.encode()).hexdigest()


def policy_for(url, policy=None):
    if policy is None:
        policy = json.loads(POLICY.read_text())
    host = urlsplit(url).hostname
    entry = policy.get('domains', {}).get(host) if policy.get('version') == 1 else None
    if (urlsplit(url).scheme != 'https' or not isinstance(entry, dict)
            or entry.get('cache_extracted_content') is not True
            or not isinstance(entry.get('basis'), str) or not entry['basis'].strip()
            or not isinstance(entry.get('reviewed_at'), str) or not entry['reviewed_at'].strip()
            or type(entry.get('ttl_seconds')) is not int or not 300 <= entry['ttl_seconds'] <= 604800):
        return None
    return entry


def lookup(url, now=None, policy=None):
    from retrieval import canonical
    entry = policy_for(url, policy)
    if not entry:
        return None
    now = int(time.time()) if now is None else now
    import research_store as db
    with db.connection() as (conn, marker):
        row = db.execute(conn, marker, """SELECT c.* FROM source_extract_cache c
            LEFT JOIN source_tombstones t ON t.url=c.url
            WHERE c.url=? AND c.expires_at>? AND t.url IS NULL""", (canonical(url), now)).fetchone()
    return dict(row) if row else None


def save(source, now=None, policy=None):
    from retrieval import canonical
    entry = policy_for(source['url'], policy)
    if not entry or source.get('content_type') != 'extracted_page':
        return False
    now = int(time.time()) if now is None else now
    url = canonical(source['url'])
    import research_store as db
    with db.connection() as (conn, marker):
        if db.execute(conn, marker, 'SELECT 1 FROM source_tombstones WHERE url=?', (url,)).fetchone():
            return False
        db.execute(conn, marker, 'DELETE FROM source_extract_cache WHERE expires_at<=?', (now,))
        db.execute(conn, marker, """INSERT INTO source_extract_cache
            (url,version_id,content_hash,text,title,description,captured_at,expires_at,published_date,published_date_provenance)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET
            version_id=excluded.version_id,content_hash=excluded.content_hash,
            text=excluded.text,title=excluded.title,description=excluded.description,
            captured_at=excluded.captured_at,expires_at=excluded.expires_at,
            published_date=excluded.published_date,published_date_provenance=excluded.published_date_provenance
            WHERE excluded.captured_at>=source_extract_cache.captured_at""",
            (url, version_id(source), hashlib.sha256(source['text'].encode()).hexdigest(),
             source['text'][:4000], source.get('title', '')[:300], source.get('description', '')[:500],
             source['retrieved_at'], now + entry['ttl_seconds'], source.get('published_date', ''),
             source.get('published_date_provenance', 'unknown')))
    return True


def apply_hit(source, cached):
    source.update(text=cached['text'], excerpt=cached['text'][:450],
        title=cached['title'], description=cached['description'],
        retrieved_at=cached['captured_at'], content_type='extracted_page',
        fingerprint=cached['content_hash'], source_version_id=cached['version_id'],
        published_date=cached['published_date'],
        published_date_provenance=cached['published_date_provenance'])


def excluded(sources):
    """Remove tombstoned public URLs before they become model evidence."""
    from retrieval import canonical
    keys = {canonical(source['url']) for source in sources if source.get('url')}
    if not keys:
        return sources, 0
    import research_store as db
    with db.connection() as (conn, marker):
        placeholders = ','.join('?' for _ in keys)
        blocked = {row['url'] for row in db.execute(conn, marker,
            f'SELECT url FROM source_tombstones WHERE url IN ({placeholders})', tuple(keys)).fetchall()}
    kept = [source for source in sources if not source.get('url') or canonical(source['url']) not in blocked]
    for n, source in enumerate(kept, 1):
        source['n'] = n
    return kept, len(sources) - len(kept)


def tombstone(url, now=None):
    from retrieval import canonical
    from research import safe_url
    if not safe_url(url):
        raise ValueError('Invalid source URL')
    now = int(time.time()) if now is None else now
    import research_store as db
    with db.connection() as (conn, marker):
        key = canonical(url)
        db.execute(conn, marker, 'DELETE FROM source_extract_cache WHERE url=?', (key,))
        db.execute(conn, marker, """INSERT INTO source_tombstones(url,deleted_at) VALUES(?,?)
            ON CONFLICT(url) DO UPDATE SET deleted_at=excluded.deleted_at""", (key, now))
        db.execute(conn, marker, 'DELETE FROM source_revalidation_jobs WHERE url=?', (key,))
        redacted = []
        for row in db.execute(conn, marker, 'SELECT id,sources FROM research_runs').fetchall():
            sources = json.loads(row['sources'])
            if any(source.get('url') and canonical(source['url']) == key for source in sources):
                db.execute(conn, marker, """UPDATE research_runs SET status='redacted',
                    answer='This answer is unavailable because a source was removed.',
                    sources='[]',usage='{"redacted_source":true}',error=NULL,updated=? WHERE id=?""",
                    (now, row['id']))
                redacted.append(row['id'])
        for rid in redacted:
            db.execute(conn, marker, """UPDATE investigations SET last_run=NULL,last_changes='{}',
                interval_hours=0 WHERE last_run=?""", (rid,))
        # A comparison may retain the URL even when its latest run did not cite it.
        for row in db.execute(conn, marker, 'SELECT id,last_changes FROM investigations').fetchall():
            changes = json.loads(row['last_changes'])
            dirty = False
            for field in ('added', 'removed', 'changed'):
                if isinstance(changes.get(field), list):
                    kept = [item for item in changes[field] if canonical(item) != key]
                    dirty |= len(kept) != len(changes[field])
                    changes[field] = kept
            if dirty:
                db.execute(conn, marker, 'UPDATE investigations SET last_changes=? WHERE id=?',
                    (json.dumps(changes), row['id']))
    return len(redacted)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Remove a public source from the owned cache and retained runs')
    parser.add_argument('command', choices=('tombstone',))
    parser.add_argument('url')
    args = parser.parse_args()
    import research_store as db
    db.ensure_schema()
    print(f'Redacted {tombstone(args.url)} retained runs')


if __name__ == '__main__':
    main()
