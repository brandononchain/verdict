"""Offline tests for the Phase 2 answer-quality changes. Provider calls are mocked."""
import json
import os
import tempfile
import unittest
import urllib.error
import uuid
from unittest.mock import patch

import answer_contract
import discovery
import enrichment
import jev_research as jev
import market_data
import research as r
import research_store as db
import retrieval
import test_research as baseline
import writer


class PlanAndFollowupTests(unittest.TestCase):
    def test_compare_subjects_parsing(self):
        cases = {
            'Compare PostgreSQL vs SQLite': ('PostgreSQL', 'SQLite'),
            'Postgres vs MySQL for analytics?': ('Postgres', 'MySQL for analytics'),
            'What is the difference between React and Vue?': ('React', 'Vue'),
            'difference between tea and coffee': ('tea', 'coffee'),
            'Compare https://lobstack.ai to Grok Bot': ('lobstack.ai', 'Grok Bot'),
            'Which is better, Rust or Go?': ('Rust', 'Go'),
            'Solana and Bitcoin': ('Solana', 'Bitcoin'),
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(retrieval.compare_subjects(query), expected)
        self.assertIsNone(retrieval.compare_subjects('Is the sky blue?'))

    def test_compare_plan_has_no_placeholder_queries(self):
        for query in ('Compare A and B products', 'Which database should I use?'):
            joined = ' '.join(retrieval.plan(query, [], 'compare'))
            self.assertNotIn('option A', joined)
            self.assertNotIn('option B', joined)
        queries = retrieval.plan('React vs Vue', [], 'compare')
        self.assertEqual(len(queries), 3)
        self.assertTrue(queries[1].startswith('React'))
        self.assertTrue(queries[2].startswith('Vue'))

    def test_standalone_question_for_followups(self):
        history = [{'role': 'user', 'content': 'How do heat pumps work in cold weather?'},
                   {'role': 'assistant', 'content': 'They move heat. [1]'}]
        follow = retrieval.standalone_question('what about the cost?', history, ['Energy.gov heat pumps'])
        self.assertLessEqual(len(follow), 350)
        self.assertIn('heat pumps', follow)
        self.assertTrue(follow.startswith('what about the cost?'))
        # A self-contained new question is not polluted by the previous topic.
        fresh = 'Explain how photosynthesis converts light into chemical energy in plants'
        self.assertEqual(retrieval.standalone_question(fresh, history), fresh)
        self.assertEqual(retrieval.standalone_question('cost?', []), 'cost?')
        long_context = [{'role': 'user', 'content': 'word ' * 400}]
        self.assertLessEqual(len(retrieval.standalone_question('and why?', long_context)), 350)

    def test_plan_uses_standalone_and_never_cuts_mid_word(self):
        history = [{'role': 'user', 'content': 'alpha ' * 300}]
        base = retrieval.plan('and beta?', history, 'standard')[0]
        self.assertLessEqual(len(base), 350)
        self.assertFalse(base.rstrip(')').endswith('alph'))
        self.assertEqual(retrieval.clip_words('abcdef ghijkl', 9), 'abcdef')

    def test_primary_domain_registry_requires_topic_context(self):
        self.assertEqual(retrieval.primary_domains('python snake length'), [])
        self.assertEqual(retrieval.primary_domains('Moon Jae-in policy'), [])
        self.assertEqual(retrieval.primary_domains('http music festival'), [])
        self.assertIn('python.org', retrieval.primary_domains('python asyncio documentation'))
        self.assertIn('nasa.gov', retrieval.primary_domains('why does the moon have phases'))
        self.assertIn('rfc-editor.org', retrieval.primary_domains('http status codes'))
        self.assertEqual(retrieval.primary_domains('PostgreSQL vacuum'), ['postgresql.org'])

    def test_focus_text_keeps_lead_and_relevant_later_sentences(self):
        filler = ' '.join(f'Filler sentence number {i} about nothing.' for i in range(300))
        text = 'Lead sentence about the topic. ' + filler + ' The zebra migration peaks in May. ' + filler
        window = retrieval.focus_text('when does the zebra migration peak', text, 2000)
        self.assertLessEqual(len(window), 2000)
        self.assertIn('Lead sentence', window)
        self.assertIn('zebra migration peaks in May', window)
        self.assertEqual(retrieval.focus_text('q', 'short', 2000), 'short')

    def test_text_date_and_recency(self):
        self.assertEqual(retrieval.text_date('Published March 3, 2026 by staff'), '2026-03-03')
        self.assertEqual(retrieval.text_date('Updated 2026-01-15.'), '2026-01-15')
        self.assertEqual(retrieval.text_date('Posted 7 Feb 2026'), '2026-02-07')
        self.assertEqual(retrieval.text_date('Due on 2999-01-01'), '')
        self.assertEqual(retrieval.recency_intent('news about the merger today'), 'news')
        self.assertEqual(retrieval.recency_intent('latest python version'), 'recent')
        self.assertIsNone(retrieval.recency_intent('why is the sky blue'))
        self.assertEqual(retrieval.news_time_range('news today'), 'day')

    def test_recent_sources_are_boosted_only_with_recency_intent(self):
        from datetime import date, timedelta
        new = (date.today() - timedelta(days=3)).isoformat()
        rows = lambda: [
            {'url': 'https://a.example/x', 'title': 'Release notes', 'domain': 'a.example',
             'text': 'release notes for the framework', 'published_date': '2019-01-01'},
            {'url': 'https://b.example/y', 'title': 'Release notes', 'domain': 'b.example',
             'text': 'release notes for the framework!', 'published_date': new}]
        self.assertEqual(retrieval.rank('latest framework release notes', rows())[0]['domain'], 'b.example')
        plain = retrieval.rank('framework release notes', rows())
        self.assertNotIn('recency', plain[0]['ranking_factors'])


class QuoteShortcutTests(unittest.TestCase):
    def test_false_positives_are_rejected(self):
        for query in ('Bitcoin gas fees explained', 'What is the bitcoin hash rate?', 'Ethereum transaction fee today',
                      'bitcoin trading volume', 'Is bitcoin worth it?', 'How does the bitcoin price get determined?',
                      'Solana network rate limits', 'bitcoin mining difficulty', 'Bitcoin ETF price impact'):
            with self.subTest(query=query):
                self.assertIsNone(market_data.quote_symbol(query))

    def test_price_questions_still_match(self):
        self.assertEqual(market_data.quote_symbol('bitcoin price'), 'BTC')
        self.assertEqual(market_data.quote_symbol('What is bitcoin trading at?'), 'BTC')
        self.assertEqual(market_data.quote_symbol('How much is 1 ETH?'), 'ETH')
        self.assertEqual(market_data.quote_symbol('What is XRP worth?'), 'XRP')


def judged(choice='1', probability=.9, sufficient=.9, conflict=.05, relevance=None, extra=None):
    answers = {'best_passage': {'choice': choice, 'probabilities': {choice: probability}},
               'sufficient': {'noul': sufficient}, 'conflict': {'noul': conflict}}
    for key, value in (relevance or {}).items():
        answers['relevant_' + key] = {'noul': value}
    answers.update(extra or {})
    return {'model': 'jev-test', 'answers': answers}


SOURCES = [{'n': 1, 'title': 'Solar', 'domain': 'a.example', 'url': 'https://a.example/1',
            'text': 'Solar panels turn sunlight into electricity.'},
           {'n': 2, 'title': 'Wind', 'domain': 'b.example', 'url': 'https://b.example/2',
            'text': 'Wind turbines turn wind into electricity.'},
           {'n': 3, 'title': 'Hydro', 'domain': 'c.example', 'url': 'https://c.example/3',
            'text': 'Hydro dams turn falling water into electricity.'}]


class JevGateTests(unittest.TestCase):
    def gate(self, raw, mode='standard'):
        with patch.object(jev, 'call', return_value=raw):
            return jev.judge('How is electricity made from renewables?', SOURCES, mode)

    def test_split_probability_with_many_relevant_sources_can_answer(self):
        raw = judged('1', probability=.34, relevance={'1': .9, '2': .85, '3': .8})
        judgment, selected, usage, _ = self.gate(raw)
        self.assertEqual(judgment['gate'], 'answer')
        self.assertEqual(judgment['relevant_count'], 3)
        self.assertEqual(judgment['evidence_ids'][0], 1)
        self.assertEqual(set(judgment['evidence_ids']), {1, 2, 3})
        self.assertTrue(usage['estimated'])  # no provider usage -> conservative estimate, never zero
        self.assertGreater(usage['input_tokens'], 0)

    def test_low_probability_without_relevance_still_abstains(self):
        judgment, _, _, _ = self.gate(judged('1', probability=.34, relevance={'1': .3, '2': .2}))
        self.assertEqual(judgment['gate'], 'abstain')

    def test_gate_thresholds_come_from_policy(self):
        policy = jev.gate_policy()
        self.assertEqual(policy['sufficient_min'], .65)
        raw = json.loads((__import__('pathlib').Path(jev.__file__).parent / 'evals' / 'quality-policy.json').read_text())
        self.assertIn('jev_gate', raw)

    def test_malformed_answers_raise_jev_error(self):
        for bad in ({'answers': {'best_passage': ['1']}},
                    {'answers': {'best_passage': {'choice': ['1']}}},
                    {'answers': {'best_passage': {'choice': '1', 'probabilities': [1]}, 'sufficient': 'x', 'conflict': {'noul': .1}}},
                    {'answers': {'best_passage': {'choice': '1', 'probabilities': {'1': 'high'}},
                                 'sufficient': {'noul': .9}, 'conflict': {'noul': .1}}},
                    {'answers': {'best_passage': {'choice': '1'}, 'sufficient': None, 'conflict': None}}):
            with self.subTest(bad=bad), self.assertRaises(jev.JevError):
                self.gate(bad)

    def test_deep_mode_carries_more_evidence(self):
        judgment, *_ = self.gate(judged('1', relevance={'1': .9, '2': .9, '3': .9}), 'deep')
        self.assertEqual(len(judgment['evidence_ids']), 3)

    def test_passages_use_stems_and_never_cut_mid_word(self):
        text = 'Intro paragraph here. The batteries were charging quickly overnight. Unrelated closing remark.'
        excerpt, start, end = jev.passage_span('how does battery charge', text)
        self.assertIn('batteries were charging', excerpt)
        self.assertEqual(text[start:end], excerpt)
        long_sentence = ('supercalifragilistic ' * 40).strip()
        excerpt, start, end = jev.passage_span('supercalifragilistic', long_sentence)
        self.assertLessEqual(len(excerpt), 450)
        self.assertTrue(excerpt.endswith('supercalifragilistic'))
        self.assertEqual(long_sentence[start:end], excerpt)


class AbstentionTests(unittest.TestCase):
    def test_structured_partial_answer(self):
        candidates = [{'id': '1', 'title': 'Solar', 'passage': 'Solar panels turn sunlight into electricity.'},
                      {'id': '2', 'title': 'Wind', 'passage': 'Wind turbines turn wind into electricity.'}]
        judgment = {'gate': 'abstain', 'selected': None, 'relevant_ids': [2]}
        answer = jev.format_answer(judgment, None, candidates, SOURCES, 'What is the cost per kilowatt of tidal power?')
        self.assertIn('could not verify a direct answer', answer)
        self.assertIn('What the sources do say', answer)
        self.assertIn('Wind turbines turn wind into electricity. [2]', answer)
        self.assertNotIn('Solar panels turn', answer)  # based on relevant_ids only
        self.assertIn('What is missing', answer)
        self.assertIn('tidal', answer)
        self.assertIn('narrow', answer)

    def test_without_relevant_sources_lists_closest_sources(self):
        answer = jev.format_answer({'gate': 'abstain', 'selected': None, 'relevant_ids': []}, None, [], SOURCES)
        self.assertIn('closest captured sources', answer)
        self.assertEqual(jev.format_answer({'gate': 'abstain', 'selected': None}, None, [], []),
                         'I could not verify an answer from the available sources.')


class UnitLimitTests(unittest.TestCase):
    def test_units_limit_is_configurable(self):
        text = '\n\n'.join(f'Fact {i}. [1]' for i in range(6))
        with self.assertRaises(ValueError):
            answer_contract.units(text)
        self.assertEqual(len(answer_contract.units(text, 6)), 6)
        check = {'probabilities': [.9, .9, .2, .9, .9, .9]}
        self.assertEqual(jev.failing_units(text, check, 6), [2])
        self.assertEqual(jev.supported_prefix(text, check, 6), 'Fact 0. [1]\n\nFact 1. [1]')


class Response:
    def __init__(self, data): self.data = json.dumps(data).encode()
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_): return self.data


class WriterPromptTests(unittest.TestCase):
    def call(self, mode='standard', revision=False, context=None, rejected=None, model='gpt-5.4-mini'):
        captured = {}
        def respond(url, payload, key, timeout):
            captured.update(payload)
            return Response({'status': 'completed', 'output': [{'type': 'message', 'content': [
                {'type': 'output_text', 'text': 'Solar panels make power. [1]'}]}],
                'usage': {'input_tokens': 5, 'output_tokens': 5}})
        sources = [{'n': i, 'title': f'T{i}', 'text': 'Solar panels make power.', 'domain': 'x.example'} for i in range(1, 8)]
        with patch.dict(os.environ, {'ZEARCH_WRITER_MODEL': model, 'OPENAI_API_KEY': 'k'}), \
             patch.object(writer, 'open_provider', side_effect=respond):
            writer.compose('How?', sources, [1, 2, 3, 4, 5, 6, 7], mode, revision, context, rejected)
        return captured

    def test_prompt_rules_and_reasoning(self):
        payload = self.call()
        self.assertEqual(payload['reasoning'], {'effort': 'low'})
        self.assertEqual(payload['max_output_tokens'], writer.MAX_OUTPUT_TOKENS)
        self.assertIn('sources conflict', payload['instructions'])
        self.assertIn('language the question is written in', payload['instructions'])
        self.assertIn('not counting an optional ## Details', payload['instructions'])
        self.assertEqual(len(json.loads(payload['input'])['evidence']), 4)

    def test_non_reasoning_model_gets_no_reasoning_param(self):
        self.assertNotIn('reasoning', self.call(model='gpt-4.1-mini'))

    def test_deep_gets_larger_budget(self):
        payload = self.call('deep')
        self.assertEqual(payload['max_output_tokens'], writer.DEEP_OUTPUT_TOKENS)
        self.assertEqual(len(json.loads(payload['input'])['evidence']), 6)

    def test_followup_context_and_rejected_paragraphs(self):
        payload = self.call(revision=True, context={'standalone': 'Heat pump cost', 'previous': 'Heat pumps move heat.',
                                                    'today': '2026-09-30'}, rejected=['Bad claim. [1]'])
        body = json.loads(payload['input'])
        self.assertEqual(body['standalone_question'], 'Heat pump cost')
        self.assertEqual(body['previous_answer'], 'Heat pumps move heat.')
        self.assertEqual(body['today'], '2026-09-30')
        self.assertEqual(body['rejected_paragraphs'], ['Bad claim. [1]'])
        self.assertIn('rejected_paragraphs', payload['instructions'])


class SearchProviderTests(unittest.TestCase):
    def run_search(self, query, responder):
        with patch.dict(os.environ, {'TAVILY_API_KEY': 'k'}), patch.object(r, 'open_provider', side_effect=responder):
            return r.search(query)

    def test_news_params_only_for_news_intent_and_fallback_on_rejection(self):
        seen = []
        def ok(url, payload, key, timeout=20):
            seen.append(payload)
            return Response({'results': [{'url': 'https://example.com/a', 'title': 'A', 'content': 'Posted May 5, 2026. Body text.'}]})
        rows = self.run_search('latest news today about chips', ok)
        self.assertEqual(seen[0]['topic'], 'news')
        self.assertEqual(seen[0]['time_range'], 'day')
        self.assertEqual(rows[0]['published_date'], '2026-05-05')
        self.assertEqual(rows[0]['published_date_provenance'], 'page_text')
        seen.clear()
        self.run_search('why is the sky blue', ok)
        self.assertNotIn('topic', seen[0]); self.assertNotIn('time_range', seen[0])
        seen.clear()
        def picky(url, payload, key, timeout=20):
            if 'topic' in payload:
                seen.append(payload)
                raise urllib.error.HTTPError(url, 400, 'bad', {}, None)
            return ok(url, payload, key)
        rows = self.run_search('breaking news today', picky)
        self.assertEqual(len(seen), 2); self.assertNotIn('topic', seen[1]); self.assertTrue(rows)
        def broken(url, payload, key, timeout=20):
            raise urllib.error.HTTPError(url, 500, 'down', {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            self.run_search('breaking news today', broken)


class EnrichmentTests(unittest.TestCase):
    def test_provider_snippet_survives_and_page_is_query_focused(self):
        snippet = 'The provider snippet says the answer is forty-two.'
        page = 'Menu Home About. ' * 40 + ' '.join(f'Filler {i} text here.' for i in range(400)) + ' Quokkas live on Rottnest Island. ' + 'More filler words. ' * 200
        source = {'n': 1, 'url': 'https://example.org/a', 'title': 'A', 'text': snippet + '\nold body text', 'domain': 'example.org'}
        with patch.dict(os.environ, {'ZEARCH_ENRICHMENT_ENABLED': '1', 'TAVILY_API_KEY': 'k'}), \
             patch.object(enrichment, '_request', return_value={'results': [{'raw_content': page, 'title': 'Rendered'}]}):
            rows, report = enrichment.enrich([source], 'where do quokkas live')
        self.assertEqual(report['enriched_pages'], 1)
        self.assertIn(snippet, rows[0]['text'])
        self.assertIn('Quokkas live on Rottnest Island', rows[0]['text'])
        self.assertLessEqual(len(rows[0]['text']), 4000)


class PipelineTests(unittest.TestCase):
    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown
    pipeline = baseline.ResearchTests.pipeline

    def reserve_run(self, query, depth='standard', parent=None):
        return db.reserve('alice', uuid.uuid4().hex, uuid.uuid4().hex, query, parent, 'test', 100, self.limits, depth)[0]

    def test_compare_draft_ids_keep_focused_sources_first(self):
        run = self.reserve_run('Compare Alpha vs Beta', 'compare')
        def search(q):
            if q.startswith('Alpha'):
                return [{'url': 'https://alpha.example/', 'title': 'Alpha', 'domain': 'alpha.example', 'text': 'Alpha is a tool for sync.'}]
            if q.startswith('Beta'):
                return [{'url': 'https://beta.example/', 'title': 'Beta', 'domain': 'beta.example', 'text': 'Beta is a tool for chat.'}]
            return [{'url': f'https://g{i}.example/', 'title': f'Roundup {i} Alpha Beta', 'domain': f'g{i}.example',
                     'text': 'Compare Alpha vs Beta roundup with many words ' * 3} for i in range(6)]
        judgment = {'selected': 4, 'selected_probability': .9, 'sufficiency_probability': .9, 'conflict_probability': .1,
                    'gate': 'answer', 'evidence_ids': [4, 5], 'relevant_ids': [5], 'model': 'jev-test'}
        chosen = {'id': '4', 'passage': 'Generic roundup.', 'span_start': 0, 'span_end': 5}
        with self.pipeline(), patch.object(r, 'search', side_effect=search), \
             patch.object(jev, 'judge', return_value=(judgment, chosen, {'input_tokens': 5}, [])):
            with patch.object(writer, 'compose', return_value=('Alpha differs from Beta. [1] [2]', {'model': 'w', 'input_tokens': 1, 'output_tokens': 1})) as compose:
                events = list(r.run('alice', run, []))
        ids = compose.call_args.args[2]
        self.assertEqual(ids[:2], [1, 2])
        self.assertEqual(len(ids), 4)
        sources = events[-1]['run']['sources']
        self.assertEqual({sources[0]['title'], sources[1]['title']}, {'Alpha', 'Beta'})

    def test_followup_search_uses_standalone_question_and_parent_evidence(self):
        parent = self.reserve_run('How do heat pumps work?')
        db.save('alice', parent['id'], status='complete', answer='Heat pumps move heat. [1]',
                sources=[{'n': 1, 'url': 'https://energy.gov/hp', 'title': 'Energy heat pumps', 'domain': 'energy.gov',
                          'text': 'Heat pumps move heat using a refrigerant.'}], usage={}, estimated_cost=1)
        child = self.reserve_run('what about the cost?', parent=parent['id'])
        seen = {}
        def fake_retrieve(query, history, depth, search, standalone=None, seed=None):
            seen.update(query=query, standalone=standalone, seed=seed)
            return [{'n': 1, 'url': 'https://example.com', 'title': 'Source', 'text': 'Evidence answers the Question.',
                     'domain': 'example.com'}], {'queries': [standalone], 'search_calls': 1}
        with self.pipeline(), patch.object(retrieval, 'retrieve', side_effect=fake_retrieve) as _, \
             patch.object(writer, 'compose', return_value=('Evidence answers the Question. [1]', {'model': 'w', 'input_tokens': 1, 'output_tokens': 1})) as compose:
            events = list(r.run('alice', child, db.context('alice', parent['id'])))
        self.assertEqual(events[-1]['type'], 'complete')
        self.assertIn('heat pumps', seen['standalone'])
        self.assertTrue(seen['standalone'].startswith('what about the cost?'))
        self.assertEqual([s['url'] for s in seen['seed']], ['https://energy.gov/hp'])
        context = compose.call_args.args[5]
        self.assertEqual(context['standalone'], seen['standalone'])
        self.assertIn('Heat pumps move heat', context['previous'])
        self.assertRegex(context['today'], r'^\d{4}-\d\d-\d\d$')

    def test_parent_evidence_competes_as_candidates(self):
        seed = [{'n': 3, 'url': 'https://energy.gov/hp', 'title': 'Heat pump cost', 'domain': 'energy.gov',
                 'text': 'Heat pump cost varies by climate.', 'evidence_span': [0, 4]}]
        rows, report = retrieval.retrieve('cost?', [{'role': 'user', 'content': 'heat pumps'}], 'standard',
                                          lambda q: [], standalone='cost? (context: heat pumps)', seed=seed)
        self.assertEqual([row['url'] for row in rows], ['https://energy.gov/hp'])
        self.assertNotIn('evidence_span', rows[0])
        self.assertEqual(rows[0]['matched_queries'], ['previous answer'])

    def test_writer_error_is_retried_once(self):
        run = self.reserve_run('Question')
        ok = ('Evidence answers the Question. [1]', {'model': 'w', 'input_tokens': 20, 'output_tokens': 10})
        with self.pipeline(), patch.object(writer, 'compose', side_effect=[writer.WriterError('transient'), ok]) as compose:
            list(r.run('alice', run, []))
        saved = db.get_run('alice', run['id'])
        self.assertEqual(compose.call_count, 2)
        self.assertEqual(saved['usage']['answer_format'], 'jev_verified_prose')
        self.assertEqual(saved['usage']['writer_attempts'], 2)
        self.assertEqual(saved['usage']['writer_failed_attempts'], 1)

    def test_persistent_writer_error_falls_back_after_one_retry(self):
        run = self.reserve_run('Question')
        with self.pipeline(), patch.object(writer, 'compose', side_effect=writer.WriterError('down')) as compose:
            list(r.run('alice', run, []))
        saved = db.get_run('alice', run['id'])
        self.assertEqual(compose.call_count, 2)
        self.assertEqual(saved['usage']['draft_fallback_reason'], 'writer_error')
        self.assertEqual(saved['usage']['answer_format'], 'jev_selected_excerpt')

    def test_revision_receives_failing_paragraphs(self):
        run = self.reserve_run('Question')
        first = 'Good claim. [1]\n\nBad claim. [1]'
        ok = ('Good claim. [1]', {'model': 'w', 'input_tokens': 5, 'output_tokens': 5})
        first_usage = {'model': 'w', 'input_tokens': 5, 'output_tokens': 5}
        with self.pipeline(), patch.object(writer, 'compose', side_effect=[(first, first_usage), ok]) as compose, \
             patch.object(jev, 'verify', side_effect=[(False, {'probabilities': [.4, .2]}, {'input_tokens': 1}),
                                                      (True, {'probabilities': [.9]}, {'input_tokens': 1})]):
            list(r.run('alice', run, []))
        self.assertEqual(compose.call_args_list[1].args[6], ['Good claim. [1]', 'Bad claim. [1]'])
        self.assertTrue(compose.call_args_list[1].args[4])

    def test_private_note_trim_keeps_web_sources_without_private_hits(self):
        run = db.reserve('alice', uuid.uuid4().hex, uuid.uuid4().hex, 'Question', None, 'test', 100, self.limits, 'standard', True)[0]
        web = [{'n': i, 'url': f'https://w{i}.example/', 'title': f'W{i}', 'domain': f'w{i}.example',
                'text': 'Evidence answers the Question.'} for i in range(1, 9)]
        import workspace_store
        with self.pipeline(), patch.object(retrieval, 'retrieve', return_value=(web, {'queries': ['Question'], 'search_calls': 1})), \
             patch.object(workspace_store, 'knowledge', return_value=[]):
            events = list(r.run('alice', run, []))
        self.assertEqual(len(events[-1]['run']['sources']), 8)

    def test_deep_second_pass_uses_reserved_search_and_rejudges(self):
        run = self.reserve_run('Explain quokka habitat', 'deep')
        queries = []
        def search(q):
            queries.append(q)
            n = len(queries)
            return [{'url': f'https://site{n}.example/', 'title': f'Quokka page {n}', 'domain': f'site{n}.example',
                     'text': f'Quokka habitat details on Rottnest Island, variant {n}. ' * 3}]
        weak = {'selected': 1, 'selected_probability': .5, 'sufficiency_probability': .5, 'conflict_probability': .1,
                'gate': 'abstain', 'evidence_ids': [], 'relevant_ids': [], 'model': 'jev-test'}
        strong = dict(weak, sufficiency_probability=.95, gate='answer', evidence_ids=[1, 2], relevant_ids=[2])
        candidate = lambda n: {'id': str(n), 'passage': 'Quokka habitat details on Rottnest Island.', 'span_start': 0, 'span_end': 40}
        chosen = candidate(1)
        with self.pipeline(), patch.object(r, 'search', side_effect=search), \
             patch.object(jev, 'judge', side_effect=[(weak, None, {'input_tokens': 10}, [candidate(1)]),
                                                     (strong, chosen, {'input_tokens': 12}, [candidate(1), candidate(2)])]) as judge:
            events = list(r.run('alice', run, []))
        saved = db.get_run('alice', run['id'])
        self.assertEqual(len(queries), 3)  # two planned searches plus one gap-driven pass
        self.assertEqual(judge.call_count, 2)
        self.assertEqual(saved['usage']['search_calls'], 3)
        self.assertEqual(saved['usage']['second_pass']['second_pass_added'], 1)
        self.assertEqual(saved['usage']['input_tokens'], 10 + 12 + 5 * 1)  # both judgments plus the draft check
        self.assertEqual(saved['usage']['judgment']['gate'], 'answer')
        self.assertEqual(len(saved['sources']), 3)
        self.assertIsNotNone(r.estimate(saved['usage']))

    def test_answer_gate_skips_second_pass(self):
        run = self.reserve_run('Question', 'deep')
        strong = {'selected': 1, 'selected_probability': .9, 'sufficiency_probability': .95, 'conflict_probability': .1,
                  'gate': 'answer', 'evidence_ids': [1], 'relevant_ids': [1], 'model': 'jev-test'}
        with self.pipeline(), patch.object(jev, 'judge', return_value=(strong, {'id': '1', 'passage': 'Evidence answers the Question.'}, {'input_tokens': 5}, [])) as judge:
            list(r.run('alice', run, []))
        self.assertEqual(judge.call_count, 1)

    def test_gap_query_targets_uncovered_terms(self):
        candidates = [{'id': '1', 'title': 'Solar', 'passage': 'Solar panels turn sunlight into electricity.'}]
        query = retrieval.gap_query('solar panel lifespan warranty', candidates, {'selected': 1, 'relevant_ids': []})
        self.assertIn('lifespan', query)
        self.assertIn('warranty', query)


class DiscoveryTests(unittest.TestCase):
    def test_changes_compare_selected_passages_not_page_noise(self):
        base = {'url': 'https://example.com/', 'evidence_span': [0, 14]}
        previous = {'answer': 'A', 'sources': [dict(base, text='Price is $10. Ad: buy now 1')]}
        noise = {'answer': 'A', 'sources': [dict(base, text='Price is $10. Ad: buy now 2 and a new footer')]}
        real = {'answer': 'A', 'sources': [dict(base, text='Price is $12. Ad: buy now 1')]}
        self.assertEqual(discovery.changes(previous, noise)['changed'], [])
        self.assertEqual(discovery.changes(previous, real)['changed'], ['https://example.com/'])

    setUp = baseline.ResearchTests.setUp
    tearDown = baseline.ResearchTests.tearDown
    reserve = baseline.ResearchTests.reserve

    def completed(self, owner='alice'):
        run, _ = self.reserve(owner)
        db.save(owner, run['id'], status='complete', answer='Answer [1]',
                sources=[{'n': 1, 'url': 'https://example.com/', 'text': 'Old text'}])
        return run['id']

    def test_expired_job_does_not_stall_the_queue(self):
        import time
        import workspace_store as workspace
        first = workspace.save_investigation('alice', self.completed())
        second = workspace.save_investigation('alice', self.completed())
        with patch.dict(os.environ, {'ZEARCH_DISCOVERY_ENABLED': '1'}), patch.object(r, 'ready', return_value=True):
            expired_job = discovery.enqueue('alice', first)
            live_job = discovery.enqueue('alice', second)
            with db.connection() as (conn, marker):
                db.execute(conn, marker, 'UPDATE investigations SET expires=? WHERE id=?', (int(time.time()) - 5, first))
                db.execute(conn, marker, 'UPDATE discovery_jobs SET created=created-100 WHERE id=?', (expired_job,))
            job = discovery.tick()
            self.assertIsNotNone(job)
            self.assertEqual(job['id'], live_job)
            with db.connection() as (conn, marker):
                status = db.execute(conn, marker, 'SELECT status FROM discovery_jobs WHERE id=?', (expired_job,)).fetchone()['status']
            self.assertEqual(status, 'cancelled')


if __name__ == '__main__':
    unittest.main()
