import json
import os
import unittest
from unittest.mock import patch

import enrichment
import jev_research as jev
import writer


class Response:
    def __init__(self, data): self.data = json.dumps(data).encode()
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_): return self.data


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{'n':1,'url':'https://example.org/a','title':'A',
                         'text':'Solar panels convert sunlight into electricity. ' * 8}]

    def test_writer_accepts_only_selected_citations_and_stateless_request(self):
        captured = {}
        def respond(url, payload, key, timeout):
            captured.update(payload)
            return Response({'status':'completed','model':'writer',
                'output':[{'type':'message','content':[{'type':'output_text',
                'text':'Solar panels convert sunlight into electricity. [1]'}]}],
                'usage':{'input_tokens':100,'output_tokens':20}})
        with patch.dict(os.environ,{'ZEARCH_WRITER_MODEL':'writer','OPENAI_API_KEY':'key'}), \
             patch.object(writer,'open_provider',side_effect=respond):
            answer,usage=writer.compose('How?',self.sources,[1])
        self.assertTrue(captured['store'] is False)
        self.assertIn('[1]',answer)
        self.assertEqual(usage['output_tokens'],20)

    def test_writer_distinguishes_capture_time_from_fact_time(self):
        captured = {}
        def respond(url, payload, key, timeout):
            captured.update(payload)
            return Response({'status':'completed', 'output':[{'type':'message','content':[
                {'type':'output_text','text':'Python.org lists a stable version. [1]'}]}],
                'usage':{'input_tokens':5,'output_tokens':8}})
        source = dict(self.sources[0], retrieved_at=1790553600)
        with patch.dict(os.environ,{'ZEARCH_WRITER_MODEL':'writer','OPENAI_API_KEY':'key'}), \
             patch.object(writer,'open_provider',side_effect=respond):
            writer.compose('latest version?', [source], [1])
        self.assertIn('captured_at_utc', json.loads(captured['input'])['evidence'][0])
        self.assertIn('not when a quoted fact was measured', captured['instructions'])

    def test_writer_receives_same_bounded_tail_span_as_verifier(self):
        captured = {}
        def respond(url, payload, key, timeout):
            captured.update(payload)
            return Response({'status':'completed', 'output':[{'type':'message','content':[
                {'type':'output_text','text':'The answer is in the later passage. [1]'}]}],
                'usage':{'input_tokens':10,'output_tokens':9}})
        text = 'Navigation. ' * 320 + 'The answer is in the later passage.'
        at = text.index('The answer is in the later passage.')
        source = dict(self.sources[0], text=text, evidence_span=[at, len(text)], source_version_id='a'*64)
        with patch.dict(os.environ, {'ZEARCH_WRITER_MODEL':'writer','OPENAI_API_KEY':'key'}), \
             patch.object(writer, 'open_provider', side_effect=respond):
            writer.compose('What is the answer?', [source], [1])
        evidence = json.loads(captured['input'])['evidence'][0]
        self.assertIn('The answer is in the later passage.', evidence['text'])
        self.assertEqual(evidence['capture_version'], 'a'*64)
        self.assertLessEqual(len(evidence['text']), 3000)

    def test_writer_rejects_unselected_reference(self):
        with patch.dict(os.environ,{'ZEARCH_WRITER_MODEL':'writer','OPENAI_API_KEY':'key'}), \
             patch.object(writer,'open_provider',return_value=Response({'status':'completed',
                 'output':[{'type':'message','content':[{'type':'output_text','text':'Claim. [2]'}]}],
                 'usage':{'input_tokens':1,'output_tokens':1}})):
            with self.assertRaises(writer.WriterError):writer.compose('How?',self.sources,[1])

    def test_jev_rejects_unsupported_paragraph(self):
        with patch.object(jev,'call',return_value={'model':'jev','answers':{
             'supported_0':{'noul':.2},'attributed_0':{'noul':.9}},'usage':{'input_tokens':12}}):
            approved,check,usage=jev.verify('How?', 'Unsupported assertion. [1]', self.sources,[1])
        self.assertFalse(approved)
        self.assertEqual(usage['input_tokens'],12)

    def test_enrichment_replaces_page_but_preserves_original_on_failure(self):
        with patch.dict(os.environ,{'ZEARCH_ENRICHMENT_ENABLED':'1','CONTEXT_DEV_API_KEY':'key'}), \
             patch.object(enrichment,'open_provider',return_value=Response({
                 'markdown':{'data':'Rendered article. ' * 10},
                 'metadata':{'title':'Rendered'}})):
            rows,report=enrichment.enrich([dict(self.sources[0])])
        self.assertEqual(rows[0]['content_type'],'extracted_page')
        self.assertEqual(rows[0]['title'],'Rendered')
        self.assertEqual(report['scrape_calls'],1)
        with patch.dict(os.environ,{'ZEARCH_ENRICHMENT_ENABLED':'1','CONTEXT_DEV_API_KEY':'key'}), \
             patch.object(enrichment,'open_provider',side_effect=OSError('offline')):
            rows,report=enrichment.enrich([dict(self.sources[0])])
        self.assertEqual(rows[0]['text'],self.sources[0]['text'])
        self.assertEqual(report['enriched_pages'],0)


if __name__ == '__main__': unittest.main()
