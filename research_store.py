"""Durable, owner-scoped runs and atomic spending reservations.

SQLite is for local development only. Hosted deployments require Postgres.
Hosted requests initialize the idempotent schema on first use.
"""
import json
import os
import sqlite3
import time
import threading
from contextlib import contextmanager
from pathlib import Path


class LimitReached(Exception):
    pass


_schema_lock = threading.Lock()
_schema_ready_for = None


@contextmanager
def connection():
    url = os.environ.get("DATABASE_URL")
    if url:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
            yield conn, "%s"
    else:
        if os.environ.get("VERCEL"):
            raise RuntimeError("Hosted research requires DATABASE_URL")
        path = Path(os.environ.get("ZEARCH_DB_PATH", "data/research.sqlite3"))
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn, "?"
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def execute(conn, marker, sql, params=()):
    return conn.execute(sql.replace("?", marker), params)


def migrate():
    with connection() as (conn, _):
        if os.environ.get('DATABASE_URL'):
            # Vercel instances may cold-start together; serialize DDL across them.
            conn.execute('SELECT pg_advisory_xact_lock(91270419)')
        conn.execute("""CREATE TABLE IF NOT EXISTS research_runs (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, parent_id TEXT,
            query TEXT NOT NULL, status TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '',
            sources TEXT NOT NULL DEFAULT '[]', usage TEXT NOT NULL DEFAULT '{}',
            error TEXT, model TEXT NOT NULL, created BIGINT NOT NULL,
            updated BIGINT NOT NULL, reserved BIGINT NOT NULL, estimated_cost BIGINT,
            day TEXT NOT NULL, request_id TEXT NOT NULL,
            UNIQUE(owner, request_id))""")
        import workspace_store
        workspace_store.migrate(conn)
        import account_store
        account_store.migrate(conn)
        import source_store
        source_store.migrate(conn)
        import source_revalidation
        source_revalidation.migrate(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS research_owner_created ON research_runs(owner, created)")
        conn.execute("""CREATE TABLE IF NOT EXISTS research_budgets (
            bucket TEXT NOT NULL, day TEXT NOT NULL, calls BIGINT NOT NULL,
            reserved BIGINT NOT NULL, PRIMARY KEY(bucket, day))""")


def ensure_schema():
    """Initialize hosted Postgres once per process and database URL, then serve normally."""
    global _schema_ready_for
    url = os.environ.get('DATABASE_URL')
    if not url:
        if os.environ.get('VERCEL'):
            raise RuntimeError('Hosted research requires DATABASE_URL')
        return  # The local SQLite server and tests already migrate at startup.
    if _schema_ready_for == url:
        return
    with _schema_lock:
        if _schema_ready_for != url:
            migrate()
            _schema_ready_for = url


def public(row):
    if not row:
        return None
    d = dict(row)
    for field in ("sources", "usage"):
        d[field] = json.loads(d[field])
    d.pop("owner", None)
    d.pop("request_id", None)
    return d


def get_run(owner, rid):
    with connection() as (conn, marker):
        row = execute(conn, marker, "SELECT * FROM research_runs WHERE owner=? AND id=?", (owner, rid)).fetchone()
        result = public(row)
        if result:
            options = execute(conn, marker, 'SELECT depth,use_knowledge FROM research_options WHERE run_id=?', (rid,)).fetchone()
            result.update(dict(options) if options else {'depth': 'standard', 'use_knowledge': 0})
        return result


def reserve(owner, rid, request_id, query, parent_id, model, amount, limits, depth="standard", use_knowledge=False):
    """All budgets and the pending run commit in one transaction, before any paid call."""
    now = int(time.time())
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    with connection() as (conn, marker):
        # Fixed lock order prevents concurrent requests overspending the same budget.
        for bucket in ("global", "user:" + owner):
            execute(conn, marker, "INSERT INTO research_budgets(bucket,day,calls,reserved) VALUES(?,?,0,0) ON CONFLICT(bucket,day) DO NOTHING", (bucket, day))
            if marker == "%s":
                execute(conn, marker, "SELECT bucket FROM research_budgets WHERE bucket=? AND day=? FOR UPDATE", (bucket, day)).fetchone()
        import workspace_store
        workspace_store.lock_owner(conn, marker, owner)
        previous = execute(conn, marker, "SELECT * FROM research_runs WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
        if previous:
            options = execute(conn, marker, 'SELECT depth,use_knowledge FROM research_options WHERE run_id=?', (previous['id'],)).fetchone()
            old = dict(options) if options else {'depth': 'standard', 'use_knowledge': 0}
            if old['depth'] != depth or bool(old['use_knowledge']) != use_knowledge:
                raise ValueError('Request identifier belongs to different research options')
            if previous["query"] != query or previous["parent_id"] != parent_id:
                raise ValueError("Request identifier already belongs to another question")
            result = public(previous); result.update(old)
            return result, False
        if parent_id:
            parent = execute(conn, marker, "SELECT status FROM research_runs WHERE owner=? AND id=?", (owner, parent_id)).fetchone()
            if not parent or parent["status"] != "complete":
                raise ValueError("Follow-up answer not found")
        for bucket, max_calls, max_amount in (("global", limits["global_calls"], limits["global_budget"]), ("user:" + owner, limits["user_calls"], limits["user_budget"])):
            row = execute(conn, marker, "SELECT calls,reserved FROM research_budgets WHERE bucket=? AND day=?", (bucket, day)).fetchone()
            if row["calls"] >= max_calls or row["reserved"] + amount > max_amount:
                raise LimitReached("Research allowance reached. Please try again after the daily reset.")
            execute(conn, marker, "UPDATE research_budgets SET calls=calls+1,reserved=reserved+? WHERE bucket=? AND day=?", (amount, bucket, day))
        execute(conn, marker, "INSERT INTO research_runs(id,owner,parent_id,query,status,model,created,updated,reserved,day,request_id) VALUES(?,?,?,?,'pending',?,?,?,?,?,?)", (rid, owner, parent_id, query, model, now, now, amount, day, request_id))
        execute(conn, marker, 'INSERT INTO research_options(run_id,depth,use_knowledge) VALUES(?,?,?)', (rid, depth, int(use_knowledge)))
        result = public(execute(conn, marker, "SELECT * FROM research_runs WHERE id=?", (rid,)).fetchone())
        result.update(depth=depth, use_knowledge=int(use_knowledge))
        return result, True


def save(owner, rid, *, status, answer="", sources=None, usage=None, error=None, estimated_cost=None):
    with connection() as (conn, marker):
        if sources:
            from retrieval import canonical
            keys = {canonical(source['url']) for source in sources if source.get('url')}
            if keys:
                placeholders = ','.join('?' for _ in keys)
                blocked = execute(conn, marker, f'SELECT url FROM source_tombstones WHERE url IN ({placeholders})', tuple(keys)).fetchone()
                if blocked:
                    status, answer, sources, usage, error = ('redacted',
                        'This answer is unavailable because a source was removed.', [],
                        {'redacted_source': True}, None)
        execute(conn, marker, "UPDATE research_runs SET status=?,answer=?,sources=?,usage=?,error=?,estimated_cost=?,updated=? WHERE owner=? AND id=? AND status<>'redacted'", (status, answer, json.dumps(sources or []), json.dumps(usage or {}), error, estimated_cost, int(time.time()), owner, rid))
    # Reservations intentionally remain charged for the day, including failures.
    # Unknown upstream charges must never silently restore spend headroom.


def context(owner, parent_id):
    messages = []
    seen = set()
    while parent_id and parent_id not in seen and len(messages) < 6:
        seen.add(parent_id)
        row = get_run(owner, parent_id)
        if not row or row["status"] != "complete":
            raise ValueError("Follow-up answer not found")
        messages[0:0] = [{"role": "user", "content": row["query"][:2000]}, {"role": "assistant", "content": row["answer"][:5000]}]
        parent_id = row["parent_id"]
    return messages


if __name__ == "__main__":
    migrate()
    print("Research schema ready.")
