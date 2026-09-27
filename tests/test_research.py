import os
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch
import research as r
import research_store as db
import research_http as http
import jev_research as jev
import writer

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ, {'ZEARCH_DB_PATH':self.temp.name+'/test.db','ZEARCH_SESSION_SECRET':'s'*40,'ZEARCH_JEV_INPUT_USD_PER_MILLION':'1','ZEARCH_SEARCH_USD_PER_CALL':'.01','ZEARCH_WRITER_INPUT_USD_PER_MILLION':'1','ZEARCH_WRITER_OUTPUT_USD_PER_MILLION':'2'},clear=True)
        self.env.start();db.migrate()
        self.limits=dict(global_calls=100,user_calls=10,global_budget=10000000,user_budget=1000000)
    def tearDown(self): self.env.stop();self.temp.cleanup()
    def reserve(self,owner='alice',request=None,parent=None):
        return db.reserve(owner,uuid.uuid4().hex,request or uuid.uuid4().hex,'Question',parent,'test',100,self.limits)
    def test_owner_isolation(self):
        run,_=self.reserve();self.assertIsNone(db.get_run('bob',run['id']))
        with self.assertRaises(ValueError):self.reserve('bob',parent=run['id'])
    def test_idempotency(self):
        run,fresh=self.reserve(request='a'*32);again,fresh=self.reserve(request='a'*32)
        self.assertFalse(fresh);self.assertEqual(run['id'],again['id'])
        with self.assertRaises(ValueError):db.reserve('alice',uuid.uuid4().hex,'a'*32,'Different',None,'test',100,self.limits)
    def test_concurrent_budget(self):
        self.limits['global_calls']=3
        def attempt(_):
            try:self.reserve();return True
            except db.LimitReached:return False
        with ThreadPoolExecutor(max_workers=8) as pool:self.assertEqual(sum(pool.map(attempt,range(12))),3)
    def pipeline(self):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(r, 'search', return_value=[
            {'n': 1, 'url': 'https://example.com', 'title': 'Source',
             'text': 'Evidence answers the Question.', 'domain': 'example.com'}]))
        stack.enter_context(patch.object(jev, 'call', return_value={
            'model': 'jev-1.13', 'answers': {
                'best_passage': {'type': 'choice', 'choice': '1', 'confidence': .9,
                                 'probabilities': {'1': .9, 'none': .1}},
                'sufficient': {'type': 'noul', 'noul': .95},
                'conflict': {'type': 'noul', 'noul': .1}},
            'usage': {'input_tokens': 10, 'output_tokens': 0}}))
        stack.enter_context(patch.object(writer, 'compose', return_value=(
            'Evidence answers the Question. [1]', {'model':'test-writer','input_tokens':20,'output_tokens':10})))
        stack.enter_context(patch.object(jev, 'verify', return_value=(
            True, {'probabilities':[.97], 'model':'jev-1.13'}, {'input_tokens':5})))
        return stack
    def test_complete_persisted(self):
        run,_=self.reserve()
        with self.pipeline():
            events=list(r.run('alice',run,[]))
        self.assertEqual(events[-1]['type'],'complete');self.assertEqual(db.get_run('alice',run['id'])['estimated_cost'],10055)
    def test_close_does_not_overwrite_complete(self):
        run,_=self.reserve()
        with self.pipeline():
            gen=r.run('alice',run,[])
            for event in gen:
                if event['type']=='complete':break
            gen.close()
        self.assertEqual(db.get_run('alice',run['id'])['status'],'complete')
    def test_disconnect_at_start(self):
        run,_=self.reserve();gen=r.run('alice',run,[]);next(gen);gen.close()
        self.assertEqual(db.get_run('alice',run['id'])['status'],'interrupted')
    def test_failure_has_no_mock(self):
        run,_=self.reserve()
        with patch.object(r,'search',side_effect=r.Unavailable('Search unavailable')):events=list(r.run('alice',run,[]))
        saved=db.get_run('alice',run['id']);self.assertEqual(saved['status'],'error');self.assertEqual(saved['answer'],'');self.assertEqual(events[-1]['type'],'error')
    def test_writer_and_jev_checked_answer(self):
        run,_=self.reserve()
        with self.pipeline():list(r.run('alice',run,[]))
        saved=db.get_run('alice',run['id'])
        self.assertIn('Evidence answers the Question.',saved['answer'])
        self.assertEqual(saved['usage']['judgment']['model'],'jev-1.13')
        self.assertEqual(saved['usage']['answer_format'],'jev_verified_prose')
        self.assertEqual(saved['usage']['draft_check']['probabilities'],[.97])
    def test_rejected_draft_falls_back_to_excerpt(self):
        run,_=self.reserve()
        with self.pipeline(), patch.object(jev,'verify',return_value=(False,{'probabilities':[.2]},{'input_tokens':5})):
            list(r.run('alice',run,[]))
        saved=db.get_run('alice',run['id'])
        self.assertEqual(saved['usage']['answer_format'],'jev_selected_excerpt')
        self.assertTrue(saved['usage']['draft_rejected'])
    def test_cookie_tamper(self):
        owner,cookie=http.identity({},True);self.assertEqual(http.identity({'Cookie':cookie})[0],owner)
        self.assertIsNone(http.identity({'Cookie':cookie.replace('zearch_session=','zearch_session=a')})[0])
    def test_production_requires_database(self):
        with patch.dict(os.environ,{'VERCEL':'1'}):
            with self.assertRaises(RuntimeError):db.migrate()
    def test_hosted_schema_initialization_is_once_per_database(self):
        previous = db._schema_ready_for
        db._schema_ready_for = None
        try:
            with patch.dict(os.environ, {'DATABASE_URL':'postgresql://example/test'}), \
                 patch.object(db, 'migrate') as migration:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(lambda _: db.ensure_schema(), range(20)))
                self.assertEqual(migration.call_count, 1)
                db.ensure_schema()
                self.assertEqual(migration.call_count, 1)
            with patch.dict(os.environ, {'DATABASE_URL':'postgresql://example/other'}), \
                 patch.object(db, 'migrate') as migration:
                db.ensure_schema()
                self.assertEqual(migration.call_count, 1)
        finally:
            db._schema_ready_for = previous
    def test_failed_initialization_can_retry(self):
        previous = db._schema_ready_for
        db._schema_ready_for = None
        try:
            with patch.dict(os.environ, {'DATABASE_URL':'postgresql://example/test'}), \
                 patch.object(db, 'migrate', side_effect=[RuntimeError('unreachable'), None]) as migration:
                with self.assertRaises(RuntimeError): db.ensure_schema()
                db.ensure_schema()
                self.assertEqual(migration.call_count, 2)
        finally:
            db._schema_ready_for = previous
    def test_invalid_input(self):
        for value in [None,{}, {'query':'a','request_id':'bad'}, {'query':'a'*2001,'request_id':'a'*32}]:
            with self.assertRaises(ValueError):r.validate(value)
        self.assertIsNone(r.safe_url('javascript:alert(1)'));self.assertIsNone(r.safe_url('https://user:pass@example.com'))
        self.assertEqual(r.validate({'query':'Compare two options','request_id':'a'*32,'depth':'compare'})[0], 'Compare two options')

    def test_default_search_and_pinned_writer_rates(self):
        with patch.dict(os.environ, {'ZEARCH_WRITER_MODEL':'gpt-5.4-mini'}, clear=False):
            with patch.dict(os.environ, {'ZEARCH_SEARCH_USD_PER_CALL':'', 'ZEARCH_WRITER_INPUT_USD_PER_MILLION':''}):
                self.assertEqual(r.rates()[1:3], [Decimal('0.008'), Decimal('0.75')])
    def test_http_stream_and_private_reload(self):
        import threading, json, urllib.request, urllib.error
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):http.post(self)
            def do_GET(self):http.get(self)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        url='http://127.0.0.1:'+str(server.server_port)+'/api/research'
        try:
            with patch.object(r,'ready',return_value=True),patch.dict(os.environ,{'JEV_MODEL':'test'}),self.pipeline():
                request=urllib.request.Request(url,data=json.dumps({'query':'Question','request_id':'x'*32}).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request) as response:
                    cookie=response.headers['Set-Cookie'];events=[json.loads(line) for line in response]
                rid=events[-1]['run']['id'];self.assertEqual(events[-1]['type'],'complete')
                with urllib.request.urlopen(urllib.request.Request(url+'?id='+rid,headers={'Cookie':cookie})) as response:self.assertIn('Evidence answers the Question.',json.load(response)['answer'])
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url+'?id='+rid)
                self.assertEqual(error.exception.code,404)
        finally:server.shutdown();server.server_close();worker.join()
    def test_invalid_pricing(self):
        with patch.dict(os.environ,{'ZEARCH_JEV_INPUT_USD_PER_MILLION':'NaN'}):
            with self.assertRaises(r.Unavailable):r.reservation()

if __name__=='__main__':unittest.main()
