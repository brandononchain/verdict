import base64
import io
import json
import os
import sqlite3
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import test_research as baseline
import account_http
import account_store as accounts
import artifact
import document_ingest
import research_http
import research_store as db
import source_revalidation as worker
import source_store
import workspace_store as workspace


class FakeHandler:
    def __init__(self, path='/', headers=None, body=b''):
        self.path = path
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status = None
        self.response_headers = {}

    def send_response(self, status): self.status = status
    def send_header(self, key, value): self.response_headers[key] = value
    def end_headers(self): pass
    def json(self): return json.loads(self.wfile.getvalue())


class ContentLengthTests(unittest.TestCase):
    def test_strict_parsing(self):
        cl = research_http.content_length
        self.assertEqual(cl({'Content-Length': '12'}, 100), 12)
        for bad in ('', '0', '-5', '1e3', '12 3', '٣', '101', 'abc'):
            with self.assertRaises(ValueError, msg=bad):
                cl({'Content-Length': bad}, 100)
        with self.assertRaises(ValueError):
            cl({}, 100)

    def test_research_post_rejects_bad_length(self):
        for bad in ('0', 'abc', '-1'):
            handler = FakeHandler(headers={'Content-Length': bad, 'Content-Type': 'application/json'})
            research_http.post(handler)
            self.assertEqual(handler.status, 400)


class ServerRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:%d' % cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); cls.thread.join()

    def request(self, path, method='GET', data=None):
        req = urllib.request.Request(self.base + path, method=method, data=data,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_collection_route_exists(self):
        status, body = self.request('/api/collection?id=bad')
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)['error'], 'Collection not found')
        status, _ = self.request('/api/collection?id=bad', 'POST', b'{}')
        self.assertEqual(status, 404)

    def test_retired_routes(self):
        self.assertEqual(self.request('/api/decide', 'POST', b'{}')[0], 410)
        self.assertEqual(self.request('/api/v/abc')[0], 410)
        self.assertEqual(self.request('/api/search', 'POST', b'{"query":"x"}')[0], 404)
        self.assertEqual(self.request('/api/playbooks')[0], 404)

    def test_head_uses_static_allowlist(self):
        status, _ = self.request('/server.py', 'HEAD')
        index_status, _ = self.request('/', 'HEAD')
        self.assertEqual(status, 200)  # falls back to the app shell, same as GET
        req = urllib.request.Request(self.base + '/server.py', method='HEAD')
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertIn('html', r.headers.get('Content-Type', ''))
        self.assertEqual(index_status, 200)
        status, body = self.request('/server.py')
        self.assertNotIn(b'ThreadingHTTPServer', body)

    def test_deleted_api_files(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ('search.py', 'playbooks.py', 'decide.py'):
            self.assertFalse(os.path.exists(os.path.join(root, 'api', name)))


class StoreTests(unittest.TestCase):
    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown
    reserve = baseline.ResearchTests.reserve

    def test_save_only_overwrites_pending_or_streaming(self):
        run, _ = self.reserve()
        db.save('alice', run['id'], status='complete', answer='Final')
        db.save('alice', run['id'], status='failed', answer='Late overwrite', error='x')
        row = db.get_run('alice', run['id'])
        self.assertEqual((row['status'], row['answer']), ('complete', 'Final'))
        other, _ = self.reserve()
        db.save('alice', other['id'], status='streaming', answer='partial')
        db.save('alice', other['id'], status='complete', answer='done')
        self.assertEqual(db.get_run('alice', other['id'])['status'], 'complete')

    def test_stale_runs_do_not_block_deletes(self):
        note = workspace.add_note('alice', 'Budget', 'The budget is 500.')
        run, _ = self.reserve()
        with self.assertRaises(ValueError):
            workspace.delete_note('alice', note['id'])
        old = int(time.time()) - db.STALE_SECONDS - 5
        with db.connection() as (conn, marker):
            db.execute(conn, marker, 'UPDATE research_runs SET updated=? WHERE id=?', (old, run['id']))
        self.assertTrue(workspace.delete_note('alice', note['id']))
        self.assertTrue(workspace.delete_workspace('alice'))

    def test_stale_run_does_not_block_claim(self):
        run, _ = self.reserve('anon')
        with db.connection() as (conn, marker):
            db.execute(conn, marker, 'UPDATE research_runs SET updated=? WHERE id=?', (int(time.time()) - db.STALE_SECONDS - 5, run['id']))
        with db.connection() as (conn, marker):
            db.execute(conn, marker, 'INSERT INTO zearch_accounts(id,email,created) VALUES(?,?,?)', ('a' * 32, 'a@example.com', 1))
        self.assertTrue(workspace.claim_workspace('anon', 'a' * 32))

    def test_charge_bucket_caps(self):
        db.charge_bucket('ip:test', 2)
        db.charge_bucket('ip:test', 2)
        with self.assertRaises(db.LimitReached):
            db.charge_bucket('ip:test', 2)

    def test_per_ip_bucket_limits_cookieless_clients(self):
        headers = {'x-vercel-forwarded-for': '203.0.113.9, 10.0.0.1'}
        with patch.dict(os.environ, {'ZEARCH_DAILY_IP_RUNS': '2'}):
            research_http.charge_ip(headers); research_http.charge_ip(headers)
            with self.assertRaises(db.LimitReached):
                research_http.charge_ip(headers)
            research_http.charge_ip({'x-real-ip': '198.51.100.4'})  # other address unaffected
            research_http.charge_ip({})  # unknown address is not throttled

    def test_postgres_options_do_not_break_sqlite(self):
        with db.connection() as (conn, _):
            self.assertIsInstance(conn, sqlite3.Connection)

    def test_malformed_limits_fall_back(self):
        with patch.dict(os.environ, {'ZEARCH_DAILY_SESSION_RUNS': 'ten'}):
            self.assertEqual(workspace.allowance('alice')['daily_limit'], 10)
        with patch.dict(os.environ, {'ZEARCH_DAILY_SESSION_RUNS': 'ten'}):
            handler = FakeHandler('/api/workspace', {'Cookie': research_http.identity({}, True)[1].split(';', 1)[0]})
            import workspace_http
            workspace_http.handle(handler)
            self.assertEqual(handler.status, 200)


class AccountTests(unittest.TestCase):
    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown

    def auth_env(self):
        return patch.dict(os.environ, {'ZEARCH_EMAIL_AUTH_ENABLED': '1', 'ZEARCH_MAIL_HOST': 'smtp.example.com',
            'ZEARCH_MAIL_USER': 'u', 'ZEARCH_MAIL_PASSWORD': 'p', 'ZEARCH_MAIL_FROM': 'a@example.com'})

    def test_disabled_get_reports_enabled_false(self):
        with patch.dict(os.environ, {'ZEARCH_SESSION_SECRET': ''}):
            handler = FakeHandler('/api/account')
            account_http.handle(handler)
            self.assertEqual(handler.status, 200)
            self.assertFalse(handler.json()['enabled'])

    def test_any_unexpired_code_verifies_after_resend(self):
        sent = []
        with self.auth_env(), patch.object(accounts, 'send_code', lambda email, code: sent.append(code)):
            accounts.request_code('user@example.com')
            accounts.request_code('user@example.com')
            self.assertEqual(len(sent), 2)
            token, account = accounts.verify('user@example.com', sent[0])  # the older code still works
            self.assertEqual(account['email'], 'user@example.com')
            with self.assertRaises(ValueError):
                accounts.verify('user@example.com', sent[1])  # consumed by the successful sign-in

    def test_wrong_codes_are_bounded(self):
        sent = []
        with self.auth_env(), patch.object(accounts, 'send_code', lambda email, code: sent.append(code)):
            accounts.request_code('user@example.com')
            wrong = '00000000' if sent[0] != '00000000' else '11111111'
            for _ in range(5):
                with self.assertRaises(ValueError):
                    accounts.verify('user@example.com', wrong)
            with self.assertRaises(ValueError):
                accounts.verify('user@example.com', sent[0])

    def test_per_ip_signin_throttle(self):
        with self.auth_env(), patch.dict(os.environ, {'ZEARCH_SIGNIN_IP_DAILY': '2'}), \
                patch.object(accounts, 'send_code', lambda email, code: None):
            accounts.request_code('a@example.com', '203.0.113.5')
            accounts.request_code('b@example.com', '203.0.113.5')
            with self.assertRaises(ValueError):
                accounts.request_code('c@example.com', '203.0.113.5')
            accounts.request_code('c@example.com', '203.0.113.6')


class RevalidationTests(unittest.TestCase):
    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown

    def test_enqueue_rearms_canceled_and_work_survives_errors(self):
        import tempfile
        from pathlib import Path
        url = 'https://example.org/article'
        policy = Path(self.temp.name) / 'policy.json'
        policy.write_text(json.dumps({'version': 1, 'domains': {'example.org': {
            'cache_extracted_content': True, 'basis': 'fixture', 'reviewed_at': '2026-09-28', 'ttl_seconds': 3600}}}))
        env = {'ZEARCH_REVALIDATION_ENABLED': '1', 'ZEARCH_SCRAPE_USD_PER_CALL': '.01', 'TAVILY_API_KEY': 't',
               'ZEARCH_DAILY_REVALIDATION_CALLS': '3', 'ZEARCH_DAILY_REVALIDATION_USD': '.03'}
        with patch.dict(os.environ, env), patch.object(source_store, 'POLICY', policy):
            key = worker.enqueue(url, now=100)
            with db.connection() as (conn, marker):
                db.execute(conn, marker, "UPDATE source_revalidation_jobs SET state='canceled' WHERE url=?", (key,))
            worker.enqueue(url, now=200)
            with db.connection() as (conn, marker):
                row = db.execute(conn, marker, 'SELECT state,next_run FROM source_revalidation_jobs WHERE url=?', (key,)).fetchone()
            self.assertEqual((row['state'], row['next_run']), ('pending', 200))
            import enrichment, research
            with patch.object(enrichment, 'extract', side_effect=research.Unavailable('down')), \
                    patch.object(worker, 'claim', return_value=worker.claim(now=int(time.time()) + 10)) as claim:
                self.assertTrue(worker.work_once())
            with db.connection() as (conn, marker):
                row = db.execute(conn, marker, 'SELECT state,last_error FROM source_revalidation_jobs WHERE url=?', (key,)).fetchone()
            self.assertEqual((row['state'], row['last_error']), ('pending', 'Unavailable'))


def docx(xml):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', xml)
    return base64.b64encode(out.getvalue()).decode()


class DocumentIngestTests(unittest.TestCase):
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def test_plain_docx_ok(self):
        xml = f'<w:document {self.W}><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>'
        self.assertEqual(document_ingest.extract('a.docx', docx(xml))[0], 'Hello')

    def test_doctype_and_entity_rejected(self):
        for prefix in ('<!DOCTYPE d [<!ENTITY x "boom">]>', '<!doctype d>', '<! ENTITY x "y">'):
            xml = f'<?xml version="1.0"?>{prefix}<w:document {self.W}><w:body><w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>'
            with self.assertRaises(ValueError, msg=prefix):
                document_ingest.extract('a.docx', docx(xml))


class ArtifactTests(unittest.TestCase):
    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown
    reserve = baseline.ResearchTests.reserve

    def completed(self, sources):
        cookie = research_http.identity({}, True)[1].split(';', 1)[0]
        owner, _ = research_http.identity({'Cookie': cookie})
        run, _ = self.reserve(owner)
        db.save(owner, run['id'], status='complete', answer='Answer [1]', sources=sources)
        return cookie, run['id']

    def test_sources_without_n_do_not_crash_text_export(self):
        cookie, rid = self.completed([{'url': 'https://example.org/x', 'title': 'Untitled'}])
        handler = FakeHandler('/api/artifact?id=%s&format=txt' % rid, {'Cookie': cookie})
        artifact.handle(handler)
        self.assertEqual(handler.status, 200)
        self.assertIn(b'[1] Untitled', handler.wfile.getvalue())

    def test_missing_renderer_has_distinct_message(self):
        cookie, rid = self.completed([])
        with patch.object(artifact, 'brief_pdf', side_effect=ImportError('reportlab')):
            handler = FakeHandler('/api/artifact?id=%s&format=pdf' % rid, {'Cookie': cookie})
            artifact.handle(handler)
        self.assertEqual(handler.status, 503)
        self.assertIn('PDF export is not available', handler.json()['error'])

    def test_oversize_brief_is_413(self):
        cookie, rid = self.completed([])
        with patch.object(artifact, 'brief_pdf', side_effect=artifact.TooLarge('big')):
            handler = FakeHandler('/api/artifact?id=%s&format=pdf' % rid, {'Cookie': cookie})
            artifact.handle(handler)
        self.assertEqual(handler.status, 413)


class DeploymentConfigTests(unittest.TestCase):
    def test_vercel_security_headers(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config = json.load(open(os.path.join(root, 'vercel.json')))
        keys = {h['key'] for rule in config['headers'] for h in rule['headers']}
        for expected in ('Content-Security-Policy', 'X-Frame-Options', 'Referrer-Policy', 'Strict-Transport-Security'):
            self.assertIn(expected, keys)


if __name__ == '__main__':
    unittest.main()
