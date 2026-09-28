import concurrent.futures
import time
import unittest
import uuid

import test_research as baseline
import billing_store as billing
import research_store as db


class M12LedgerTests(unittest.TestCase):
    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown

    def account(self, address):
        account_id = uuid.uuid4().hex
        with db.connection() as (conn, marker):
            db.execute(conn, marker, 'INSERT INTO zearch_accounts(id,email,created) VALUES(?,?,?)',
                       (account_id, address, int(time.time())))
        billing.entitlement(account_id, 'plus', 'active', int(time.time()) + 3600)
        return account_id

    def test_grant_reserve_settle_and_replay(self):
        owner = self.account('a@example.com')
        run = uuid.uuid4().hex
        self.assertTrue(billing.grant(owner, 'verified-event-1', 1000))
        self.assertFalse(billing.grant(owner, 'verified-event-1', 1000))
        self.assertTrue(billing.reserve(owner, run, 600))
        self.assertFalse(billing.reserve(owner, run, 600))
        self.assertEqual(billing.statement(owner)['available'], 400)
        self.assertTrue(billing.settle(owner, run, 220))
        self.assertFalse(billing.settle(owner, run, 220))
        statement = billing.statement(owner)
        self.assertEqual(statement['available'], 780)
        self.assertEqual([(e['kind'], e['delta']) for e in statement['entries']],
                         [('grant', 1000), ('reserve', -600), ('refund', 380)])
        with self.assertRaises(billing.CreditError): billing.settle(owner, run, 221)
        with self.assertRaises(billing.CreditError): billing.reserve(owner, run, 601)

    def test_no_cross_account_grant_replay_or_unbacked_charge(self):
        alice = self.account('a@example.com')
        bob = self.account('b@example.com')
        billing.grant(alice, 'external-event', 500)
        with self.assertRaises(billing.CreditError): billing.grant(bob, 'external-event', 500)
        run = uuid.uuid4().hex
        billing.reserve(alice, run, 400)
        with self.assertRaises(billing.CreditError): billing.settle(bob, run, 0)
        with self.assertRaises(billing.CreditError): billing.settle(alice, run, 401)
        self.assertEqual(billing.statement(bob)['available'], 0)
        self.assertEqual(billing.statement(alice)['available'], 100)

    def test_concurrent_zero_balance_and_expired_entitlement(self):
        owner = self.account('a@example.com')
        billing.grant(owner, 'event', 100)
        def attempt(_):
            try:
                return billing.reserve(owner, uuid.uuid4().hex, 30)
            except billing.CreditError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(20))), 3)
        self.assertEqual(billing.statement(owner)['available'], 10)
        billing.entitlement(owner, 'plus', 'past_due', int(time.time()) + 3600)
        with self.assertRaises(billing.CreditError): billing.reserve(owner, uuid.uuid4().hex, 1)
        billing.entitlement(owner, 'plus', 'active', int(time.time()) - 1)
        with self.assertRaises(billing.CreditError): billing.reserve(owner, uuid.uuid4().hex, 1)

    def test_balance_is_not_operational_allowance(self):
        owner = self.account('a@example.com')
        billing.grant(owner, 'event', 100)
        self.assertEqual(billing.statement(owner)['available'], 100)
        self.assertIsNone(db.get_run('acct:' + owner, uuid.uuid4().hex))
        with self.assertRaises(billing.CreditError): billing.reserve('guest', uuid.uuid4().hex, 10)

    def test_account_erasure_clears_beta_credit_records(self):
        owner = self.account('a@example.com')
        billing.grant(owner, 'event', 100)
        run = uuid.uuid4().hex
        billing.reserve(owner, run, 30)
        with db.connection() as (conn, marker):
            billing.erase_account(conn, marker, owner)
            db.execute(conn, marker, 'DELETE FROM zearch_accounts WHERE id=?', (owner,))
        with db.connection() as (conn, marker):
            for table in ('credit_wallets', 'credit_reservations', 'credit_ledger'):
                self.assertEqual(db.execute(conn, marker, 'SELECT COUNT(*) AS n FROM '+table+' WHERE account_id=?',
                                            (owner,)).fetchone()['n'], 0)


if __name__ == '__main__': unittest.main()
