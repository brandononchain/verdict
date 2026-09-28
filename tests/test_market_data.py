import json
import time
import unittest
from datetime import datetime, timezone

import market_data


class MarketDataTests(unittest.TestCase):
    def test_quote_intent_is_narrow(self):
        self.assertTrue(market_data.wants_btc_usd_quote('Can you tell me what the price of Bitcoin is currently?'))
        self.assertTrue(market_data.wants_btc_usd_quote('Can you tell me the price of Bitcoin?'))
        self.assertFalse(market_data.wants_btc_usd_quote('Predict Bitcoin price tomorrow'))
        self.assertFalse(market_data.wants_btc_usd_quote('Bitcoin price last week'))
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

    def test_bounded_candle_series_is_attached_to_fresh_quote(self):
        now = time.time()
        stamp = datetime.fromtimestamp(now - 3, timezone.utc).isoformat()
        class Response:
            def __init__(self, data): self.data=json.dumps(data).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, size): return self.data
        def opener(request, timeout):
            if '/candles' in request.full_url:
                hour = int(now // 3600) * 3600
                return Response([[hour-3600, 100, 110, 103, 105, 1],
                                 [hour-7200, 95, 105, 99, 100, 2]])
            return Response({'price':'106','time':stamp})
        source, answer = market_data.quote(now=now, opener=opener)
        self.assertIn('$106.00',answer)
        self.assertEqual(source['chart']['points'],[[int(now // 3600)*3600-7200,100],
                                                    [int(now // 3600)*3600-3600,105]])
        self.assertEqual(source['chart']['source_url'],market_data.CANDLES_URL)


if __name__ == '__main__':
    unittest.main()
