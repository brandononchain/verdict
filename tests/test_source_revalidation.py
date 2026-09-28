import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import research_store as db
import source_revalidation as worker
import source_store


class RevalidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'ZEARCH_DB_PATH': self.tmp.name + '/research.sqlite3',
            'ZEARCH_REVALIDATION_ENABLED': '1', 'ZEARCH_SCRAPE_USD_PER_CALL': '.01',
            'CONTEXT_DEV_API_KEY': 'test',
            'ZEARCH_DAILY_REVALIDATION_CALLS': '3', 'ZEARCH_DAILY_REVALIDATION_USD': '.03'})
        self.env.start()
        db.migrate()
        self.policy = Path(self.tmp.name) / 'policy.json'
        self.policy.write_text(json.dumps({'version': 1, 'domains': {'example.org': {
            'cache_extracted_content': True, 'basis': 'Test fixture permission',
            'reviewed_at': '2026-09-28', 'ttl_seconds': 3600}}}))
        self.policy_patch = patch.object(source_store, 'POLICY', self.policy)
        self.policy_patch.start()
        self.url = 'https://example.org/article'

    def tearDown(self):
        self.policy_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_claim_is_atomic_and_budgeted_before_provider_call(self):
        worker.enqueue(self.url, now=100)
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: worker.claim(now=100), range(8)))
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        job = next(claim for claim in claims if claim)
        with db.connection() as (conn, marker):
            budget = db.execute(conn, marker, 'SELECT calls,reserved FROM source_revalidation_budgets').fetchone()
        self.assertEqual(tuple(budget), (1, 10000))
        self.assertEqual(worker.report()['job_states'], {'running': 1})
        self.assertTrue(worker.finish(job, now=101))
        self.assertFalse(worker.finish(job, now=102))
        self.assertIsNone(worker.claim(now=102))

    def test_bounded_retry_and_daily_cap(self):
        worker.enqueue(self.url, now=100)
        first = worker.claim(now=100)
        self.assertTrue(worker.finish(first, error='timeout', now=101))
        self.assertIsNone(worker.claim(now=160))
        second = worker.claim(now=161)
        self.assertEqual(second['attempt'], 2)
        self.assertTrue(worker.finish(second, error='timeout', now=162))
        third = worker.claim(now=462)
        self.assertEqual(third['attempt'], 3)
        self.assertTrue(worker.finish(third, error='timeout', now=463))
        self.assertIsNone(worker.claim(now=9999))
        with db.connection() as (conn, marker):
            row = db.execute(conn, marker, 'SELECT state FROM source_revalidation_jobs WHERE url=?', (self.url,)).fetchone()
        self.assertEqual(row['state'], 'failed')

    def test_tombstone_blocks_queue_and_worker_defaults_off(self):
        worker.enqueue(self.url, now=100)
        with patch.dict(os.environ, {'ZEARCH_REVALIDATION_ENABLED': '0'}):
            self.assertIsNone(worker.claim(now=100))
        source_store.tombstone(self.url, now=101)
        self.assertIsNone(worker.claim(now=102))
        with self.assertRaises(ValueError): worker.enqueue(self.url, now=103)

    def test_exhausted_lease_becomes_failed_without_new_charge(self):
        worker.enqueue(self.url, now=100)
        for when in (100, 191, 282):
            job = worker.claim(now=when)
            self.assertIsNotNone(job)
        self.assertIsNone(worker.claim(now=373))
        self.assertEqual(worker.report()['job_states'], {'failed': 1})
        self.assertEqual(worker.report()['daily_reservations'][0]['calls'], 3)

    def test_zero_cap_or_missing_key_never_claims_a_paid_job(self):
        worker.enqueue(self.url, now=100)
        with patch.dict(os.environ, {'ZEARCH_DAILY_REVALIDATION_CALLS': '0'}):
            self.assertIsNone(worker.claim(now=100))
        with patch.dict(os.environ, {'CONTEXT_DEV_API_KEY': ''}):
            with self.assertRaises(ValueError): worker.claim(now=100)
        self.assertEqual(worker.report()['daily_reservations'], [])

    def test_worker_saves_fresh_extract_and_uses_no_network_in_test(self):
        worker.enqueue(self.url)
        with patch('enrichment.extract', return_value=('Fresh captured article. ' * 10, {'title': 'Fresh article'})) as extract:
            self.assertTrue(worker.work_once())
        self.assertEqual(extract.call_count, 1)
        cached = source_store.lookup(self.url)
        self.assertEqual(cached['title'], 'Fresh article')
        self.assertFalse(worker.work_once())


if __name__ == '__main__': unittest.main()
