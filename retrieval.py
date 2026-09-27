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

# Deliberately small, auditable registry. A match prefers the publisher's own
# pages but never excludes independent evidence or claims all other sites are bad.
PRIMARY_DOMAINS = {
    'postgresql': ('postgresql.org',), 'postgres': ('postgresql.org',),
    'sqlite': ('sqlite.org',), 'python': ('python.org', 'docs.python.org'),
    'http': ('rfc-editor.org', 'developer.mozilla.org'),
    'https': ('rfc-editor.org', 'developer.mozilla.org'),
    'moon': ('nasa.gov',), 'heat pump': ('energy.gov',),
}


def primary_domains(query):
    words = set(tokens(query))
    domains = []
    for term, sites in PRIMARY_DOMAINS.items():
        if set(term.split()).issubset(words):
            for site in sites:
                if site not in domains:
                    domains.append(site)
    return domains[:8]


def primary_domain(host, preferred):
    host = (host or '').lower().rstrip('.')
    return any(host == domain or host.endswith('.' + domain) for domain in preferred)


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
    documents = [Counter(tokens(s.get('title', '') + ' ' + s['text'][:3000])) for s in rows]
    terms = set(tokens(query))
    preferred = primary_domains(query)
    mean = sum(sum(d.values()) for d in documents) / max(1, len(documents)) or 1
    for source, words in zip(rows, documents):
        score = 0
        for term in terms:
            count = words[term]
            frequency = sum(term in doc for doc in documents)
            inverse = math.log(1 + (len(rows) - frequency + .5) / (frequency + .5))
            score += inverse * count * 2.2 / (count + 1.2 * (.25 + .75 * sum(words.values()) / mean))
        title_terms = set(tokens(source.get('title', '')))
        focused_terms = set(tokens(source['text'][:800]))
        coverage = len(terms & (title_terms | focused_terms)) / max(1, len(terms))
        provider_score = source.get('provider_score')
        if type(provider_score) not in (int, float) or not math.isfinite(provider_score) or not 0 <= provider_score <= 1:
            provider_score = 0
        score += 1.0 * coverage + .4 * provider_score
        if coverage >= .4 and primary_domain(source.get('domain'), preferred):
            score += 1.5
            source['source_tier'] = 'primary'
        else:
            source['source_tier'] = 'web'
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
        'failed_searches': failed, 'ranking': 'lexical relevance, source provenance, provider score, deduplication and domain diversity'}
