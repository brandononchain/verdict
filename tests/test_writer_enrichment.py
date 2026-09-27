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

    def test_writer_rejects_unselected_reference(self):
        with patch.dict(os.environ,{'ZEARCH_WRITER_MODEL':'writer','OPENAI_API_KEY':'key'}), \
             patch.object(writer,'open_provider',return_value=Response({'status':'completed',
                 'output':[{'type':'message','content':[{'type':'output_text','text':'Claim. [2]'}]}],
                 'usage':{'input_tokens':1,'output_tokens':1}})):
            with self.assertRaises(writer.WriterError):writer.compose('How?',self.sources,[1])

    def test_jev_rejects_unsupported_paragraph(self):
        with patch.object(jev,'call',return_value={'model':'jev','answers':{
             'supported_0':{'noul':.2}},'usage':{'input_tokens':12}}):
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
