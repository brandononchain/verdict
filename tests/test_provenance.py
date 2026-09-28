import unittest
from datetime import datetime, timezone
from provenance import publication_date


class PublicationDateTests(unittest.TestCase):
    def test_accepts_iso_and_rfc_dates(self):
        captured = int(datetime(2026, 9, 28, tzinfo=timezone.utc).timestamp())
        self.assertEqual(publication_date('2026-09-27', captured), '2026-09-27')
        self.assertEqual(publication_date('Sun, 27 Sep 2026 23:00:00 GMT', captured), '2026-09-27')
        self.assertEqual(publication_date('2026-09-27T23:00:00-05:00', captured), '2026-09-28')

    def test_rejects_invalid_and_implausible_dates(self):
        captured = int(datetime(2026, 9, 28, tzinfo=timezone.utc).timestamp())
        for value in ('unknown', '2030-01-01', '2026-09-29', '2026-02-30', '2026-09-28' * 20, None):
            with self.subTest(value=value):
                self.assertEqual(publication_date(value, captured), '')
