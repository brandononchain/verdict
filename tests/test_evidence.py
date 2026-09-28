import unittest
from evidence import window


class EvidenceWindowTests(unittest.TestCase):
    def test_keeps_inspected_tail_within_model_bound(self):
        source = {'text': 'Navigation. ' * 320 + 'Relevant answer is at the end.'}
        at = source['text'].index('Relevant answer')
        source['evidence_span'] = [at, len(source['text'])]
        excerpt = window(source)
        self.assertLessEqual(len(excerpt), 3000)
        self.assertIn('Relevant answer is at the end.', excerpt)
        self.assertNotEqual(excerpt, source['text'][:3000])

    def test_invalid_span_falls_back_to_prefix(self):
        source = {'text': 'A' * 4000, 'evidence_span': [5000, 5100]}
        self.assertEqual(window(source), 'A' * 3000)
