"""Opt-in, budgeted worker for explicitly permitted extracted-page rechecks.

python source_revalidation.py enqueue https://approved.example/page
python source_revalidation.py work
"""
import argparse
import math
import os
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import research_store as db
import source_store
from research import safe_url
from retrieval import canonical

MAX_ATTEMPTS = 3
LEASE_SECONDS = 90


def migrate(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS source_revalidation_jobs (
        url TEXT PRIMARY KEY, state TEXT NOT NULL, attempts BIGINT NOT NULL,
        next_run BIGINT NOT NULL, lease_until BIGINT NOT NULL,
        last_error TEXT, created BIGINT NOT NULL, updated BIGINT NOT NULL)""")
    conn.execute('CREATE INDEX IF NOT EXISTS source_revalidation_due ON source_revalidation_jobs(state,next_run)')
    conn.execute("""CREATE TABLE IF NOT EXISTS source_revalidation_budgets (
        day TEXT PRIMARY KEY, calls BIGINT NOT NULL, reserved BIGINT NOT NULL)""")


def price_and_limits():
    try:
        price = Decimal(os.environ['ZEARCH_SCRAPE_USD_PER_CALL'])
        daily = Decimal(os.environ.get('ZEARCH_DAILY_REVALIDATION_USD', '0'))
        calls = int(os.environ.get('ZEARCH_DAILY_REVALIDATION_CALLS', '0'))
        if (not price.is_finite() or price <= 0 or not daily.is_finite()
                or daily < 0 or calls < 0):
            raise ValueError('Invalid revalidation budget')
        return math.ceil(price * 1_000_000), int(daily * 1_000_000), calls
    except (KeyError, InvalidOperation) as exc:
        raise ValueError('Revalidation price and budget must be configured') from exc


def enqueue(url, now=None):
    url = safe_url(url)
    if not url or not source_store.policy_for(url):
        raise ValueError('URL has no approved extraction cache policy')
    now = int(time.time()) if now is None else now
    key = canonical(url)
    with db.connection() as (conn, marker):
        if db.execute(conn, marker, 'SELECT 1 FROM source_tombstones WHERE url=?', (key,)).fetchone():
            raise ValueError('Source was tombstoned')
        db.execute(conn, marker, """INSERT INTO source_revalidation_jobs
            (url,state,attempts,next_run,lease_until,created,updated)
            VALUES(?,'pending',0,?,0,?,?) ON CONFLICT(url) DO UPDATE SET
            state='pending', attempts=0, next_run=excluded.next_run,
            lease_until=0,last_error=NULL,updated=excluded.updated
            WHERE source_revalidation_jobs.state IN ('complete','failed','canceled')""", (key, now, now, now))
    return key


def claim(now=None):
    if os.environ.get('ZEARCH_REVALIDATION_ENABLED') != '1':
        return None
    if not os.environ.get('TAVILY_API_KEY'):
        raise ValueError('Revalidation provider key is not configured')
    price, max_usd, max_calls = price_and_limits()
    if not max_calls or max_usd < price:
        return None
    now = int(time.time()) if now is None else now
    day = time.strftime('%Y-%m-%d', time.gmtime(now))
    with db.connection() as (conn, marker):
        db.execute(conn, marker, """UPDATE source_revalidation_jobs SET state='failed',
            last_error='LeaseExpired',updated=? WHERE state='running' AND lease_until<=?
            AND attempts>=?""", (now, now, MAX_ATTEMPTS))
        sql = """SELECT * FROM source_revalidation_jobs WHERE
            ((state='pending' AND next_run<=?) OR (state='running' AND lease_until<=?))
            AND attempts<? ORDER BY next_run,url LIMIT 1"""
        if marker == '%s':
            sql += ' FOR UPDATE SKIP LOCKED'
        row = db.execute(conn, marker, sql, (now, now, MAX_ATTEMPTS)).fetchone()
        if not row:
            return None
        url = row['url']
        if (not source_store.policy_for(url) or
                db.execute(conn, marker, 'SELECT 1 FROM source_tombstones WHERE url=?', (url,)).fetchone()):
            db.execute(conn, marker, "UPDATE source_revalidation_jobs SET state='canceled',updated=? WHERE url=?", (now, url))
            return None
        db.execute(conn, marker, """INSERT INTO source_revalidation_budgets(day,calls,reserved)
            VALUES(?,0,0) ON CONFLICT(day) DO NOTHING""", (day,))
        if marker == '%s':
            db.execute(conn, marker, 'SELECT day FROM source_revalidation_budgets WHERE day=? FOR UPDATE', (day,)).fetchone()
        budget = db.execute(conn, marker, 'SELECT calls,reserved FROM source_revalidation_budgets WHERE day=?', (day,)).fetchone()
        if budget['calls'] >= max_calls or budget['reserved'] + price > max_usd:
            return None
        attempt = row['attempts'] + 1
        lease = now + LEASE_SECONDS
        db.execute(conn, marker, """UPDATE source_revalidation_jobs SET state='running',attempts=?,
            lease_until=?,updated=? WHERE url=?""", (attempt, lease, now, url))
        db.execute(conn, marker, """UPDATE source_revalidation_budgets SET
            calls=calls+1,reserved=reserved+? WHERE day=?""", (price, day))
        return {'url': url, 'attempt': attempt, 'lease_until': lease}


def finish(job, error=None, now=None):
    now = int(time.time()) if now is None else now
    with db.connection() as (conn, marker):
        row = db.execute(conn, marker, """SELECT state,attempts,lease_until FROM source_revalidation_jobs
            WHERE url=?""", (job['url'],)).fetchone()
        if not row or row['state'] != 'running' or row['attempts'] != job['attempt'] or row['lease_until'] != job['lease_until']:
            return False
        state = 'complete' if error is None else ('failed' if job['attempt'] >= MAX_ATTEMPTS else 'pending')
        delay = 0 if error is None else 60 * 5 ** (job['attempt'] - 1)
        db.execute(conn, marker, """UPDATE source_revalidation_jobs SET state=?,next_run=?,
            lease_until=0,last_error=?,updated=? WHERE url=?""",
            (state, now + delay, str(error)[:120] if error else None, now, job['url']))
        return True


def work_once():
    job = claim()
    if not job:
        return False
    try:
        import enrichment
        content, metadata = enrichment.extract(job['url'])
        source = {'url': job['url'], 'text': content, 'content_type': 'extracted_page',
                  'retrieved_at': int(time.time()), 'title': str(metadata.get('title') or urlsplit(job['url']).hostname)[:300],
                  'description': str(metadata.get('description') or '')[:500],
                  'published_date': '', 'published_date_provenance': 'unknown'}
        if not source_store.save(source):
            raise ValueError('Source cache policy or tombstone rejected the extract')
        finish(job)
    except Exception as exc:  # includes research.Unavailable; a failed job must never crash the worker loop
        finish(job, type(exc).__name__)
    return True


def report():
    with db.connection() as (conn, marker):
        states = db.execute(conn, marker, 'SELECT state,COUNT(*) AS n FROM source_revalidation_jobs GROUP BY state').fetchall()
        budgets = db.execute(conn, marker, 'SELECT day,calls,reserved FROM source_revalidation_budgets ORDER BY day DESC LIMIT 14').fetchall()
    return {'job_states': {row['state']: row['n'] for row in states},
            'daily_reservations': [{'day': row['day'], 'calls': row['calls'],
                'estimated_usd': round(row['reserved'] / 1_000_000, 6)} for row in budgets]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('enqueue', 'work', 'report'))
    parser.add_argument('url', nargs='?')
    args = parser.parse_args()
    db.ensure_schema()
    if args.command == 'enqueue':
        if not args.url:
            parser.error('enqueue requires an approved HTTPS URL')
        print(enqueue(args.url))
    elif args.command == 'work':
        print('processed' if work_once() else 'idle')
    else:
        import json
        print(json.dumps(report(), indent=2))


if __name__ == '__main__':
    main()
