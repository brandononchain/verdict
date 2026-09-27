"""Bounded query diversification and deterministic lexical evidence ranking.

This is a transparent baseline, not an embedding/semantic reranker.
"""
import hashlib
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STOP = set('a an the is are was were of to in on for and or what which how does do with by from '
           'can could would will you your me my i it this that tell give find show please currently now'.split())


def tokens(text):
    return [t for t in re.findall(r'\w+', text.lower()) if len(t) > 1 and t not in STOP]


def canonical(url):
    p = urlsplit(url)
    params = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/') or '/', urlencode(sorted(params)), ''))


def plan(query, history, depth):
    previous = [m['content'] for m in history if m['role'] == 'user'][-2:]
    context = ' | '.join(previous)[-1000:]
    base = (context + ' | ' + query) if context else query
    queries = [base]
    if depth == 'deep':
        queries += [base + ' primary sources official documentation evidence', base + ' limitations conflicting evidence independent analysis']
    elif depth == 'compare':
        queries += [base + ' advantages strengths direct comparison evidence',
                    base + ' disadvantages limitations tradeoffs alternatives independent evidence']
    return queries


def rank(query, sources, limit=8, budget=24000):
    unique = {}
    for source in sources:
        key = canonical(source['url']) if source.get('url') else 'note:' + source['note_id']
        if key not in unique or len(source['text']) > len(unique[key]['text']):
            unique[key] = dict(source)
    rows = list(unique.values())
    documents = [Counter(tokens(s.get('title', '') + ' ' + s['text'])) for s in rows]
    terms = set(tokens(query))
    mean = sum(sum(d.values()) for d in documents) / max(1, len(documents)) or 1
    for source, words in zip(rows, documents):
        score = 0
        for term in terms:
            count = words[term]
            frequency = sum(term in doc for doc in documents)
            inverse = math.log(1 + (len(rows) - frequency + .5) / (frequency + .5))
            score += inverse * count * 2.2 / (count + 1.2 * (.25 + .75 * sum(words.values()) / mean))
        source['relevance'] = round(score, 4)
    rows.sort(key=lambda s: (-s['relevance'], s.get('url', s.get('note_id', ''))))
    selected, domains, fingerprints = [], Counter(), set()
    for row in rows:
        fingerprint = hashlib.sha256(re.sub(r'\s+', ' ', row['text']).strip().encode()).hexdigest()
        domain = row.get('domain') or 'private'
        if fingerprint in fingerprints or domains[domain] >= 2:
            continue
        text = row['text'][:min(4000, budget)]
        if not text:
            break
        fingerprints.add(fingerprint); domains[domain] += 1; budget -= len(text)
        row.update(n=len(selected) + 1, text=text, excerpt=text[:450], fingerprint=fingerprint)
        selected.append(row)
        if len(selected) == limit:
            break
    return selected


def retrieve(query, history, depth, search):
    queries = plan(query, history, depth)
    results, failed = [], 0
    # Provider timeouts bound each worker; every attempt is reserved before here.
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = [pool.submit(search, q) for q in queries]
        for future in futures:
            try:
                results.extend(future.result())
            except Exception:
                failed += 1
    return rank(query, results), {'queries': queries, 'search_calls': len(queries),
        'failed_searches': failed, 'ranking': 'lexical BM25 with URL/content deduplication and domain diversity'}
