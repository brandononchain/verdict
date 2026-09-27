import concurrent.futures
import json
import os
import time
import unittest
import uuid
from unittest.mock import patch
import test_research as baseline
import discovery
import research
import jev_research as jev
import writer
import research_store as db
import retrieval
import workspace_store as workspace

class WorkspaceTests(unittest.TestCase):
    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown
    reserve = baseline.ResearchTests.reserve
    pipeline = baseline.ResearchTests.pipeline

    def completed(self, owner='alice'):
        run, _ = self.reserve(owner)
        db.save(owner, run['id'], status='complete', answer='Answer [1]', sources=[{'n':1,'url':'https://example.com/','text':'Old text'}])
        return run['id']

    def test_migration_reentrant(self):
        db.migrate(); db.migrate()
        self.assertEqual(workspace.notes('alice'), [])

    def test_notes_private_and_opt_in(self):
        note = workspace.add_note('alice', 'Project budget', 'The project budget is 500 credits.')
        workspace.add_note('bob', 'Secret', 'Secret project budget is 999 credits.')
        selected = workspace.knowledge('alice', 'project budget')
        self.assertEqual(len(selected), 1); self.assertEqual(selected[0]['note_id'], note['id'])
        self.assertFalse(workspace.delete_note('bob', note['id']))
        self.assertTrue(workspace.delete_note('alice', note['id']))
        self.assertEqual(workspace.knowledge('alice', 'project budget'), [])

    def test_private_text_never_enters_search_query(self):
        workspace.add_note('alice', 'Budget', 'Confidential budget amount is 500 credits.')
        source = {'n': 1, 'url': 'https://example.com/', 'text': 'Public budget evidence',
                  'title': 'Source', 'domain': 'example.com'}
        with self.pipeline():
            for use_notes in (False, True):
                with self.subTest(use_notes=use_notes), patch.dict(os.environ, {'JEV_MODEL': 'test'}), \
                     patch.object(research, 'ready', return_value=True), \
                     patch.object(research, 'search', return_value=[source]) as search, \
                     patch.object(jev, 'call', return_value={
                         'model': 'jev-latest', 'answers': {
                             'best_passage': {'choice':'1','probabilities':{'1':.9}},
                             'sufficient':{'noul':.9}, 'conflict':{'noul':.1}},
                         'usage':{'input_tokens':10}}) as model:
                    run, _, history = research.prepare('alice', {'query':'budget',
                        'request_id':uuid.uuid4().hex,'use_knowledge':use_notes})
                    list(research.run('alice',run,history))
                    self.assertNotIn('Confidential',str(search.call_args))
                    self.assertEqual('Confidential' in str(model.call_args),use_notes)

    def test_note_limits_atomic(self):
        def add(n):
            try: workspace.add_note('alice',str(n),'text'); return 1
            except ValueError: return 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(add,range(25))),20)

    def test_delete_run_does_not_refund_budget(self):
        rid = self.completed()
        self.assertFalse(workspace.delete_run('bob',rid))
        self.assertTrue(workspace.delete_run('alice',rid))
        self.assertIsNone(db.get_run('alice',rid)); self.assertEqual(workspace.allowance('alice')['used'],1)

    def test_pending_cannot_be_deleted(self):
        run,_=self.reserve()
        with self.assertRaises(ValueError): workspace.delete_run('alice',run['id'])

    def test_options_idempotency(self):
        rid=uuid.uuid4().hex; request=uuid.uuid4().hex
        run,_=db.reserve('alice',rid,request,'Q',None,'test',100,self.limits,'deep',True)
        self.assertEqual(db.get_run('alice',rid)['depth'],'deep')
        with self.assertRaises(ValueError): db.reserve('alice',uuid.uuid4().hex,request,'Q',None,'test',100,self.limits,'standard',True)

    def test_deep_reservation_accounts_for_all_searches(self):
        self.assertEqual(research.reservation('deep')-research.reservation('standard'),20000)
        self.assertEqual(research.reservation('compare'),research.reservation('deep'))
        usage={'input_tokens':10,'search_calls':3}
        self.assertEqual(research.estimate(usage),30010)

    def test_job_enqueue_deduplicates_under_concurrency(self):
        iid=workspace.save_investigation('alice',self.completed())
        with patch.dict(os.environ,{'ZEARCH_DISCOVERY_ENABLED':'1'}):
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                jobs=list(pool.map(lambda _:discovery.enqueue('alice',iid),range(12)))
            self.assertEqual(len(set(jobs)),1)
            with self.assertRaises(ValueError):discovery.enqueue('bob',iid)

    def test_claim_and_completion(self):
        iid=workspace.save_investigation('alice',self.completed())
        with patch.dict(os.environ,{'ZEARCH_DISCOVERY_ENABLED':'1'}),patch.object(research,'ready',return_value=True):
            discovery.enqueue('alice',iid)
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                claims=list(pool.map(lambda _:discovery.tick(),range(4)))
            self.assertEqual(sum(c is not None for c in claims),1)
            job=next(c for c in claims if c)
            run=db.get_run('alice',job['last_run']); run['sources'][0]['text']='New text'
            discovery.finish(job,run)
            saved=workspace.saved('alice')[0]
            self.assertEqual(saved['job']['status'],'complete')
            self.assertEqual(saved['last_changes']['changed'],['https://example.com/'])

    def test_stale_worker_cannot_publish(self):
        iid=workspace.save_investigation('alice',self.completed())
        with patch.dict(os.environ,{'ZEARCH_DISCOVERY_ENABLED':'1'}),patch.object(research,'ready',return_value=True):
            discovery.enqueue('alice',iid);job=discovery.tick()
            with db.connection() as (conn,marker):db.execute(conn,marker,'UPDATE discovery_jobs SET lease_until=1 WHERE id=?',(job['id'],))
            self.assertIsNone(discovery.tick())
            discovery.finish(job,db.get_run('alice',job['last_run']))
            self.assertEqual(workspace.saved('alice')[0]['job']['status'],'failed')

    def test_due_schedule_queues_once_and_pause_cancels(self):
        iid=workspace.save_investigation('alice',self.completed())
        with patch.dict(os.environ,{'ZEARCH_DISCOVERY_ENABLED':'1'}),patch.object(research,'ready',return_value=True):
            discovery.schedule('alice',iid,24)
            with db.connection() as (conn,marker):db.execute(conn,marker,'UPDATE investigations SET next_run=0 WHERE id=?',(iid,))
            job=discovery.tick();self.assertIsNotNone(job);self.assertIsNone(discovery.tick())
            with self.assertRaises(ValueError):discovery.remove('alice',iid)
            discovery.finish(job,error='test failure')
            discovery.enqueue('alice',iid);discovery.schedule('alice',iid,0)
            self.assertIsNone(discovery.tick())

    def test_worker_runs_pipeline_once(self):
        iid=workspace.save_investigation('alice',self.completed())
        source={'n':1,'url':'https://example.com/','text':'Updated evidence','title':'Source','domain':'example.com'}
        with patch.dict(os.environ,{'ZEARCH_DISCOVERY_ENABLED':'1','JEV_MODEL':'test'}),patch.object(research,'ready',return_value=True),patch.object(research,'search',return_value=[source]) as search,patch.object(writer,'compose',side_effect=writer.WriterError('unavailable')),patch.object(jev,'call',return_value={'model':'jev-latest','answers':{'best_passage':{'choice':'1','probabilities':{'1':.9}},'sufficient':{'noul':.9},'conflict':{'noul':.1}},'usage':{'input_tokens':10}}):
            discovery.enqueue('alice',iid)
            self.assertTrue(discovery.work_once());self.assertFalse(discovery.work_once())
            self.assertEqual(search.call_count,1)
            self.assertEqual(workspace.saved('alice')[0]['job']['status'],'complete')

    def test_expired_schedule_cannot_enqueue(self):
        iid=workspace.save_investigation('alice',self.completed())
        with db.connection() as (conn,marker):db.execute(conn,marker,'UPDATE investigations SET expires=1 WHERE id=?',(iid,))
        with patch.dict(os.environ,{'ZEARCH_DISCOVERY_ENABLED':'1'}):
            with self.assertRaises(ValueError):discovery.enqueue('alice',iid)

class RetrievalTests(unittest.TestCase):
    def test_plan_bounded(self):
        self.assertEqual(len(retrieval.plan('question',[],'deep')),3)
        self.assertEqual(len(retrieval.plan('question',[],'compare')),3)
        self.assertIn('tradeoffs',retrieval.plan('question',[],'compare')[2])
        self.assertEqual(len(retrieval.plan('question',[],'standard')),1)

    def test_dedup_ranking_and_domain_diversity(self):
        rows=[{'url':'https://example.com/a?utm_source=ad','text':'Solar battery storage','title':'Solar','domain':'example.com'},
              {'url':'https://example.com/a','text':'Solar battery storage and costs','title':'Solar','domain':'example.com'},
              {'url':'https://example.com/b','text':'Other energy source','title':'Energy','domain':'example.com'},
              {'url':'https://example.com/c','text':'Battery chemistry tradeoffs','title':'Chemistry','domain':'example.com'},
              {'url':'https://independent.org/','text':'Independent battery solar comparison','title':'Solar comparison','domain':'independent.org'}]
        ranked=retrieval.rank('solar battery',rows)
        self.assertLessEqual(sum(s['domain']=='example.com' for s in ranked),2)
        self.assertEqual(len({retrieval.canonical(s['url']) for s in ranked}),len(ranked))
        self.assertEqual([s['n'] for s in ranked],list(range(1,len(ranked)+1)))

    def test_partial_search_failure_is_visible(self):
        def search(q):
            if 'limitations' in q:raise RuntimeError('provider failed')
            return [{'url':'https://example.com/','title':'Source','domain':'example.com','text':'Evidence'}]
        result,report=retrieval.retrieve('question',[],'deep',search)
        self.assertEqual(len(result),1);self.assertEqual(report['failed_searches'],1);self.assertEqual(report['search_calls'],3)
