import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import enrichment
import research_store as db
import source_store


class Response:
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_): return json.dumps({'markdown': {'data': 'Extracted article. ' * 20},
        'metadata': {'title': 'Extracted title'}}).encode()


class SourceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'ZEARCH_DB_PATH': self.tmp.name + '/research.sqlite3',
            'ZEARCH_ENRICHMENT_ENABLED': '1', 'CONTEXT_DEV_API_KEY': 'test'})
        self.env.start()
        db.migrate()
        self.policy = Path(self.tmp.name) / 'policy.json'
        self.policy.write_text(json.dumps({'version': 1, 'domains': {}}))
        self.policy_patch = patch.object(source_store, 'POLICY', self.policy)
        self.policy_patch.start()
        self.source = {'n': 1, 'url': 'https://example.org/article?utm_source=search',
            'title': 'Search title', 'text': 'Search excerpt', 'domain': 'example.org',
            'published_date': '2026-09-27', 'published_date_provenance': 'provider_metadata'}

    def tearDown(self):
        self.policy_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def allow(self):
        self.policy.write_text(json.dumps({'version': 1, 'domains': {'example.org': {
            'cache_extracted_content': True, 'basis': 'Test fixture permission',
            'reviewed_at': '2026-09-28', 'ttl_seconds': 3600}}}))

    def test_default_policy_never_reuses_extractions(self):
        with patch.object(enrichment, 'open_provider', return_value=Response()) as provider:
            enrichment.enrich([dict(self.source)])
            enrichment.enrich([dict(self.source)])
        self.assertEqual(provider.call_count, 2)
        self.assertIsNone(source_store.lookup(self.source['url']))

    def test_allowed_cache_hit_expiry_and_tombstone(self):
        self.allow()
        with patch.object(enrichment, 'open_provider', return_value=Response()) as provider:
            first, first_report = enrichment.enrich([dict(self.source)])
            second, second_report = enrichment.enrich([dict(self.source)])
        self.assertEqual(provider.call_count, 1)
        self.assertEqual((first_report['scrape_calls'], second_report['scrape_calls']), (1, 0))
        self.assertEqual(second_report['cache_hits'], 1)
        self.assertEqual(first[0]['text'], second[0]['text'])
        self.assertEqual(first[0]['retrieved_at'], second[0]['retrieved_at'])
        self.assertEqual(source_store.version_id(first[0]), second[0]['source_version_id'])
        self.assertIsNone(source_store.lookup(self.source['url'], now=int(time.time()) + 3601))
        source_store.tombstone(self.source['url'])
        self.assertIsNone(source_store.lookup(self.source['url']))
        self.assertFalse(source_store.save(first[0]))

    def test_policy_requires_exact_host_and_review_basis(self):
        self.allow()
        self.assertIsNone(source_store.policy_for('https://sub.example.org/article'))
        self.assertIsNone(source_store.policy_for('http://example.org/article'))
        self.assertIsNotNone(source_store.policy_for(self.source['url']))
        self.policy.write_text(json.dumps({'version': 1, 'domains': {'example.org': {
            'cache_extracted_content': True, 'ttl_seconds': 3600}}}))
        self.assertIsNone(source_store.policy_for(self.source['url']))


if __name__ == '__main__': unittest.main()
