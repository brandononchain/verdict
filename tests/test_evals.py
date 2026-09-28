import json
import tempfile
import unittest
from pathlib import Path
from evals import run, review


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
