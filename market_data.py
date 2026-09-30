"""Small, deterministic path for supported crypto spot quotes.

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
ASSETS = {'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'SOL': 'Solana', 'XRP': 'XRP'}


PRICE_INTENT = re.compile(r"\b(price|worth|quote|trading at|trades at|how much (?:is|does|are)|cost of|value of)\b")
NOT_A_QUOTE = re.compile(
    r"\b(historical|history|yesterday|prediction|predict|forecast|future|tomorrow|compare|past|ago|"
    r"gas|hash|hashrate|volume|fees?|rates?|market\s*cap|mining|miner|difficulty|dominance|supply|halving|"
    r"transaction|block|wallet|address|etf|stock|shares?|futures|options|why|explain|effect|impact|affect|"
    r"determine[sd]?|calculate|worth\s+(?:it|buying|investing|holding))\b"
    r"|\blast\s+(?:week|month|year)\b|\b20\d{2}\b|\b(?:how|what)\s+(?:does|do)\b")


def quote_symbol(question):
    q = question.lower()
    if (not PRICE_INTENT.search(q) or NOT_A_QUOTE.search(q) or len(q.split()) > 14
            or re.search(r'\b(eur|euro|gbp|pound|cad|canadian|aud|australian)\b', q)):
        return None
    matched = [symbol for symbol, pattern in {
        'BTC': r'\b(bitcoin|btc)\b', 'ETH': r'\b(ethereum|ether|eth)\b',
        'SOL': r'\b(solana|sol)\b', 'XRP': r'\b(xrp|ripple)\b'
    }.items() if re.search(pattern, q)]
    return matched[0] if len(matched) == 1 else None


def wants_btc_usd_quote(question):
    return quote_symbol(question) == 'BTC'


def quote(symbol='BTC', now=None, opener=None):
    if symbol not in ASSETS:
        raise ValueError('Unsupported market product')
    now = time.time() if now is None else now
    opener = opener or urllib.request.urlopen
    ticker_url = f'https://api.exchange.coinbase.com/products/{symbol}-USD/ticker'
    candles_url = f'https://api.exchange.coinbase.com/products/{symbol}-USD/candles'
    request = urllib.request.Request(ticker_url, headers={'User-Agent': 'Zearch/1.0', 'Accept': 'application/json'})
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
    text = f'Coinbase Exchange {symbol}-USD last trade price: {shown} USD per {symbol}. Trade time: {observed}.'
    source = {'n': 1, 'url': ticker_url, 'title': f'Coinbase Exchange {symbol}-USD ticker',
              'domain': 'api.exchange.coinbase.com', 'text': text, 'excerpt': text,
              'retrieved_at': int(now), 'content_type': 'market_ticker',
              'market': {'symbol': symbol, 'name': ASSETS[symbol], 'price': shown,
                         'observed_at': int(stamp.timestamp()), 'venue': 'Coinbase Exchange'}}
    try:
        start = datetime.fromtimestamp(now - 24 * 3600, timezone.utc).isoformat()
        end = datetime.fromtimestamp(now, timezone.utc).isoformat()
        from urllib.parse import urlencode
        candle_url = candles_url + '?' + urlencode({'granularity': 3600, 'start': start, 'end': end})
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
            source['chart'] = {'kind': 'price_series', 'label': f'{symbol}-USD · Coinbase Exchange',
                               'unit': 'USD', 'interval_seconds': 3600,
                               'source_url': candles_url, 'captured_at': int(now), 'points': series}
    except (OSError, ValueError, TypeError, OverflowError, KeyError):
        pass  # The fresh ticker stands on its own when historical candles are unavailable.
    answer = f'{ASSETS[symbol]}’s last traded price on Coinbase Exchange was **{shown} USD** at {observed}. [1]\n\nPrices change continuously and may differ across exchanges.'
    return source, answer
