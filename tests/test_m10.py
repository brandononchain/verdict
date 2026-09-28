import base64
import io
import json
import os
import unittest
import zipfile
from unittest.mock import patch

import test_research as baseline
import account_store as accounts
import document_ingest
import research_http
import account_http
import workspace_http
import research
import jev_research as jev
import writer
import uuid
import research_store as db
import workspace_store as workspace


class M10Tests(unittest.TestCase):
    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown
    reserve = baseline.ResearchTests.reserve

    def auth_env(self):
        return patch.dict(os.environ, {'ZEARCH_EMAIL_AUTH_ENABLED':'1', 'ZEARCH_MAIL_HOST':'smtp.example.com',
            'ZEARCH_MAIL_USER':'user', 'ZEARCH_MAIL_PASSWORD':'password', 'ZEARCH_MAIL_FROM':'Zearch <sign-in@example.com>'})

    def test_email_code_one_time_and_cross_device_session(self):
        sent = []
        with self.auth_env(), patch.object(accounts, 'send_code', side_effect=lambda email,code: sent.append((email,code))):
            accounts.request_code(' Owner@Example.com ')
            self.assertEqual(sent[0][0], 'owner@example.com')
            for _ in range(4):
                with self.assertRaises(ValueError): accounts.verify('owner@example.com', '00000000' if sent[0][1] != '00000000' else '11111111')
            token, account = accounts.verify('owner@example.com', sent[0][1])
            self.assertEqual(accounts.session({'Cookie':'zearch_account='+token})['id'],account['id'])
            self.assertEqual(research_http.identity({'Cookie':'zearch_account='+token})[0], 'acct:'+account['id'])
            with self.assertRaises(ValueError): accounts.verify('owner@example.com',sent[0][1])
            accounts.revoke({'Cookie':'zearch_account='+token})
            self.assertIsNone(accounts.session({'Cookie':'zearch_account='+token}))

    def test_fifth_failed_attempt_locks_code(self):
        sent=[]
        with self.auth_env(), patch.object(accounts,'send_code',side_effect=lambda email,code:sent.append(code)):
            accounts.request_code('owner@example.com')
            bad='00000000' if sent[0]!='00000000' else '11111111'
            for _ in range(5):
                with self.assertRaises(ValueError): accounts.verify('owner@example.com',bad)
            with self.assertRaises(ValueError): accounts.verify('owner@example.com',sent[0])

    def test_claim_moves_only_current_guest_and_preserves_spend(self):
        with db.connection() as (conn, marker):
            db.execute(conn,marker,'INSERT INTO zearch_accounts(id,email,created) VALUES(?,?,?)',('a'*32,'a@example.com',1))
        run,_=self.reserve('guest')
        db.save('guest',run['id'],status='complete',answer='Private [1]')
        workspace.add_note('guest','Memo','Secret for A')
        workspace.add_note('other','Memo','Secret for B')
        self.assertTrue(workspace.claim_workspace('guest','a'*32))
        self.assertFalse(workspace.claim_workspace('guest','a'*32))
        self.assertIsNone(db.get_run('guest',run['id']))
        self.assertEqual(db.get_run('acct:'+'a'*32,run['id'])['answer'],'Private [1]')
        self.assertEqual(workspace.allowance('acct:'+'a'*32)['used'],1)
        self.assertEqual(workspace.notes('acct:'+'a'*32,True)[0]['body'],'Secret for A')
        self.assertEqual(workspace.notes('other',True)[0]['body'],'Secret for B')
        with self.assertRaises(ValueError): workspace.claim_workspace('guest','b'*32)

    def test_document_import_acl_export_and_redaction(self):
        encoded=base64.b64encode(b'Budget 2026 is 500 credits.').decode()
        doc=workspace.add_document('alice','budget.md',encoded)
        self.assertEqual(workspace.documents('bob'),[])
        self.assertEqual(workspace.knowledge('bob','budget'),[])
        self.assertEqual(workspace.knowledge('alice','budget')[0]['document_id'],doc['id'])
        self.assertEqual(workspace.export_page('alice')['documents'][0]['text'],'Budget 2026 is 500 credits.')
        run,_=self.reserve('alice')
        db.save('alice',run['id'],status='complete',answer='Budget 500. [1]',sources=[
            {'n':1,'document_id':doc['id'],'note_id':doc['id'],'text':'Budget 2026 is 500 credits.'}])
        self.assertFalse(workspace.delete_document('bob',doc['id']))
        self.assertTrue(workspace.delete_document('alice',doc['id']))
        self.assertEqual(db.get_run('alice',run['id'])['status'],'redacted')
        self.assertEqual(db.get_run('alice',run['id'])['sources'],[])
        self.assertEqual(workspace.export_page('alice')['documents'],[])

    def test_private_document_never_enters_public_query(self):
        workspace.add_document('alice','plan.txt',base64.b64encode(b'Confidential plan budget is 500 credits.').decode())
        with patch.object(research,'ready',return_value=True), patch.object(research,'search',return_value=[]) as search, \
             patch.object(jev,'call',return_value={'answers':{'best_passage':{'choice':'1','probabilities':{'1':.9}},
                'sufficient':{'noul':.9},'conflict':{'noul':.1}},'usage':{'input_tokens':10}}) as judge, \
             patch.object(writer,'compose',side_effect=writer.WriterError('offline')):
            run,_,history=research.prepare('alice',{'query':'budget','request_id':uuid.uuid4().hex,'use_knowledge':True})
            events=list(research.run('alice',run,history))
            self.assertEqual(events[-1]['type'],'complete')
            self.assertNotIn('Confidential',str(search.call_args))
            self.assertIn('Confidential',str(judge.call_args))
            self.assertEqual(events[-1]['run']['sources'][0]['content_type'],'document')

    def test_docx_text_and_reject_bad_archive(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as archive:
            archive.writestr('[Content_Types].xml','<Types/>')
            archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello DOCX</w:t></w:r></w:p></w:body></w:document>')
        text,_=document_ingest.extract('report.docx',base64.b64encode(raw.getvalue()).decode())
        self.assertEqual(text,'Hello DOCX')
        with self.assertRaises(ValueError): document_ingest.extract('report.docx',base64.b64encode(b'not zip').decode())

    def test_note_deletion_redacts_saved_answer(self):
        note=workspace.add_note('alice','Private','Secret')
        run,_=self.reserve('alice')
        db.save('alice',run['id'],status='complete',answer='Secret [1]',sources=[{'n':1,'note_id':note['id'],'text':'Secret'}])
        child,_=self.reserve('alice',parent=run['id'])
        db.save('alice',child['id'],status='complete',answer='Reused secret [1]',sources=[{'n':1,'url':'https://example.com','text':'Public'}])
        self.assertTrue(workspace.delete_note('alice',note['id']))
        self.assertEqual(db.get_run('alice',run['id'])['status'],'redacted')
        self.assertEqual(db.get_run('alice',child['id'])['status'],'redacted')

    def test_parent_deletion_redacts_derived_followup(self):
        parent,_=self.reserve('alice')
        db.save('alice',parent['id'],status='complete',answer='Private fact [1]')
        child,_=self.reserve('alice',parent=parent['id'])
        db.save('alice',child['id'],status='complete',answer='Derived fact [1]')
        self.assertTrue(workspace.delete_run('alice',parent['id']))
        self.assertEqual(db.get_run('alice',child['id'])['status'],'redacted')

    def test_http_two_account_isolation_claim_export_and_delete(self):
        class Handler:
            def __init__(self, path, headers, data=None):
                self.path=path; self.headers=headers; self.rfile=io.BytesIO(json.dumps(data).encode() if data else b'')
                self.wfile=io.BytesIO(); self.headers=dict(headers)
                if data: self.headers.update({'Content-Length':str(len(json.dumps(data).encode())), 'Content-Type':'application/json'})
                self.headers.setdefault('Host','zearch.test')
                self.status=None; self.response_headers={}
            def send_response(self, status): self.status=status
            def send_header(self, key, value): self.response_headers[key]=value
            def end_headers(self): pass
            def result(self): return json.loads(self.wfile.getvalue())
        def call(module, path, headers=None, data=None):
            handler=Handler(path,headers or {},data)
            module.handle(handler,mutate=data is not None)
            return handler
        guest_cookie=research_http.identity({},True)[1].split(';',1)[0]
        sent={}
        with self.auth_env(), patch.object(accounts,'send_code',side_effect=lambda email,code:sent.__setitem__(email,code)):
            guest=call(workspace_http,'/api/workspace',{'Cookie':guest_cookie},{'action':'add_document',
                'filename':'private.txt','content_base64':base64.b64encode(b'Alice private facts').decode()})
            self.assertEqual(guest.status,200)
            guest_owner,_=research_http.anonymous_identity({'Cookie':guest_cookie})
            run,_=self.reserve(guest_owner)
            db.save(guest_owner,run['id'],status='complete',answer='Alice answer [1]')
            def sign_in(email):
                requested=call(account_http,'/api/account',{}, {'action':'request_code','email':email})
                self.assertEqual(requested.status,200)
                verified=call(account_http,'/api/account',{}, {'action':'verify_code','email':email,'code':sent[email]})
                self.assertEqual(verified.status,200)
                return verified.response_headers['Set-Cookie'].split(';',1)[0]
            alice=sign_in('alice@example.com')
            self.assertEqual(call(account_http,'/api/account',{'Cookie':guest_cookie+'; '+alice},
                {'action':'claim_workspace'}).status,200)
            bob=sign_in('bob@example.com')
            self.assertEqual(call(workspace_http,'/api/workspace?export=1',{'Cookie':bob}).result()['documents'],[])
            self.assertEqual(research_http.identity({'Cookie':bob})[0].startswith('acct:'),True)
            viewer=Handler('/api/research?id='+run['id'],{'Cookie':bob})
            research_http.get(viewer)
            self.assertEqual(viewer.status,404)
            alice_export=call(workspace_http,'/api/workspace?export=1',{'Cookie':alice}).result()
            self.assertEqual(alice_export['documents'][0]['text'],'Alice private facts')
            self.assertEqual(alice_export['runs'][0]['answer'],'Alice answer [1]')
            second_device=sign_in('alice@example.com')
            self.assertEqual(call(workspace_http,'/api/workspace?export=1',{'Cookie':second_device}).result()['runs'][0]['id'],run['id'])
            self.assertEqual(call(account_http,'/api/account',{'Cookie':alice},{'action':'delete_account'}).status,200)
            self.assertEqual(call(workspace_http,'/api/workspace?export=1',{'Cookie':alice}).result()['runs'],[])
            self.assertIsNone(call(account_http,'/api/account',{'Cookie':second_device}).result()['account'])
            self.assertEqual(call(account_http,'/api/account',{'Cookie':bob}).result()['account']['email'],'bob@example.com')
