"""Bounded query diversification and deterministic lexical evidence ranking.

This is a transparent baseline, not an embedding/semantic reranker.
"""
import hashlib
import math
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STOP = set('a an the is are was were of to in on for and or what which how does do with by from '
           'can could would will you your me my i it this that tell give find show please currently now'.split())

# Deliberately small, auditable registry. A match prefers the publisher's own
# pages but never excludes independent evidence or claims all other sites are bad.
# Each entry is (sites, context words). Ambiguous names (python, moon, http) only
# match together with a topic word so "python snake" or "Moon Jae-in" do not.
_PYTHON_CONTEXT = frozenset('docs documentation library module stdlib pep version release syntax function package interpreter asyncio typing decorator generator dataclass pip venv import'.split())
_HTTP_CONTEXT = frozenset('status header headers method methods protocol request response rfc cache caching cookie cookies redirect verb verbs'.split())
_MOON_CONTEXT = frozenset('phase phases orbit orbital lunar tide tides crater craters eclipse apollo artemis landing surface face regolith'.split())
PRIMARY_DOMAINS = {
    'postgresql': (('postgresql.org',), None), 'postgres': (('postgresql.org',), None),
    'sqlite': (('sqlite.org',), None), 'python': (('python.org', 'docs.python.org'), _PYTHON_CONTEXT),
    'http': (('rfc-editor.org', 'developer.mozilla.org'), _HTTP_CONTEXT),
    'https': (('rfc-editor.org', 'developer.mozilla.org'), _HTTP_CONTEXT),
    'moon': (('nasa.gov',), _MOON_CONTEXT), 'heat pump': (('energy.gov',), None),
}


def primary_domains(query):
    words = set(tokens(query))
    domains = []
    for term, (sites, context) in PRIMARY_DOMAINS.items():
        if not set(term.split()).issubset(words):
            continue
        if context is not None and not words & context:
            continue
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


def stem(word):
    """Light suffix stripping so 'panels'/'panel' and 'making'/'makes' agree."""
    w = word.lower()
    if len(w) > 4 and w.endswith('ies'):
        w = w[:-3] + 'y'
    elif len(w) > 3 and w.endswith('s') and not w.endswith('ss'):
        w = w[:-1]
    if len(w) > 5 and w.endswith('ing'):
        w = w[:-3]
    elif len(w) > 4 and w.endswith('ed'):
        w = w[:-2]
    if len(w) > 4 and w.endswith('e'):
        w = w[:-1]
    return w


def stems(text):
    return [stem(t) for t in tokens(text)]


def clip_words(text, limit):
    """Trim to at most `limit` characters without cutting a word in half."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if not text[limit].isspace():
        space = cut.rfind(' ')
        if space >= limit * 0.5:
            cut = cut[:space]
    return cut.rstrip(' ,;:-')


_SENTENCE = re.compile(r'(?<=[.!?])\s+|\n+')


def _sentences(text):
    out, at = [], 0
    for match in _SENTENCE.finditer(text):
        if text[at:match.start()].strip():
            out.append((at, match.start()))
        at = match.end()
    if text[at:].strip():
        out.append((at, len(text)))
    return out


def focus_text(query, text, limit=4000, lead=800):
    """Query-focused window: leading text plus the best-scoring later sentences.

    The result is stored as the source text, so evidence spans computed later
    refer to it directly. Sentences are kept whole and in their original order.
    """
    if not isinstance(text, str) or len(text) <= limit:
        return text
    spans = _sentences(text)
    if not spans:
        return text[:limit]
    terms = set(stems(query))
    chosen, used = [], 0
    for index, (a, b) in enumerate(spans):
        if used and used + (b - a) > lead:
            break
        chosen.append(index); used += (b - a) + 1
    rest = [i for i in range(len(spans)) if i not in set(chosen)]
    # Rarer terms count more: weight by inverse frequency across the document.
    document = Counter(w for a, b in spans for w in set(stems(text[a:b])))
    def weight(term):
        return math.log(1 + len(spans) / (1 + document[term]))
    scored = []
    for i in rest:
        a, b = spans[i]
        words = set(stems(text[a:b]))
        score = sum(weight(t) for t in terms & words)
        if score:
            scored.append((-score, i))
    scored.sort()
    for _, i in scored:
        a, b = spans[i]
        if used + (b - a) + 1 > limit:
            continue
        chosen.append(i); used += (b - a) + 1
    if len(chosen) == len(set(chosen)) and used < limit * 0.6:
        # Few matches: fill with the following text so the window is not tiny.
        for i in rest:
            if i in chosen:
                continue
            a, b = spans[i]
            if used + (b - a) + 1 > limit:
                break
            chosen.append(i); used += (b - a) + 1
    parts = []
    for i in sorted(set(chosen)):
        a, b = spans[i]
        parts.append(text[a:b].strip() if b - a <= limit else clip_words(text[a:b], limit))
    return '\n'.join(parts)[:limit]


MONTHS = {m: n for n, m in enumerate('jan feb mar apr may jun jul aug sep oct nov dec'.split(), 1)}
_ISO_DATE = re.compile(r'\b(20\d\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b')
_MDY_DATE = re.compile(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b', re.I)
_DMY_DATE = re.compile(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(20\d\d)\b', re.I)


def text_date(text, captured_at=None):
    """First plausible calendar date in the opening of a page, as ISO, or ''."""
    head = (text or '')[:1500]
    found = None
    match = _ISO_DATE.search(head)
    if match:
        found = tuple(int(g) for g in match.groups())
    else:
        m = _MDY_DATE.search(head)
        d = _DMY_DATE.search(head)
        if m:
            found = (int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        elif d:
            found = (int(d.group(3)), MONTHS[d.group(2).lower()], int(d.group(1)))
    if not found:
        return ''
    try:
        value = date(*found)
    except ValueError:
        return ''
    if value > date.fromtimestamp(captured_at if captured_at else time.time()):
        return ''
    return value.isoformat()


_NEWS = re.compile(r"\b(news|today|tonight|breaking|this week|this month|yesterday|announce[sd]?|announcement|"
                   r"just (?:released|launched|announced)|last (?:24 hours|few days|week))\b", re.I)
_RECENT = re.compile(r"\b(latest|newest|recent(?:ly)?|current(?:ly)?|right now|up[- ]to[- ]date|these days)\b", re.I)


def recency_intent(query):
    """'news' for explicit news/time-window asks, 'recent' for latest/current, else None."""
    if _NEWS.search(query or ''):
        return 'news'
    if _RECENT.search(query or ''):
        return 'recent'
    return None


def news_time_range(query):
    q = (query or '').lower()
    if re.search(r'\b(today|tonight|yesterday|24 hours|breaking)\b', q):
        return 'day'
    if re.search(r'\b(this week|last week|few days)\b', q):
        return 'week'
    return 'month'


def recency_boost(published, now=None):
    try:
        age = ((now or date.today()) - date.fromisoformat(published)).days
    except (TypeError, ValueError):
        return 0.0
    if age < 0:
        return 0.0
    return .6 if age <= 30 else .35 if age <= 180 else .1 if age <= 730 else 0.0


_FOLLOWUP_WORDS = re.compile(r"\b(it|its|that|this|they|them|their|those|these|he|she|his|her|there|also|"
                             r"another|same|former|latter|instead|above|previous|earlier)\b", re.I)


_FOLLOWUP_START = ('and ', 'but ', 'also ', 'so ', 'what about', 'how about', 'why', 'how so', 'which one', 'which is better',
                   'compare those', 'compare them', 'compare these', 'is that', 'does that', 'do they', 'is it', 'does it')


def is_followup(query):
    text = query.strip().lower()
    return (len(tokens(query)) <= 5 or bool(_FOLLOWUP_WORDS.search(text)) or text.startswith(_FOLLOWUP_START))


_REFINEMENTS = (
    ('translate', re.compile(r"^(?:please\s+)?(?:translate\b|(?:say|write|give me)\s+(?:that|it|this)\s+in\b|in\s+(?:spanish|french|german|italian|portuguese|japanese|chinese|korean|arabic|hindi|dutch|russian)\b)", re.I)),
    ('shorten', re.compile(r"^(?:please\s+)?(?:(?:make|keep)\s+(?:it|that|this)\s+(?:much\s+)?(?:shorter|briefer|more concise|concise|brief|short)|shorter|shorten\b|tl;?dr|too long|be (?:more )?(?:brief|concise)|(?:can you\s+)?summari[sz]e\s+(?:it|that|this)|in (?:one|two|a few) (?:sentences?|lines?|words?))", re.I)),
    ('expand', re.compile(r"^(?:please\s+)?(?:(?:make|give)\s+(?:it|that|this|me)\s+(?:a bit |much )?(?:longer|more detailed|more detail)|longer|expand\b|elaborate\b|more detail|explain (?:that |it |this )?(?:more|further|in more detail)|go deeper|tell me more)", re.I)),
    ('reformat', re.compile(r"^(?:please\s+)?(?:(?:put|show|give|write|turn|format|convert|rewrite)\s+(?:it|that|this|me)?\s*(?:in|as|into|to)\s+(?:a\s+|an\s+)?(?:table|list|bullets?|bullet points?|steps?|numbered list|outline|checklist)|as (?:a )?(?:table|list|bullets?|bullet points?|steps?|checklist)|bullet points?)", re.I)),
)


def refinement_intent(query):
    """'shorten' | 'expand' | 'reformat' | 'translate' when the user only asks to reshape the previous answer, else None."""
    text = re.sub(r'\s+', ' ', query.strip())
    if not text or len(text) > 80:
        return None
    for name, pattern in _REFINEMENTS:
        if pattern.match(text):
            return name
    return None


def _first_sentence(text, limit=110):
    text = re.sub(r'\s+', ' ', re.sub(r'\[\d+\]', '', re.sub(r'[#*`|>]', ' ', text or ''))).strip()
    match = re.match(r'(.+?[.!?])(?:\s|$)', text)
    return clip_words(match.group(1) if match else text, limit)


def standalone_question(query, history, parent_titles=()):
    """Deterministic standalone search question for a follow-up, at most 350 characters.

    The previous user question anchors the topic; when it was a comparison the two
    subjects are named explicitly ("compare those", "which is better"); the first
    sentence of the previous answer and parent source titles fill any remaining room.
    """
    query = query.strip()
    previous = [m['content'] for m in history if m.get('role') == 'user' and m.get('content')]
    if not previous or len(query) > 250 or not is_followup(query):
        return query
    room = 350 - len(query) - len(' (context: )')
    if room < 40:
        return query
    context = re.sub(r'\s+', ' ', previous[-1]).strip()
    subjects = compare_subjects(context)
    if subjects and re.search(r'\b(those|them|these|both|which|better|differ\w*|compare|one)\b', query, re.I):
        context = f'comparison of {subjects[0]} and {subjects[1]}'
    answer = next((m['content'] for m in reversed(history) if m.get('role') == 'assistant' and m.get('content')), '')
    lead = _first_sentence(answer) if len(query.split()) <= 6 else ''
    extras = ([lead] if lead else []) + [re.sub(r'\s+', ' ', str(t)).strip() for t in parent_titles if t][:2]
    for extra in extras:
        if len(context) + 3 + len(extra) <= room:
            context += ' ; ' + extra
    return f'{query} (context: {clip_words(context, room)})'


def compare_subjects(query):
    """Parse the two sides of a comparison question, or None."""
    text = query.strip()
    patterns = (
        r'^(?:what(?:\'s|\s+is|\s+are)\s+)?(?:the\s+)?(?:differences?|distinctions?|similarit(?:y|ies))\s+(?:between|of)\s+(.{2,140}?)\s+and\s+(.{2,140}?)\s*[?.!]*$',
        r'^compare\s+(.{2,140}?)\s+(?:to|vs\.?|versus|with|and|against)\s+(.{2,140}?)\s*[?.!]*$',
        r'^(?:how\s+(?:does|do)\s+)?(.{2,140}?)\s+(?:compare[sd]?|differs?)\s+(?:to|from|with)\s+(.{2,140}?)\s*[?.!]*$',
        r'^(?:which\s+is\s+better|which\s+one|better)[,:]?\s+(.{2,140}?)\s+or\s+(.{2,140}?)\s*[?.!]*$',
        r'^(?:is\s+|are\s+|should\s+i\s+(?:use|choose)\s+)?(.{2,140}?)\s+(?:vs\.?|versus)\s+(.{2,140}?)\s*[?.!]*$',
        r'^(.{2,60}?)\s+and\s+(.{2,60}?)\s*[?.!]*$')
    for pattern in patterns:
        match = re.match(pattern, text, re.I)
        if match:
            def subject(value):
                value = value.strip(' ?.!,')
                parsed = urlsplit(value)
                return parsed.hostname if parsed.scheme in ('http', 'https') and parsed.hostname else value
            left, right = (subject(part) for part in match.groups())
            if left and right and left.lower() != right.lower():
                return left, right
    return None


def plan(query, history, depth, standalone=None):
    base = standalone or standalone_question(query, history)
    queries = [base]
    if depth == 'deep':
        # The third reserved search is a gap-driven second pass (see gap_query).
        queries.append(base + ' primary sources official documentation evidence')
    elif depth == 'compare':
        # Search each side directly. Repeating the entire comparison question
        # frequently retrieves generic listicles and misses one subject.
        subjects = compare_subjects(query)
        if subjects:
            queries += [side + ' overview key facts official documentation' for side in subjects]
        else:
            queries.append(base + ' comparison differences evidence')
    return queries


def gap_query(query, candidates, judgment, standalone=None):
    """Second-pass search aimed at what the first judgment could not cover."""
    base = standalone or query
    covered = set()
    ids = {str(n) for n in ([judgment.get('selected')] if judgment.get('selected') else []) + list(judgment.get('relevant_ids', []))}
    for candidate in candidates:
        if not ids or candidate['id'] in ids:
            covered |= set(stems(candidate.get('passage', '') + ' ' + candidate.get('title', '')))
    missing = [t for t in tokens(query) if stem(t) not in covered]
    missing = list(dict.fromkeys(missing))[:4]
    if missing:
        return base + ' ' + ' '.join(missing) + ' specifics documentation'
    return base + ' limitations conflicting evidence independent analysis'


def needs_second_pass(judgment):
    return (judgment.get('gate') != 'answer' or judgment.get('sufficiency_probability', 1) < .85
            or len(judgment.get('relevant_ids', [])) < 1)


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
    documents = [Counter(stems(s.get('title', '') + ' ' + s['text'][:3000])) for s in rows]
    terms = set(stems(query))
    preferred = primary_domains(query)
    intent = recency_intent(query)
    mean = sum(sum(d.values()) for d in documents) / max(1, len(documents)) or 1
    for source, words in zip(rows, documents):
        score = 0
        for term in terms:
            count = words[term]
            frequency = sum(term in doc for doc in documents)
            inverse = math.log(1 + (len(rows) - frequency + .5) / (frequency + .5))
            score += inverse * count * 2.2 / (count + 1.2 * (.25 + .75 * sum(words.values()) / mean))
        lexical_relevance = score
        title_terms = set(stems(source.get('title', '')))
        focused_terms = set(stems(source['text'][:800]))
        coverage = len(terms & (title_terms | focused_terms)) / max(1, len(terms))
        provider_score = source.get('provider_score')
        if type(provider_score) not in (int, float) or not math.isfinite(provider_score) or not 0 <= provider_score <= 1:
            provider_score = 0
        score += 1.0 * coverage + .4 * provider_score
        recency = recency_boost(source.get('published_date')) if intent and coverage >= .3 else 0.0
        score += recency
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
        if recency:
            source['ranking_factors']['recency'] = recency
        source['relevance'] = round(score, 4)
    rows.sort(key=lambda s: (-s['relevance'], s.get('url', s.get('note_id', ''))))
    selected, domains, fingerprints = [], Counter(), set()
    for row in rows:
        fingerprint = hashlib.sha256(re.sub(r'\s+', ' ', row['text']).strip().encode()).hexdigest()
        domain = row.get('domain') or 'private'
        if fingerprint in fingerprints or domains[domain] >= 2:
            continue
        text = focus_text(query, row['text'], min(4000, budget))
        if not text:
            break
        fingerprints.add(fingerprint); domains[domain] += 1; budget -= len(text)
        row.update(n=len(selected) + 1, text=text, excerpt=text[:450], fingerprint=fingerprint)
        row['selection_reasons'] = ['lexical relevance', 'query coverage', 'domain diversity']
        if row['ranking_factors']['primary_boost']:
            row['selection_reasons'].append('matched publisher domain')
        if row['ranking_factors']['provider_score']:
            row['selection_reasons'].append('provider score')
        if row['ranking_factors'].get('recency'):
            row['selection_reasons'].append('recent publication')
        if len(row.get('matched_queries', [])) > 1:
            row['selection_reasons'].append('found by multiple queries')
        selected.append(row)
        if len(selected) == limit:
            break
    return selected


def _gather(queries, search):
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
    return results, failed, failure_kinds


def retrieve(query, history, depth, search, standalone=None, seed=None):
    queries = plan(query, history, depth, standalone)
    results, failed, failure_kinds = _gather(queries, search)
    for source in seed or []:
        # Evidence from the parent answer competes on relevance without a new search.
        if isinstance(source, dict) and source.get('url') and isinstance(source.get('text'), str) and source['text'].strip():
            row = {k: v for k, v in source.items() if k not in ('n', 'evidence_span', 'relevance', 'ranking_factors', 'selection_reasons')}
            row['matched_queries'] = ['previous answer']
            results.append(row)
    candidate_urls = list(dict.fromkeys(canonical(row['url']) for row in results if row.get('url')))
    selected = rank(standalone or query, results, limit=8)
    focus = []
    if depth == 'compare' and len(queries) == 3:
        # Put one result from each focused search first so the writer window
        # actually contains both sides of a comparison.
        subjects = compare_subjects(query) or (queries[1], queries[2])
        focused_sources = []
        for focused, side in zip(queries[1:], subjects):
            option = rank(side, [row for row in results if focused in row.get('matched_queries', [])], limit=1)
            if option and canonical(option[0]['url']) not in {canonical(row['url']) for row in focused_sources}:
                focused_sources.append(option[0])
        keys = {canonical(row['url']) for row in focused_sources}
        selected = (focused_sources + [row for row in selected if canonical(row['url']) not in keys])[:8]
        for n, row in enumerate(selected, 1):
            row['n'] = n
        focus = list(range(1, len(focused_sources) + 1))
    report = {'queries': queries, 'search_calls': len(queries),
        'failed_searches': failed, 'search_failure_kinds': dict(failure_kinds),
        'candidate_urls': candidate_urls, 'selected_urls': [row['canonical_url'] for row in selected if row.get('canonical_url')],
        'ranking': 'lexical relevance, source provenance, provider score, deduplication and domain diversity'}
    if focus:
        report['compare_focus'] = focus
    return selected, report


def second_pass(query, sources, extra_query, search, room=3):
    """One extra search; returns (new sources numbered after `sources`, report additions).

    The search is charged even when it fails: the reservation already covers it.
    """
    results, failed, kinds = _gather([extra_query], search)
    known = {canonical(s['url']) for s in sources if s.get('url')}
    fresh = [row for row in results if row.get('url') and canonical(row['url']) not in known]
    added = rank(query, fresh, limit=max(0, min(room, 8 - len(sources))))
    for offset, row in enumerate(added, len(sources) + 1):
        row['n'] = offset
    return added, {'second_pass_query': extra_query, 'second_pass_added': len(added),
                   'failed_searches': failed, 'search_failure_kinds': dict(kinds)}


def missing_terms(query, candidates, judgment):
    """Query words that no selected passage covers (the same signal that drives the second-pass search)."""
    ids = {str(n) for n in ([judgment.get('selected')] if judgment.get('selected') else []) + list(judgment.get('relevant_ids', []))}
    covered = set()
    for candidate in candidates or []:
        if not ids or candidate['id'] in ids:
            covered |= set(stems(candidate.get('passage', '') + ' ' + candidate.get('title', '')))
    return list(dict.fromkeys(t for t in tokens(query) if stem(t) not in covered))[:4]


def _clean_label(text, limit=40):
    text = re.sub(r'[\x00-\x1f\x7f\[\]<>`*_#|]', ' ', str(text or ''))
    text = re.sub(r'https?://\S+', ' ', text)
    return clip_words(re.sub(r'\s+', ' ', text).strip(' -:;,.'), limit)


def suggest_followups(query, mode='standard', report=None, sources=None, missing=(), outcome='answered'):
    """0-3 short follow-up questions. Deterministic, no model call, and never a factual claim.

    outcome: 'answered' | 'abstained' | 'redacted' | 'market'.
    """
    query = re.sub(r'\s+', ' ', str(query or '')).strip()
    sources = [s for s in (sources or []) if isinstance(s, dict)]
    suggestions = []
    if outcome == 'redacted':
        suggestions = ['Ask a differently worded question']
    elif outcome == 'market':
        suggestions = ['How has the price moved over the past week?', 'Show the source and time of this quote']
    else:
        if outcome == 'abstained':
            if mode == 'standard':
                suggestions.append('Search with Deep research')
            elif mode == 'deep':
                suggestions.append('Ask with Compare or a narrower question')
            name = _clean_label((sources[0].get('title') or sources[0].get('domain')) if sources else '')
            if name:
                suggestions.append(f'Narrow to {name}')
        subjects = compare_subjects(query) if mode == 'compare' else None
        if subjects:
            left, right = (_clean_label(x, 30) for x in subjects)
            if outcome == 'answered':
                suggestions += [f'Which is better for my use case: {left} or {right}?', f'How do {left} and {right} differ on cost?']
        elif outcome == 'answered':
            for term in [_clean_label(t, 30) for t in list(missing)[:2]]:
                if term:
                    suggestions.append(f'What about {term}?')
            domains = list(dict.fromkeys(s.get('domain') for s in sources if s.get('domain')))
            if mode in ('scrape', 'crawl'):
                suggestions += ['What are the key facts on this page?' if mode == 'scrape' else 'Which pages cover pricing or contact details?']
            elif domains:
                suggestions.append(f'What does {_clean_label(domains[0], 40)} say in more detail?')
        if outcome == 'answered':
            suggestions += ['Give a shorter version', 'Explain in more detail']
    out = []
    for text in suggestions:
        text = clip_words(re.sub(r'\s+', ' ', text).strip(), 90)
        if text and text.lower() not in {x.lower() for x in out} and text.lower().rstrip('?') != query.lower().rstrip('?'):
            out.append(text)
    return out[:3]
