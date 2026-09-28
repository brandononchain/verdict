import json
import tempfile
import unittest
from pathlib import Path
from evals import run, review, quality_gate, retrieval_quality


class EvaluationWorkflowTests(unittest.TestCase):
    def test_versioned_corpus_and_followup_order(self):
        data = run.corpus()
        self.assertEqual(len(data['cases']), 100)
        self.assertEqual({case['category'] for case in data['cases']},
                         {'factual','technical','current','comparison','ambiguous','unsupported','adversarial','conflict','synthesis','followup'})
        self.assertEqual(len([case for case in data['cases'] if case['temporal']=='current']), 12)
        chosen = run.selection(data['cases'], ['followup-03'], None, 1)
        self.assertEqual([case['id'] for case in chosen], ['current-01','followup-03'])
        self.assertEqual([case['mode'] for case in chosen], ['standard','standard'])

    def test_blank_scorecard_requires_complete_human_review(self):
        with tempfile.TemporaryDirectory() as directory:
            results, cards = Path(directory)/'results.jsonl', Path(directory)/'cards.jsonl'
            result = dict(version='m6.2-v1', case_id='current-01', category='current',
                          mode='standard', temporal='current', run_id='r1', status='complete')
            results.write_text(json.dumps(result)+'\n')
            self.assertEqual(review.init(results, cards), 1)
            self.assertEqual(review.report(review.read_rows(cards))['reviewed'], 0)
            card = review.read_rows(cards)[0]
            card.update(reviewer='human', reviewed_at='2026-09-28T00:00:00Z',
                        citations_opened=True, failure_stage='none')
            card['scores'] = dict.fromkeys(review.DIMENSIONS, 'pass')
            self.assertEqual(review.report([card])['by_mode']['standard']['scores']['freshness']['pass'], 1)
            card['citations_opened'] = False
            with self.assertRaises(ValueError): review.report([card])
            card['citations_opened'] = True
            card['scores']['freshness'] = 'na'
            with self.assertRaises(ValueError): review.report([card])

    def test_duplicate_results_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'results.jsonl'
            row = {'run_id':'same'}
            path.write_text(json.dumps(row)+'\n'+json.dumps(row)+'\n')
            with self.assertRaises(ValueError): review.read_rows(path)

    def test_release_gate_needs_complete_human_cohort_and_measured_thresholds(self):
        self.assertEqual(quality_gate.evaluate([], {})['status'], 'HOLD')
        rows=[]
        for case in run.corpus()['cases']:
            rows.append(dict(version='m6.2-v1', case_id=case['id'], category=case['category'],
                             mode=case['mode'], temporal=case['temporal'], run_id=case['id'],
                             status='complete', reviewer='human', reviewed_at='2026-09-28T00:00:00Z',
                             citations_opened=True, scores={key:'pass' for key in review.DIMENSIONS},
                             failure_stage='none', total_ms=5000, estimated_cost=12000))
        policy={'version':'m6.4-v1','baseline_id':'test-fixture-only','thresholds':{
            mode:{'min_pass_rate':{key:.95 for key in review.DIMENSIONS},
                  'max_p95_total_ms':6000,'max_p95_estimated_cost_usd':.02}
            for mode in quality_gate.MODES}}
        self.assertEqual(quality_gate.evaluate(rows, {})['status'], 'HOLD')
        self.assertEqual(quality_gate.evaluate(rows, policy)['status'], 'GO')
        rows[0]['scores']['citation_support']='fail'
        policy['thresholds']['standard']['min_pass_rate']['citation_support']=1
        self.assertEqual(quality_gate.evaluate(rows, policy)['status'], 'HOLD')

    def test_retrieval_quality_requires_human_candidate_judgments(self):
        case=run.corpus()['cases'][0]
        card=dict(version='m6.2-v1',case_id=case['id'],mode=case['mode'],temporal=case['temporal'],
                  status='complete',reviewer='human',reviewed_at='2026-09-28T00:00:00Z',
                  citations_opened=True, scores={key:'pass' for key in review.DIMENSIONS},
                  failure_stage='none',source_relevance_reviewed=True,
                  candidate_urls=['https://example.org/a','https://example.org/b'],
                  selected_urls=['https://example.org/a'],primary_selected_urls=['https://example.org/a'],
                  relevant_candidate_urls=['https://example.org/a','https://example.org/b'])
        result=retrieval_quality.report([card])['by_mode'][case['mode']]
        self.assertEqual(result['candidate_recall'],.5)
        self.assertEqual(result['matched_publisher_share'],1)
        card['relevant_candidate_urls']=['https://example.org/outside']
        with self.assertRaises(ValueError): retrieval_quality.report([card])
