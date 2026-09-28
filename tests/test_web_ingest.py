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
import writer
import jev_research as jev


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
            self.assertEqual(report['failed_pages'],2)
            crawl_payload=next(c.args[1] for c in call.call_args_list if c.args[0]=='crawl')
            self.assertEqual(crawl_payload['limit'],5)
            self.assertFalse(crawl_payload['allow_external'])
            self.assertEqual(crawl_payload['select_domains'],['^example\\.com$'])
            self.assertTrue(crawl_payload['include_images'])
            self.assertEqual(report['extract_calls'],1)
            self.assertEqual(call.call_count,2)
        with patch.object(web_ingest,'_request',return_value={'results':rows}) as call:
            sources, report=web_ingest.collect('https://example.com/','scrape')
            self.assertEqual([s['url'] for s in sources],['https://example.com/'])
            self.assertEqual(report['extract_calls'],1)
            self.assertEqual(call.call_args.args[1]['urls'],'https://example.com/')
            self.assertTrue(call.call_args.args[1]['include_favicon'])

    def test_broad_crawl_keeps_home_and_skips_status_and_extracts_assets(self):
        home={'url':'https://example.com/','title':'Home','raw_content':
              'We build useful tools for teams. ![Brand logo](/assets/logo.svg) Contact hello@example.com. ' * 2,
              'images':['https://cdn.example.net/graphic.png'],'favicon':'https://example.com/favicon.ico'}
        status={'url':'https://example.com/status','title':'Status',
                'raw_content':'No service-affecting failures were reported this month. ' * 2}
        product={'url':'https://example.com/product','title':'Product',
                 'raw_content':'The product helps teams work together. [Demo](https://youtu.be/abc123) ' * 2}
        def respond(endpoint, _):
            return {'results':[home]} if endpoint == 'extract' else {'results':[status,product,home]}
        with patch.object(web_ingest,'_request',side_effect=respond) as call:
            sources, report=web_ingest.collect('https://example.com/','crawl','Summarize the site')
        self.assertEqual([s['title'] for s in sources],['Home','Product'])
        self.assertIn('exclude_paths',next(c.args[1] for c in call.call_args_list if c.args[0]=='crawl'))
        self.assertNotIn('![',sources[0]['text'])
        self.assertIn('hello@example.com',sources[0]['emails'])
        self.assertEqual({a['kind'] for a in sources[0]['assets']},{'image','favicon','logo'})
        self.assertEqual(sources[1]['assets'][0]['kind'],'video')
        self.assertEqual(report['crawl_pages'],2)
        self.assertGreater(research.reservation('crawl'),research.reservation('scrape'))

    def test_asset_manifest_discards_unsafe_urls(self):
        found, emails, _ = web_ingest.assets({'images':['http://127.0.0.1/a.png',
            'javascript:alert(1)','https://cdn.example.net/image.png']},
            '![logo](file:///etc/passwd) [clip](https://youtu.be/example) admin@example.org.',
            'https://example.com/')
        self.assertEqual([item['kind'] for item in found],['image','video'])
        self.assertEqual(emails,['admin@example.org'])

    def test_jev_writer_flow_dataset_export_and_deletion(self):
        source={'n':1,'url':'https://example.com/page','canonical_url':'https://example.com/page',
                'text':'Evidence answers the Question. '*5,'excerpt':'Evidence answers the Question.',
                'title':'Example page','domain':'example.com','retrieved_at':1750000000,
                'content_type':'extracted_page','retrieval_provider':'tavily_extract',
                'description':'A public page','assets':[{'kind':'logo','url':'https://example.com/logo.svg','label':'Logo'}],
                'emails':['hello@example.com']}
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
        self.assertEqual(data['pages'][0]['assets'][0]['kind'],'logo')
        self.assertEqual(data['pages'][0]['emails'],['hello@example.com'])
        self.assertEqual(data['pages'][0]['description'],'A public page')
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

    def test_crawl_abstention_returns_captured_findings_when_writer_unavailable(self):
        source={'n':1,'url':'https://example.com/','canonical_url':'https://example.com/',
                'title':'Example home','domain':'example.com',
                'text':'The site offers a desktop workspace for AI teammates and product teams.',
                'excerpt':'The site offers a desktop workspace for AI teammates and product teams.',
                'retrieved_at':1750000000,'content_type':'extracted_page'}
        body={'query':'Summarize this site','request_id':uuid.uuid4().hex,
              'depth':'crawl','target_url':'https://example.com/'}
        abstain={'selected':None,'selected_probability':.7,'sufficiency_probability':.4,
                 'conflict_probability':.1,'gate':'abstain','evidence_ids':[],
                 'relevant_ids':[1],'model':'jev-test'}
        with patch.object(research,'ready',return_value=True), \
             patch.object(web_ingest,'collect',return_value=([source],{
                 'queries':[],'search_calls':0,'extract_calls':0,'crawl_calls':1,
                 'crawl_pages':1,'failed_pages':0,'candidate_urls':[source['url']],
                 'selected_urls':[source['url']],'ranking':'bounded crawl'})), \
             patch.object(jev,'judge',return_value=(abstain,None,{'input_tokens':10},[
                 {'id':'1','passage':source['text'],'span_start':0,'span_end':len(source['text'])}])), \
             patch.object(writer,'compose',side_effect=writer.WriterError('unavailable')):
            run,_,history=research.prepare('alice',body)
            list(research.run('alice',run,history))
        saved=db.get_run('alice',run['id'])
        self.assertEqual(saved['status'],'complete')
        self.assertEqual(saved['usage']['answer_format'],'captured_excerpts')
        self.assertIn('desktop workspace for AI teammates',saved['answer'])
        self.assertIn('[1]',saved['answer'])


if __name__ == '__main__': unittest.main()
