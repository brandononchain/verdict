import io
import json
import os
import unittest
import uuid
from unittest.mock import patch

import test_research as baseline
import artifact
import research
import research_store as db
import web_ingest
import workspace_store as workspace


class WebIngestTests(unittest.TestCase):
    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown
    pipeline = baseline.ResearchTests.pipeline

    def test_public_url_validation_and_options_replay(self):
        for url in ('http://example.com', 'https://localhost/', 'https://127.0.0.1/',
                    'https://127.1/', 'https://metadata.google.internal/',
                    'https://user:pass@example.com/', 'file:///etc/passwd'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                research.validate({'query':'Summarize','request_id':'a'*32,'depth':'scrape','target_url':url})
        body={'query':'Summarize','request_id':'a'*32,'depth':'scrape','target_url':'https://example.com/page'}
        with patch.object(research,'ready',return_value=True):
            run, fresh, _ = research.prepare('alice',body)
            self.assertTrue(fresh)
            self.assertEqual(db.get_run('alice',run['id'])['target_url'],body['target_url'])
            again, fresh, _ = research.prepare('alice',body)
            self.assertFalse(fresh)
            self.assertEqual(again['id'],run['id'])
            with self.assertRaises(ValueError):
                research.prepare('alice',dict(body,target_url='https://example.com/other'))
        with self.assertRaises(ValueError):
            research.validate(dict(body,depth='standard'))

    def test_extract_and_crawl_are_bounded_and_same_host(self):
        rows=[{'url':'https://example.com/','raw_content':'A supported fact about the home page. '*4},
              {'url':'https://example.com/docs','raw_content':'Documentation with supported evidence. '*4},
              {'url':'https://other.example.net/','raw_content':'Unrelated external page. '*4},
              {'url':'http://example.com/insecure','raw_content':'Insecure page content. '*4}]
        with patch.object(web_ingest,'_request',return_value={'results':rows,'failed_results':[{}]}) as call:
            sources, report=web_ingest.collect('https://example.com/','crawl')
            self.assertEqual(len(sources),2)
            self.assertEqual(report['crawl_calls'],1)
            self.assertEqual(report['failed_pages'],1)
            self.assertEqual(call.call_args.args[1]['limit'],5)
            self.assertFalse(call.call_args.args[1]['allow_external'])
            self.assertEqual(call.call_args.args[1]['select_domains'],['^example\\.com$'])
        with patch.object(web_ingest,'_request',return_value={'results':rows}) as call:
            sources, report=web_ingest.collect('https://example.com/','scrape')
            self.assertEqual([s['url'] for s in sources],['https://example.com/'])
            self.assertEqual(report['extract_calls'],1)
            self.assertEqual(call.call_args.args[1]['urls'],'https://example.com/')

    def test_jev_writer_flow_dataset_export_and_deletion(self):
        source={'n':1,'url':'https://example.com/page','canonical_url':'https://example.com/page',
                'text':'Evidence answers the Question. '*5,'excerpt':'Evidence answers the Question.',
                'title':'Example page','domain':'example.com','retrieved_at':1750000000,
                'content_type':'extracted_page','retrieval_provider':'tavily_extract'}
        body={'query':'Question','request_id':uuid.uuid4().hex,'depth':'scrape','target_url':'https://example.com/page'}
        with patch.object(research,'ready',return_value=True), patch.object(web_ingest,'collect',return_value=(
                [source],{'queries':[],'search_calls':0,'extract_calls':1,'crawl_calls':0,'failed_pages':0,
                          'candidate_urls':[source['url']],'selected_urls':[source['url']],'ranking':'extraction'})):
            record,_,history=research.prepare('alice',body)
            with self.pipeline():
                events=list(research.run('alice',record,history))
        self.assertEqual(events[-1]['type'],'complete')
        saved=db.get_run('alice',record['id'])
        self.assertEqual(saved['usage']['answer_format'],'jev_verified_prose')
        self.assertEqual(saved['usage']['search_calls'],0)
        self.assertEqual(saved['usage']['extract_calls'],1)
        self.assertEqual(saved['estimated_cost'],10055)
        self.assertEqual(len(saved['sources'][0]['source_version_id']),64)
        import usage_report
        summary=usage_report.report()['scrape']
        self.assertEqual(summary['runs'],1)
        self.assertEqual(summary['complete'],1)
        self.assertEqual(summary['source_tiers'],{'web':1})
        self.assertNotIn(body['query'],str(summary))
        data=json.loads(artifact.data_json(saved))
        self.assertEqual(data['pages'][0]['text'],source['text'])
        self.assertEqual(data['target_url'],body['target_url'])
        with self.assertRaises(ValueError): workspace.save_investigation('alice',saved['id'])
        self.assertTrue(workspace.delete_run('alice',saved['id']))
        self.assertIsNone(db.get_run('alice',saved['id']))

    def test_export_endpoint_is_owner_scoped(self):
        import research_http
        class Handler:
            def __init__(self,path,cookie):
                self.path=path; self.headers={'Cookie':cookie}; self.wfile=io.BytesIO(); self.status=None
            def send_response(self,value): self.status=value
            def send_header(self,*_): pass
            def end_headers(self): pass
        alice=research_http.identity({},True)[1].split(';',1)[0]
        bob=research_http.identity({},True)[1].split(';',1)[0]
        owner,_=research_http.identity({'Cookie':alice})
        with patch.object(research,'ready',return_value=True):
            run,_,_=research.prepare(owner,{'query':'Question','request_id':uuid.uuid4().hex,
                'depth':'crawl','target_url':'https://example.com/'})
        db.save(owner,run['id'],status='complete',answer='Answer [1]',sources=[{'n':1,'url':'https://example.com/','text':'Evidence'}])
        path='/api/artifact?id='+run['id']+'&format=json'
        denied=Handler(path,bob); artifact.handle(denied)
        self.assertEqual(denied.status,404)
        allowed=Handler(path,alice); artifact.handle(allowed)
        self.assertEqual(allowed.status,200)
        self.assertEqual(json.loads(allowed.wfile.getvalue())['kind'],'crawl')
        workspace.delete_run(owner,run['id'])
        after=Handler(path,alice); artifact.handle(after)
        self.assertEqual(after.status,404)


if __name__ == '__main__': unittest.main()
