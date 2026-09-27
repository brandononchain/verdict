import os
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import research as r
import research_store as db
import research_http as http

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ, {'ZEARCH_DB_PATH':self.temp.name+'/test.db','ZEARCH_SESSION_SECRET':'s'*40,'ZEARCH_INPUT_USD_PER_MILLION':'1','ZEARCH_OUTPUT_USD_PER_MILLION':'2','ZEARCH_SEARCH_USD_PER_CALL':'.01'},clear=True)
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
    def pipeline(self,run,stream):
        return patch.multiple(r,search=lambda _: [{'n':1,'url':'https://example.com','title':'Source','text':'Evidence'}],stream_model=lambda _:iter(stream))
    def test_complete_persisted(self):
        run,_=self.reserve()
        with self.pipeline(run,[('delta','Answer [1]'),('usage',{'prompt_tokens':10,'completion_tokens':5})]):
            events=list(r.run('alice',run,[]))
        self.assertEqual(events[-1]['type'],'complete');self.assertEqual(db.get_run('alice',run['id'])['estimated_cost'],10020)
    def test_close_does_not_overwrite_complete(self):
        run,_=self.reserve()
        with self.pipeline(run,[('delta','Answer [1]')]):
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
    def test_citation_ids(self):
        answer,warnings=r.citations('Claim [99]',[{'n':1}]);self.assertNotIn('[99]',answer);self.assertEqual(len(warnings),2)
    def test_cookie_tamper(self):
        owner,cookie=http.identity({},True);self.assertEqual(http.identity({'Cookie':cookie})[0],owner)
        self.assertIsNone(http.identity({'Cookie':cookie.replace('zearch_session=','zearch_session=a')})[0])
    def test_production_requires_database(self):
        with patch.dict(os.environ,{'VERCEL':'1'}):
            with self.assertRaises(RuntimeError):db.migrate()
    def test_invalid_input(self):
        for value in [None,{}, {'query':'a','request_id':'bad'}, {'query':'a'*2001,'request_id':'a'*32}]:
            with self.assertRaises(ValueError):r.validate(value)
        self.assertIsNone(r.safe_url('javascript:alert(1)'));self.assertIsNone(r.safe_url('https://user:pass@example.com'))
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
            with patch.object(r,'ready',return_value=True),patch.dict(os.environ,{'ZEARCH_MODEL':'test'}),self.pipeline(None,[('delta','Answer [1]')]):
                request=urllib.request.Request(url,data=json.dumps({'query':'Question','request_id':'x'*32}).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request) as response:
                    cookie=response.headers['Set-Cookie'];events=[json.loads(line) for line in response]
                rid=events[-1]['run']['id'];self.assertEqual(events[-1]['type'],'complete')
                with urllib.request.urlopen(urllib.request.Request(url+'?id='+rid,headers={'Cookie':cookie})) as response:self.assertEqual(json.load(response)['answer'],'Answer [1]')
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url+'?id='+rid)
                self.assertEqual(error.exception.code,404)
        finally:server.shutdown();server.server_close();worker.join()
    def test_invalid_pricing(self):
        with patch.dict(os.environ,{'ZEARCH_INPUT_USD_PER_MILLION':'NaN'}):
            with self.assertRaises(r.Unavailable):r.reservation()

if __name__=='__main__':unittest.main()
