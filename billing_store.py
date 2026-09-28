"""Account credit ledger foundation. Internal API only; no checkout or public grants."""
import time
import uuid

import research_store as db


class CreditError(ValueError):
    pass


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS credit_wallets (
        account_id TEXT PRIMARY KEY, available BIGINT NOT NULL DEFAULT 0,
        plan TEXT NOT NULL DEFAULT 'explore', status TEXT NOT NULL DEFAULT 'inactive',
        period_end BIGINT NOT NULL DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS credit_ledger (
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL, kind TEXT NOT NULL,
        reference TEXT NOT NULL, delta BIGINT NOT NULL, created BIGINT NOT NULL,
        UNIQUE(kind,reference))''')
    conn.execute('CREATE INDEX IF NOT EXISTS credit_ledger_owner ON credit_ledger(account_id,created,id)')
    conn.execute('''CREATE TABLE IF NOT EXISTS credit_reservations (
        account_id TEXT NOT NULL, run_id TEXT NOT NULL, reserved BIGINT NOT NULL,
        charged BIGINT, status TEXT NOT NULL, created BIGINT NOT NULL,
        PRIMARY KEY(account_id,run_id))''')


def _account(conn, marker, account_id):
    if not isinstance(account_id, str) or len(account_id) != 32 or any(c not in '0123456789abcdef' for c in account_id):
        raise CreditError('Invalid account')
    if not db.execute(conn, marker, 'SELECT 1 FROM zearch_accounts WHERE id=?', (account_id,)).fetchone():
        raise CreditError('Account not found')
    db.execute(conn, marker, 'INSERT INTO credit_wallets(account_id) VALUES(?) ON CONFLICT(account_id) DO NOTHING', (account_id,))
    suffix = ' FOR UPDATE' if marker == '%s' else ''
    return db.execute(conn, marker, 'SELECT * FROM credit_wallets WHERE account_id=?' + suffix, (account_id,)).fetchone()


def _positive(amount):
    if type(amount) is not int or not 1 <= amount <= 1_000_000_000:
        raise CreditError('Invalid credit amount')


def _entry(conn, marker, account_id, kind, reference, delta):
    db.execute(conn, marker, '''INSERT INTO credit_ledger(id,account_id,kind,reference,delta,created)
        VALUES(?,?,?,?,?,?)''', (uuid.uuid4().hex, account_id, kind, reference, delta, time.time_ns()))
    db.execute(conn, marker, 'UPDATE credit_wallets SET available=available+? WHERE account_id=?', (delta, account_id))


def entitlement(account_id, plan, status, period_end):
    """Trusted operator API; payment events must be verified and ordered before calling."""
    if plan not in ('explore', 'plus', 'team') or status not in ('inactive', 'active', 'past_due', 'cancelled'):
        raise CreditError('Invalid entitlement')
    if type(period_end) is not int or period_end < 0:
        raise CreditError('Invalid entitlement period')
    with db.connection() as (conn, marker):
        _account(conn, marker, account_id)
        db.execute(conn, marker, 'UPDATE credit_wallets SET plan=?,status=?,period_end=? WHERE account_id=?',
                   (plan, status, period_end, account_id))


def grant(account_id, reference, amount):
    """Trusted, idempotent grant; reference must identify one verified external event."""
    _positive(amount)
    if not isinstance(reference, str) or not 1 <= len(reference) <= 128:
        raise CreditError('Invalid grant reference')
    with db.connection() as (conn, marker):
        _account(conn, marker, account_id)
        prior = db.execute(conn, marker, "SELECT account_id,delta FROM credit_ledger WHERE kind='grant' AND reference=?",
                           (reference,)).fetchone()
        if prior:
            if prior['account_id'] != account_id or prior['delta'] != amount:
                raise CreditError('Grant reference already belongs to another grant')
            return False
        _entry(conn, marker, account_id, 'grant', reference, amount)
        return True


def reserve(account_id, run_id, amount):
    _positive(amount)
    if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id):
        raise CreditError('Invalid run')
    with db.connection() as (conn, marker):
        wallet = _account(conn, marker, account_id)
        prior = db.execute(conn, marker, 'SELECT reserved FROM credit_reservations WHERE account_id=? AND run_id=?',
                           (account_id, run_id)).fetchone()
        if prior:
            if prior['reserved'] != amount: raise CreditError('Reservation has a different amount')
            return False
        if wallet['status'] != 'active' or wallet['period_end'] <= int(time.time()):
            raise CreditError('Active entitlement required')
        if wallet['available'] < amount:
            raise CreditError('Insufficient credits')
        db.execute(conn, marker, '''INSERT INTO credit_reservations(account_id,run_id,reserved,status,created)
            VALUES(?,?,?,'pending',?)''', (account_id, run_id, amount, int(time.time())))
        _entry(conn, marker, account_id, 'reserve', run_id, -amount)
        return True


def settle(account_id, run_id, charged):
    """Refund unused reserved credits once. Caller decides charge after provider-cost review."""
    if type(charged) is not int or charged < 0:
        raise CreditError('Invalid charge')
    with db.connection() as (conn, marker):
        _account(conn, marker, account_id)
        row = db.execute(conn, marker, 'SELECT reserved,charged,status FROM credit_reservations WHERE account_id=? AND run_id=?',
                         (account_id, run_id)).fetchone()
        if not row: raise CreditError('Reservation not found')
        if row['status'] == 'settled':
            if row['charged'] != charged: raise CreditError('Reservation settled for a different charge')
            return False
        if charged > row['reserved']: raise CreditError('Charge exceeds reservation')
        refund = row['reserved'] - charged
        if refund: _entry(conn, marker, account_id, 'refund', run_id, refund)
        db.execute(conn, marker, "UPDATE credit_reservations SET charged=?,status='settled' WHERE account_id=? AND run_id=?",
                   (charged, account_id, run_id))
        return True


def statement(account_id):
    with db.connection() as (conn, marker):
        wallet = dict(_account(conn, marker, account_id))
        rows = [dict(row) for row in db.execute(conn, marker,
            'SELECT kind,reference,delta,created FROM credit_ledger WHERE account_id=? ORDER BY created,id',
            (account_id,)).fetchall()]
        if wallet['available'] != sum(row['delta'] for row in rows):
            raise RuntimeError('Credit ledger does not reconcile')
        return {'plan': wallet['plan'], 'status': wallet['status'], 'period_end': wallet['period_end'],
                'available': wallet['available'], 'entries': rows}


def erase_account(conn, marker, account_id):
    """Delete beta credit records with the account; billing retention policy is still unapproved."""
    db.execute(conn, marker, 'DELETE FROM credit_reservations WHERE account_id=?', (account_id,))
    db.execute(conn, marker, 'DELETE FROM credit_ledger WHERE account_id=?', (account_id,))
    db.execute(conn, marker, 'DELETE FROM credit_wallets WHERE account_id=?', (account_id,))
