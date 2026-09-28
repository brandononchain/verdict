import unittest
import json
import os
from unittest.mock import patch
import jev_research as jev

SOURCES = [
    {'n':1, 'title':'First source', 'domain':'example.com', 'url':'https://example.com',
     'text':'Solar panels turn sunlight into electricity. Other content not related.'},
    {'n':2, 'title':'Second source', 'domain':'source.org', 'url':'https://source.org',
     'text':'A second passage about photovoltaic solar panels.'},
]


def raw(choice='1', enough=.91, conflict=.02):
    return {'model':'jev-1.13', 'answers':{
        'best_passage':{'choice':choice, 'probabilities':{choice:.9}},
        'sufficient':{'noul':enough}, 'conflict':{'noul':conflict}},
        'usage':{'input_tokens':63, 'output_tokens':0}}


class JevResearchTests(unittest.TestCase):
    def test_only_typed_question_payload(self):
        state, questions, candidates = jev.state_and_questions('How do solar panels work?', SOURCES)
        self.assertEqual(set(questions), {'best_passage','sufficient','conflict','relevant_1','relevant_2'})
        self.assertEqual(questions['best_passage']['type'],'choice')
        self.assertIn('none', questions['best_passage']['criteria'])
        self.assertNotIn('messages',state)
        self.assertLessEqual(len(candidates),8)

    def test_provider_request_uses_native_jev_api(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args): return json.dumps(raw()).encode()
        class Opener:
            def open(self,request,timeout):
                self.request=request
                return Response()
        opener=Opener()
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'test-token','JEV_MODEL':'jev-latest'}), \
             patch('urllib.request.build_opener',return_value=opener):
            state,questions,_=jev.state_and_questions('solar',SOURCES)
            jev.call(state,questions)
        self.assertEqual(opener.request.full_url,'https://api.typesafe.ai/v1/systemone')
        payload=json.loads(opener.request.data)
        self.assertEqual(set(payload),{'model','state','questions'})
        self.assertEqual(payload['model'],'jev-latest')

    def test_extractive_answer(self):
        with patch.object(jev,'call',return_value=raw()):
            judgment, chosen, usage, candidates = jev.judge('How do solar panels work?',SOURCES)
        answer=jev.format_answer(judgment,chosen,candidates,SOURCES)
        self.assertEqual(judgment['gate'],'answer')
        self.assertIn('Solar panels turn sunlight into electricity. Other content not related. [1]',answer.replace('”',''))
        self.assertEqual(usage['input_tokens'],63)

    def test_abstains_without_evidence(self):
        with patch.object(jev,'call',return_value=raw(choice='none',enough=.1)):
            judgment, chosen, _, candidates=jev.judge('What is not in sources?',SOURCES)
        self.assertIsNone(chosen)
        self.assertEqual(judgment['gate'],'abstain')
        self.assertNotIn('Solar panels',jev.format_answer(judgment,chosen,candidates,SOURCES))

    def test_conflict_requires_review(self):
        with patch.object(jev,'call',return_value=raw(conflict=.8)):
            judgment,chosen,_,candidates=jev.judge('solar panels',SOURCES)
        self.assertEqual(judgment['gate'],'review')
        self.assertIn('may disagree',jev.format_answer(judgment,chosen,candidates,SOURCES))

    def test_invalid_choice_fails_closed(self):
        with patch.object(jev,'call',return_value=raw(choice='999')):
            with self.assertRaises(jev.JevError):jev.judge('solar panels',SOURCES)

    def test_invalid_probability_fails_closed(self):
        with patch.object(jev,'call',return_value=raw(enough=float('nan'))):
            with self.assertRaises(jev.JevError):jev.judge('solar panels',SOURCES)

    def test_passage_is_bounded_and_extracts(self):
        self.assertLessEqual(len(jev.passage('specific term', 'x '*2000)),450)
        self.assertEqual(jev.passage('solar panels','Other claim. Solar panels produce power.'),
                         'Solar panels produce power.')
        evidence = ('HTTP 429 means too many requests from the client. '
                    'The server is asking the client to slow down. '
                    'A Retry-After header may say how long to wait before another request.')
        self.assertEqual(jev.passage('What does HTTP 429 mean and how should a client respond?', evidence), evidence)

    def test_passage_offsets_resolve_in_original_capture(self):
        text = 'Repeated introduction.\nRepeated introduction.\nHTTP 429 asks clients to slow down.\nRetry-After gives a delay.'
        passage, start, end = jev.passage_span('HTTP 429 clients slow down', text)
        self.assertEqual(text[start:end].split(), passage.split())
        self.assertEqual(start, text.index('HTTP 429'))
        self.assertLessEqual(len(passage), 450)

    def test_verification_uses_only_each_paragraphs_citations(self):
        captured = {}
        def fake_call(state, questions):
            captured.update(state)
            return {'answers': {'supported_0': {'noul': .9}, 'supported_1': {'noul': .9}}}
        with patch.object(jev, 'call', side_effect=fake_call):
            approved, _, _ = jev.verify('solar panels', 'First claim. [1]\n\nSecond claim. [2]', SOURCES, [1, 2])
        self.assertTrue(approved)
        self.assertEqual([e['id'] for e in captured['checks'][0]['cited_evidence']], [1])
        self.assertEqual([e['id'] for e in captured['checks'][1]['cited_evidence']], [2])
        self.assertEqual(captured['checks'][0]['cited_evidence'][0]['captured_at_utc'], 'unknown')
        with self.assertRaises(jev.JevError):
            jev.verify('solar panels', 'Unsupported citation. [999]', SOURCES, [1, 2])
