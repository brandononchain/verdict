import json
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

import answer_contract
import jev_research as jev
import research as r
import research_store as db
import retrieval
import writer


class Response:
    def __init__(self, data): self.data = json.dumps(data).encode()
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_): return self.data


SOURCES = [{'n': 1, 'url': 'https://example.org/a', 'title': 'A', 'text': 'Alpha is fast. ' * 10, 'domain': 'example.org'}]


def capture(mode, revision=False, context=None):
    seen = {}
    def respond(url, payload, key, timeout):
        seen.update(payload)
        return Response({'status': 'completed', 'model': 'w', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': 'Alpha is fast. [1]'}]}], 'usage': {'input_tokens': 1, 'output_tokens': 1}})
    with patch.dict(os.environ, {'ZEARCH_WRITER_MODEL': 'w', 'OPENAI_API_KEY': 'k'}), \
         patch.object(writer, 'open_provider', side_effect=respond):
        writer.compose('Q?', SOURCES, [1], mode, revision, context)
    return seen


class PromptShapeTests(unittest.TestCase):
    def test_mode_specific_structure_instructions(self):
        self.assertIn('## Key findings', capture('deep')['instructions'])
        self.assertIn('## Limits', capture('deep')['instructions'])
        self.assertNotIn('## Key findings', capture('standard')['instructions'])
        compare = capture('compare')['instructions']
        self.assertIn('No clear winner', compare)
        self.assertIn('table', compare)
        for mode in ('scrape', 'crawl'):
            text = capture(mode)['instructions']
            self.assertIn('## Key facts', text)
            self.assertIn('## Notable sections', text)
        for mode in ('standard', 'deep', 'compare', 'scrape'):
            self.assertIn('Place [source ID] beside each factual sentence', capture(mode)['instructions'])

    def test_refinement_prompt_and_body(self):
        seen = capture('standard', context={'refine': 'shorten', 'previous': 'Long earlier answer.', 'standalone': 'Topic'})
        self.assertIn('shorter', seen['instructions'])
        body = json.loads(seen['input'])
        self.assertEqual(body['requested_change'], 'shorten')
        self.assertEqual(body['previous_answer'], 'Long earlier answer.')


class ContractShapeTests(unittest.TestCase):
    def test_new_shapes_are_accepted(self):
        deep = ('Alpha beats Beta on speed. [1]\n\n## Key findings\n\n- Alpha is fast. [1]\n- Beta is slow. [2]\n\n'
                '## Where sources differ\n\nSource 1 says X [1] while source 2 says Y [2].\n\n## Limits\n\nNo data on cost. [1]')
        self.assertEqual(len(answer_contract.units(deep, 6)), 4)
        compare = ('No clear winner: Alpha suits speed, Beta suits cost. [1] [2]\n\n'
                   '| Aspect | Alpha | Beta |\n|---|---|---|\n| Speed | Fast [1] | Slow [2] |\n| Cost | High [1] | Low [2] |\n\n'
                   'The main difference is speed versus cost. [1]')
        self.assertEqual(len(answer_contract.units(compare, 4)), 3)
        scrape = ('This page is the Alpha docs home. [1]\n\n## Key facts\n\n- Alpha is fast. [1]\n- It is free. [1]\n\n'
                  '## Notable sections\n\nIt also covers install and pricing. [1]')
        self.assertEqual(len(answer_contract.units(scrape, 4)), 3)
        with self.assertRaises(ValueError):
            answer_contract.units('Alpha is fast. [1]\n\n## Limits', 6)


class RewriteTests(unittest.TestCase):
    def test_refinement_intent(self):
        cases = {'shorter': 'shorten', 'make it shorter please': 'shorten', 'tl;dr': 'shorten', 'summarize that': 'shorten',
                 'explain more': 'expand', 'go deeper': 'expand', 'as a table': 'reformat', 'put it in bullet points': 'reformat',
                 'translate to Spanish': 'translate', 'in French': 'translate'}
        for text, intent in cases.items():
            self.assertEqual(retrieval.refinement_intent(text), intent, text)
        for text in ('What is the shortest path in a graph?', 'How do heat pumps work?', 'and the cost?', ''):
            self.assertIsNone(retrieval.refinement_intent(text), text)

    def test_standalone_variants(self):
        history = [{'role': 'user', 'content': 'React vs Vue for a small app'},
                   {'role': 'assistant', 'content': 'React has a larger ecosystem. [1]'}]
        for query in ('compare those', 'which one is better?', 'why?', 'and for large apps?'):
            out = retrieval.standalone_question(query, history, ['Title'])
            self.assertTrue(out.startswith(query))
            self.assertLessEqual(len(out), 350)
        self.assertIn('comparison of React and Vue', retrieval.standalone_question('compare those', history))
        self.assertIn('React has a larger ecosystem', retrieval.standalone_question('why?', history))
        self.assertNotIn('[1]', retrieval.standalone_question('why?', history))
        self.assertEqual(retrieval.standalone_question('Explain how photosynthesis converts light into chemical energy in plants', history),
                         'Explain how photosynthesis converts light into chemical energy in plants')


class FollowupTests(unittest.TestCase):
    def check(self, items):
        self.assertLessEqual(len(items), 3)
        self.assertEqual(len(set(items)), len(items))
        for item in items:
            self.assertIsInstance(item, str)
            self.assertTrue(0 < len(item) <= 90)
            self.assertNotRegex(item, r'https?://|[\n<>\[\]]')

    def test_answered_and_compare(self):
        sources = [{'n': 1, 'title': 'T', 'domain': 'example.org'}]
        out = retrieval.suggest_followups('How do heat pumps work?', 'standard', {}, sources)
        self.check(out)
        self.assertIn('Give a shorter version', out)
        out = retrieval.suggest_followups('React vs Vue', 'compare', {}, sources)
        self.check(out)
        self.assertTrue(out[0].startswith('Which is better'))
        self.check(retrieval.suggest_followups('q', 'deep', {}, [{'domain': 'x' * 200, 'title': 't'}], ['a' * 200, 'cost']))

    def test_abstained_market_redacted(self):
        out = retrieval.suggest_followups('q', 'standard', {}, [{'title': 'Heat *pump* <b>guide</b> https://x.y'}], ['cost'], 'abstained')
        self.check(out)
        self.assertEqual(out[0], 'Search with Deep research')
        self.assertTrue(any(x.startswith('Narrow to ') for x in out))
        self.assertNotIn('Search with Deep research', retrieval.suggest_followups('q', 'deep', {}, [], (), 'abstained'))
        self.check(retrieval.suggest_followups('BTC price', 'standard', outcome='market'))
        self.assertEqual(len(retrieval.suggest_followups('q', outcome='redacted')), 1)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'ZEARCH_DB_PATH': self.temp.name + '/t.db', 'ZEARCH_SESSION_SECRET': 's' * 40,
            'ZEARCH_JEV_INPUT_USD_PER_MILLION': '1', 'ZEARCH_SEARCH_USD_PER_CALL': '.01',
            'ZEARCH_WRITER_INPUT_USD_PER_MILLION': '1', 'ZEARCH_WRITER_OUTPUT_USD_PER_MILLION': '2'}, clear=True)
        self.env.start(); db.migrate()
        self.limits = dict(global_calls=100, user_calls=10, global_budget=10000000, user_budget=1000000)
    def tearDown(self): self.env.stop(); self.temp.cleanup()
    def reserve(self, query, parent=None):
        return db.reserve('alice', uuid.uuid4().hex, uuid.uuid4().hex, query, parent, 'test', 100, self.limits)[0]
    def pipeline(self):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(jev, 'call', return_value={'model': 'j', 'answers': {
            'best_passage': {'type': 'choice', 'choice': '1', 'confidence': .9, 'probabilities': {'1': .9, 'none': .1}},
            'sufficient': {'type': 'noul', 'noul': .95}, 'conflict': {'type': 'noul', 'noul': .1}},
            'usage': {'input_tokens': 10, 'output_tokens': 0}}))
        stack.enter_context(patch.object(jev, 'verify', return_value=(True, {'probabilities': [.97]}, {'input_tokens': 5})))
        return stack

    def test_refinement_skips_search_and_still_verifies(self):
        parent = self.reserve('How do heat pumps work?')
        db.save('alice', parent['id'], status='complete', answer='Heat pumps move heat using a refrigerant. [1]',
                sources=[{'n': 1, 'url': 'https://energy.gov/hp', 'title': 'Energy', 'domain': 'energy.gov',
                          'text': 'Heat pumps move heat using a refrigerant.'}], usage={}, estimated_cost=1)
        child = self.reserve('shorter', parent=parent['id'])
        ok = ('Heat pumps move heat. [1]', {'model': 'w', 'input_tokens': 1, 'output_tokens': 1})
        with self.pipeline(), \
             patch.object(r, 'search', side_effect=AssertionError('no search')), \
             patch('enrichment.enrich', side_effect=AssertionError('no enrichment')), \
             patch.object(writer, 'compose', return_value=ok) as compose:
            events = list(r.run('alice', child, db.context('alice', parent['id'])))
        self.assertEqual(events[-1]['type'], 'complete')
        usage = events[-1]['run']['usage']
        self.assertEqual(usage['refinement'], 'shorten')
        self.assertEqual(usage['search_calls'], 0)
        self.assertEqual(usage['answer_format'], 'jev_verified_prose')
        self.assertEqual(compose.call_args.args[5]['refine'], 'shorten')
        self.assertIn('heat pumps', usage['standalone_question'].lower())
        self.assertIn('Reusing the earlier sources', [e['text'] for e in events if e['type'] == 'status'])
        self.assertIn('followups', usage)

    def test_status_lines_and_followups_on_completed_run(self):
        run = self.reserve('React vs Vue')
        found = [{'n': 1, 'url': 'https://example.com', 'title': 'Source', 'text': 'Evidence answers the Question.', 'domain': 'example.com'}]
        ok = ('Evidence answers the Question. [1]', {'model': 'w', 'input_tokens': 1, 'output_tokens': 1})
        with self.pipeline(), patch.object(r, 'search', return_value=found), patch.object(writer, 'compose', return_value=ok):
            events = list(r.run('alice', run, []))
        statuses = [e['text'] for e in events if e['type'] == 'status']
        self.assertEqual(statuses[0], 'Searching the web') if len(retrieval.plan('React vs Vue', [], 'standard')) == 1 else None
        self.assertIn('Reading 1 source', statuses)
        self.assertIn('Checking each claim against its source', statuses)
        followups = events[-1]['run']['usage']['followups']
        self.assertTrue(1 <= len(followups) <= 3 and all(len(x) <= 90 for x in followups))


if __name__ == '__main__':
    unittest.main()
