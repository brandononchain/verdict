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
        # Search each side directly. Repeating the entire comparison question
        # frequently retrieves generic listicles and misses one subject.
        match = re.match(r'^\s*compare\s+(.{2,140}?)\s+(?:to|vs\.?|versus|with)\s+(.{2,140}?)\s*[?.!]?\s*$', query, re.I)
        if match:
            def subject(value):
                value = value.strip(' ?.!')
                parsed = urlsplit(value)
                return parsed.hostname if parsed.scheme in ('http', 'https') and parsed.hostname else value
            left, right = (subject(part) for part in match.groups())
            queries = [base, left + ' product features official information', right + ' product features official information']
        else:
            queries += [base + ' option A features evidence', base + ' option B tradeoffs evidence']
    return queries


def rank(query, sources, limit=8, budget=24000):
    unique = {}
    for source in sources:
        key = canonical(source['url']) if source.get('url') else 'note:' + source['note_id']
        previous = unique.get(key)
        matched = list(dict.fromkeys((previous or {}).get('matched_queries', []) + source.get('matched_queries', [])))
        if previous is None or len(source['text']) > len(previous['text']):
            unique[key] = dict(source)
            unique[key]['matched_queries'] = matched
        else:
            previous['matched_queries'] = matched
        if source.get('url'):
            unique[key]['canonical_url'] = key
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
        lexical_relevance = score
        title_terms = set(tokens(source.get('title', '')))
        focused_terms = set(tokens(source['text'][:800]))
        coverage = len(terms & (title_terms | focused_terms)) / max(1, len(terms))
        provider_score = source.get('provider_score')
        if type(provider_score) not in (int, float) or not math.isfinite(provider_score) or not 0 <= provider_score <= 1:
            provider_score = 0
        score += 1.0 * coverage + .4 * provider_score
        primary_boost = 0
        if coverage >= .4 and primary_domain(source.get('domain'), preferred):
            primary_boost = 1.5
            score += primary_boost
            source['source_tier'] = 'primary'
        else:
            source['source_tier'] = 'web'
        source['ranking_factors'] = {'lexical_relevance': round(lexical_relevance, 3),
                                     'query_coverage': round(coverage, 3),
                                     'provider_score': round(provider_score, 3),
                                     'primary_boost': primary_boost}
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
        row['selection_reasons'] = ['lexical relevance', 'query coverage', 'domain diversity']
        if row['ranking_factors']['primary_boost']:
            row['selection_reasons'].append('matched publisher domain')
        if row['ranking_factors']['provider_score']:
            row['selection_reasons'].append('provider score')
        if len(row.get('matched_queries', [])) > 1:
            row['selection_reasons'].append('found by multiple queries')
        selected.append(row)
        if len(selected) == limit:
            break
    return selected


def retrieve(query, history, depth, search):
    queries = plan(query, history, depth)
    results, failed = [], 0
    failure_kinds = Counter()
    # Provider timeouts bound each worker; every attempt is reserved before here.
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = [pool.submit(search, q) for q in queries]
        for query_text, future in zip(queries, futures):
            try:
                for source in future.result():
                    row = dict(source)
                    row['matched_queries'] = [query_text]
                    results.append(row)
            except Exception as exc:
                failed += 1
                failure_kinds[type(exc).__name__] += 1
    candidate_urls = list(dict.fromkeys(canonical(row['url']) for row in results if row.get('url')))
    selected = rank(query, results, limit=8)
    if depth == 'compare' and len(queries) == 3:
        # Put one result from each focused search first so the four-source
        # writer window actually contains both sides of a comparison.
        focused_sources = []
        for focused in queries[1:]:
            option = rank(query, [row for row in results if focused in row.get('matched_queries', [])], limit=1)
            if option and canonical(option[0]['url']) not in {canonical(row['url']) for row in focused_sources}:
                focused_sources.append(option[0])
        keys = {canonical(row['url']) for row in focused_sources}
        selected = (focused_sources + [row for row in selected if canonical(row['url']) not in keys])[:8]
        for n, row in enumerate(selected, 1):
            row['n'] = n
    return selected, {'queries': queries, 'search_calls': len(queries),
        'failed_searches': failed, 'search_failure_kinds': dict(failure_kinds),
        'candidate_urls': candidate_urls, 'selected_urls': [row['canonical_url'] for row in selected if row.get('canonical_url')],
        'ranking': 'lexical relevance, source provenance, provider score, deduplication and domain diversity'}
