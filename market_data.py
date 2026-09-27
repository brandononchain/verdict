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


def wants_btc_usd_quote(question):
    q = question.lower()
    return (bool(re.search(r'\b(bitcoin|btc)\b', q))
            and bool(re.search(r'\b(price|trading|worth|quote|rate)\b', q))
            and bool(re.search(r'\b(current|currently|right now|now|live|today|latest)\b', q))
            and not re.search(r'\b(historical|history|yesterday|prediction|forecast|future|tomorrow|compare)\b', q)
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
    answer = f'Bitcoin’s last traded price on Coinbase Exchange was **{shown} USD** at {observed}. [1]\n\nPrices change continuously and may differ across exchanges.'
    return source, answer
