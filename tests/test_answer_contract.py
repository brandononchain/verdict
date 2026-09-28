import unittest
from answer_contract import units


class AnswerContractTests(unittest.TestCase):
    def test_code_fence_checked_with_cited_explanation(self):
        result = units('Use this query. [1]\n\n```sql\nSELECT 1;\n\nSELECT 2;\n```')
        self.assertEqual(len(result), 1)
        self.assertIn('SELECT 2', result[0])

    def test_heading_attaches_to_table(self):
        result = units('The answer is 2. [1]\n\n## Details\n\n| Year | Value |\n| --- | --- |\n| 2024 | 2 [1] |')
        self.assertEqual(len(result), 2)
        self.assertTrue(result[1].startswith('## Details'))

    def test_bare_or_unclosed_code_rejected(self):
        for answer in ('```py\nprint(1)\n```', 'Explanation [1]\n\n```py\nprint(1)'):
            with self.assertRaises(ValueError): units(answer)
