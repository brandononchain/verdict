import json
import time
import unittest
from datetime import datetime, timezone

import market_data


class MarketDataTests(unittest.TestCase):
    def test_quote_intent_is_narrow(self):
        self.assertTrue(market_data.wants_btc_usd_quote('Can you tell me what the price of Bitcoin is currently?'))
        self.assertFalse(market_data.wants_btc_usd_quote('Predict Bitcoin price tomorrow'))
        self.assertFalse(market_data.wants_btc_usd_quote('What was the Bitcoin price yesterday?'))
        self.assertFalse(market_data.wants_btc_usd_quote('Current Bitcoin price in EUR'))

    def test_fresh_quote_is_cited_and_timestamped(self):
        now = time.time()
        stamp = datetime.fromtimestamp(now - 3, timezone.utc).isoformat()
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return json.dumps({'price': '109123.45', 'time': stamp}).encode()
        source, answer = market_data.quote(now=now, opener=lambda *args, **kwargs: Response())
        self.assertIn('$109,123.45', answer)
        self.assertIn('[1]', answer)
        self.assertIn('Coinbase Exchange', source['title'])
        self.assertEqual(source['url'], market_data.TICKER_URL)

    def test_old_quote_is_rejected(self):
        now = time.time()
        stamp = datetime.fromtimestamp(now - 300, timezone.utc).isoformat()
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return json.dumps({'price': '109123.45', 'time': stamp}).encode()
        with self.assertRaisesRegex(ValueError, 'Stale'):
            market_data.quote(now=now, opener=lambda *args, **kwargs: Response())


if __name__ == '__main__':
    unittest.main()
