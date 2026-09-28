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
import workspace_store as workspace
import source_revalidation


class Response:
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_): return json.dumps({'markdown': {'data': 'Extracted article. ' * 20},
        'metadata': {'title': 'Extracted title'}}).encode()


class SourceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'ZEARCH_DB_PATH': self.tmp.name + '/research.sqlite3',
            'ZEARCH_ENRICHMENT_ENABLED': '1', 'TAVILY_API_KEY': 'test'})
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
        with patch.object(enrichment, '_request', return_value={'results':[{'raw_content':'Extracted article. ' * 20,'title':'Extracted title'}]}) as provider:
            enrichment.enrich([dict(self.source)])
            enrichment.enrich([dict(self.source)])
        self.assertEqual(provider.call_count, 2)
        self.assertIsNone(source_store.lookup(self.source['url']))

    def test_allowed_cache_hit_expiry_and_tombstone(self):
        self.allow()
        with patch.object(enrichment, '_request', return_value={'results':[{'raw_content':'Extracted article. ' * 20,'title':'Extracted title'}]}) as provider:
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

    def test_tombstone_redacts_retained_runs_and_future_evidence(self):
        self.allow()
        limits = dict(global_calls=20, user_calls=10, global_budget=1000000, user_budget=1000000)
        ids = []
        for owner in ('alice', 'bob'):
            rid = owner + 'a' * (32 - len(owner))
            db.reserve(owner, rid, owner + 'request', 'Question', None, 'test', 100, limits)
            db.save(owner, rid, status='complete', answer='Claim from extracted article [1]',
                sources=[dict(self.source, text='Captured page text', excerpt='Captured page text')],
                usage={'candidate_urls': [self.source['url']]})
            ids.append((owner, rid))
        iid = workspace.save_investigation('alice', ids[0][1])
        source_revalidation.enqueue(self.source['url'])
        self.assertEqual(source_store.tombstone('https://example.org/article'), 2)
        for owner, rid in ids:
            saved = db.get_run(owner, rid)
            self.assertEqual(saved['status'], 'redacted')
            self.assertEqual(saved['sources'], [])
            self.assertNotIn('Claim from', saved['answer'])
            self.assertEqual(saved['usage'], {'redacted_source': True})
        self.assertEqual(workspace.saved('alice')[0]['last_run'], None)
        self.assertEqual(workspace.saved('alice')[0]['interval_hours'], 0)
        with db.connection() as (conn, marker):
            self.assertIsNone(db.execute(conn, marker, 'SELECT url FROM source_revalidation_jobs').fetchone())
        kept, removed = source_store.excluded([dict(self.source, text='New copy', n=1)])
        self.assertEqual((kept, removed), ([], 1))
        db.save('alice', ids[0][1], status='complete', answer='Reintroduced claim', sources=[dict(self.source, text='New copy')])
        self.assertEqual(db.get_run('alice', ids[0][1])['status'], 'redacted')

    def test_tombstone_redacts_descendant_without_original_source(self):
        limits = dict(global_calls=20,user_calls=10,global_budget=1000000,user_budget=1000000)
        parent='a'*32; child='b'*32
        db.reserve('alice',parent,'parent-request','Question',None,'test',100,limits)
        db.save('alice',parent,status='complete',answer='Claim [1]',sources=[dict(self.source)])
        db.reserve('alice',child,'child-request','Follow up',parent,'test',100,limits)
        db.save('alice',child,status='complete',answer='Derived claim [1]',sources=[{
            'n':1,'url':'https://different.example/page','text':'Other source'}])
        self.assertEqual(source_store.tombstone('https://example.org/article'),2)
        self.assertEqual(db.get_run('alice',child)['status'],'redacted')
        db.save('alice',child,status='complete',answer='Reintroduced derived claim')
        self.assertEqual(db.get_run('alice',child)['status'],'redacted')


if __name__ == '__main__': unittest.main()
