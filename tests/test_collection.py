import base64
import io
import json
import os
import time
import unittest
import uuid
from unittest.mock import patch

import test_research as baseline
import collection_batch as batches
import collection_visual as visuals
import collection_http
import discovery
import research
import research_store as db
import workspace_store as workspace


class CollectionTests(unittest.TestCase):
    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown

    def collected(self, owner='alice', mode='scrape', url='https://example.com/a'):
        with patch.object(research, 'ready', return_value=True):
            run, _, _ = research.prepare(owner, {'query':'Summarize this page',
                'request_id': uuid.uuid4().hex, 'depth': mode, 'target_url': url})
        db.save(owner, run['id'], status='complete', answer='The page has a product. [1]',
                sources=[{'n':1,'url':url,'title':'Product','text':'The page has a product.'}])
        return run['id']

    def test_site_monitor_keeps_target_and_compares_captures(self):
        rid = self.collected(mode='crawl', url='https://example.com/')
        iid = workspace.save_investigation('alice', rid)
        self.assertEqual(workspace.saved('alice')[0]['target_url'], 'https://example.com/')
        with patch.dict(os.environ, {'ZEARCH_DISCOVERY_ENABLED':'1'}), patch.object(research,'ready',return_value=True):
            discovery.schedule('alice', iid, 24)
            discovery.enqueue('alice', iid)
            job = discovery.tick()
            self.assertEqual(job['target_url'],'https://example.com/')
            self.assertEqual(job['depth'],'crawl')
            with patch.object(research,'prepare',return_value=(db.get_run('alice',rid),False,[])) as prepare:
                discovery.finish(job, db.get_run('alice',rid))
            self.assertEqual(workspace.saved('alice')[0]['last_changes']['changed'],[])
        self.assertTrue(discovery.remove('alice',iid))
        with db.connection() as (conn, marker):
            self.assertIsNone(db.execute(conn, marker,'SELECT * FROM investigation_targets WHERE investigation_id=?',(iid,)).fetchone())

    def test_batch_is_bounded_owner_scoped_and_one_page_per_worker(self):
        with patch.dict(os.environ, {'ZEARCH_DISCOVERY_ENABLED':'1'}), patch.object(research,'ready',return_value=True):
            with self.assertRaises(ValueError): batches.create('alice',['http://example.com/a','https://example.com/b'],'')
            bid = batches.create('alice',['https://example.com/a','https://example.com/b'],'Product facts')
            self.assertEqual(batches.list_for('bob'),[])
            first = batches.tick()
            self.assertEqual(first['batch_id'],bid)
            self.assertEqual(first['target_url'],'https://example.com/a')
            self.assertEqual(batches.list_for('alice')[0]['status'],'running')
            rid = self.collected(url=first['target_url'])
            batches.finish(first,db.get_run('alice',rid))
            self.assertEqual(batches.list_for('alice')[0]['items'][0]['status'],'complete')
            second = batches.tick()
            batches.finish(second,error='Provider unavailable')
            self.assertEqual(batches.list_for('alice')[0]['status'],'partial')
            self.assertEqual(batches.list_for('alice')[0]['items'][1]['status'],'failed')
            self.assertIsNone(batches.tick())
            workspace.delete_workspace('alice')
            self.assertEqual(batches.list_for('alice'),[])

    def test_visual_capture_is_explicit_owner_scoped_and_metered(self):
        rid = self.collected()
        jpeg = b'\xff\xd8\xff' + b'test'
        with patch.dict(os.environ, {'ZEARCH_VISUAL_CAPTURE_ENABLED':'1','ZEARCH_DAILY_VISUAL_USER':'1'}), \
             patch('visual_browser.render', return_value=(jpeg, {'colors':{'accent':'#ffffff'}})) as render:
            self.assertIsNone(visuals.get('alice',rid))
            result=visuals.capture('alice',rid)
            self.assertEqual(result['status'],'queued')
            self.assertIsNone(visuals.get('bob',rid))
            self.assertTrue(visuals.work_once())
            result = visuals.get('alice',rid)
            self.assertEqual(result['status'],'complete')
            self.assertTrue(result['screenshot'])
            self.assertEqual(result['styleguide']['colors']['accent'],'#ffffff')
            self.assertEqual(visuals.screenshot_bytes('alice',rid),('image/jpeg',jpeg))
            self.assertIsNone(visuals.screenshot_bytes('bob',rid))
            visuals.capture('alice',rid)
            self.assertEqual(render.call_count,1)
            second=self.collected(url='https://example.com/b')
            with self.assertRaisesRegex(ValueError,'allowance'):
                visuals.capture('alice',second)
        workspace.delete_run('alice',rid)
        self.assertIsNone(visuals.get('alice',rid))

    def test_visual_endpoint_does_not_expose_other_owner(self):
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
        rid=self.collected(owner)
        path='/api/collection?id='+rid
        denied=Handler(path,bob); collection_http.handle(denied)
        self.assertEqual(denied.status,404)
        allowed=Handler(path,alice); collection_http.handle(allowed)
        self.assertEqual(allowed.status,200)
        self.assertIsNone(json.loads(allowed.wfile.getvalue())['visual'])

    def test_browser_capture_rejects_private_destinations_and_invalid_images(self):
        from visual_browser import public_host
        self.assertFalse(public_host('http://example.com'))
        self.assertFalse(public_host('https://127.0.0.1'))
        with patch('visual_browser.socket.getaddrinfo', return_value=[(2, 1, 0, '', ('10.0.0.1',443))]):
            self.assertFalse(public_host('https://example.com'))
        rid = self.collected()
        with patch.dict(os.environ, {'ZEARCH_VISUAL_CAPTURE_ENABLED':'1'}):
            visuals.capture('alice',rid)
            job = visuals.claim()
            with self.assertRaisesRegex(ValueError,'invalid'):
                visuals.finish(job,b'<script>',{})

    def test_cancel_batch_does_not_cancel_running_page(self):
        with patch.dict(os.environ, {'ZEARCH_DISCOVERY_ENABLED':'1'}), patch.object(research,'ready',return_value=True):
            bid=batches.create('alice',['https://example.com/a','https://example.com/b'],'')
            running=batches.tick()
            with self.assertRaises(ValueError): batches.cancel('bob',bid)
            batches.cancel('alice',bid)
            parts=batches.list_for('alice')[0]['items']
            self.assertEqual([p['status'] for p in parts],['running','cancelled'])
            rid=self.collected(url=running['target_url'])
            batches.finish(running,db.get_run('alice',rid))
            self.assertIsNone(batches.tick())


if __name__ == '__main__': unittest.main()
