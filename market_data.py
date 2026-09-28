"""Small, deterministic path for time-sensitive BTC spot quotes.

The Exchange ticker is a last trade on one venue, not a global reference price.
Never substitute an old web snippet when the live quote is unavailable.
"""
import json
import math
import re
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

TICKER_URL = 'https://api.exchange.coinbase.com/products/BTC-USD/ticker'
CANDLES_URL = 'https://api.exchange.coinbase.com/products/BTC-USD/candles'


def wants_btc_usd_quote(question):
    q = question.lower()
    return (bool(re.search(r'\b(bitcoin|btc)\b', q))
            and bool(re.search(r'\b(price|trading|worth|quote|rate)\b', q))
            and (bool(re.search(r'\b(current|currently|right now|now|live|today|latest)\b', q))
                 or bool(re.search(r'\b(price|quote|worth)\b', q)))
            and not re.search(r'\b(historical|history|yesterday|prediction|forecast|future|tomorrow|compare|past|ago)\b|\blast\s+(?:week|month|year)\b|\b20\d{2}\b', q)
            and not re.search(r'\b(eur|euro|gbp|pound|cad|canadian|aud|australian)\b', q))


def quote(now=None, opener=None):
    now = time.time() if now is None else now
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(TICKER_URL, headers={'User-Agent': 'Zearch/1.0', 'Accept': 'application/json'})
    with opener(request, timeout=8) as response:
        raw = response.read(16_001)
    if len(raw) > 16_000:
        raise ValueError('Oversized market quote')
    data = json.loads(raw)
    try:
        price = Decimal(str(data['price']))
        tick = datetime.fromisoformat(data['time'].replace('Z', '+00:00'))
        if not price.is_finite() or price <= 0 or tick.tzinfo is None:
            raise ValueError('Invalid market quote')
        stamp = tick.astimezone(timezone.utc)
        age = now - stamp.timestamp()
        if not math.isfinite(age) or age < -30 or age > 120:
            raise ValueError('Stale market quote')
    except (KeyError, TypeError, AttributeError, InvalidOperation) as exc:
        raise ValueError('Invalid market quote') from exc
    shown = f'${price:,.2f}'
    observed = stamp.strftime('%Y-%m-%d %H:%M:%S UTC')
    text = f'Coinbase Exchange BTC-USD last trade price: {shown} USD per BTC. Trade time: {observed}.'
    source = {'n': 1, 'url': TICKER_URL, 'title': 'Coinbase Exchange BTC-USD ticker',
              'domain': 'api.exchange.coinbase.com', 'text': text, 'excerpt': text,
              'retrieved_at': int(now), 'content_type': 'market_ticker'}
    try:
        start = datetime.fromtimestamp(now - 24 * 3600, timezone.utc).isoformat()
        end = datetime.fromtimestamp(now, timezone.utc).isoformat()
        from urllib.parse import urlencode
        candle_url = CANDLES_URL + '?' + urlencode({'granularity': 3600, 'start': start, 'end': end})
        candles_request = urllib.request.Request(candle_url, headers={'User-Agent': 'Zearch/1.0', 'Accept': 'application/json'})
        with opener(candles_request, timeout=8) as response:
            candles_raw = response.read(64_001)
        if len(candles_raw) > 64_000:
            raise ValueError('Oversized candles')
        rows = json.loads(candles_raw)
        if not isinstance(rows, list) or len(rows) > 300:
            raise ValueError('Invalid candles')
        points = {}
        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                continue
            bucket, low, high, opening, close, volume = row[:6]
            if type(bucket) is not int or not now - 26 * 3600 <= bucket <= now + 60:
                continue
            values = [float(v) for v in (low, high, opening, close, volume)]
            if not all(math.isfinite(v) for v in values) or min(values[:4]) <= 0 or values[4] < 0 or not values[0] <= values[3] <= values[1]:
                continue
            points[bucket] = [bucket, round(values[3], 2)]
        series = [points[key] for key in sorted(points)][-26:]
        if len(series) >= 2:
            source['chart'] = {'kind': 'price_series', 'label': 'BTC-USD · Coinbase Exchange',
                               'unit': 'USD', 'interval_seconds': 3600,
                               'source_url': CANDLES_URL, 'captured_at': int(now), 'points': series}
    except (OSError, ValueError, TypeError, OverflowError, KeyError):
        pass  # The fresh ticker stands on its own when historical candles are unavailable.
    answer = f'Bitcoin’s last traded price on Coinbase Exchange was **{shown} USD** at {observed}. [1]\n\nPrices change continuously and may differ across exchanges.'
    return source, answer
