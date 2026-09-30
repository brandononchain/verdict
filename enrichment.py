"""Optional bounded page extraction; search snippets remain usable on provider failure."""
import hashlib
import os
import time

from research import safe_url
from retrieval import clip_words, focus_text
from web_ingest import _request
import source_store

MAX_PAGES = 3


def extract(url):
    data = _request('extract', {'urls': url, 'extract_depth': 'basic', 'format': 'markdown'})
    results = data.get('results') or []
    row = results[0] if results and isinstance(results[0], dict) else {}
    content = row.get('raw_content')
    if not isinstance(content, str) or len(content.strip()) < 100:
        raise ValueError('Extraction did not contain useful page text')
    # The caller windows the page around the question; keep enough to choose from.
    return content[:60_000], {'title': row.get('title'), 'description': row.get('description')}


def enrich(sources, query=''):
    if os.environ.get('ZEARCH_ENRICHMENT_ENABLED') != '1':
        return sources, {'scrape_calls': 0, 'enriched_pages': 0, 'cache_hits': 0, 'cache_errors': 0}
    calls = improved = cache_hits = cache_errors = 0
    for source in sources[:MAX_PAGES]:
        if source.get('note_id') or not safe_url(source.get('url')):
            continue
        try:
            cached = source_store.lookup(source['url'])
            if cached:
                source_store.apply_hit(source, cached)
                cache_hits += 1
                continue
        except Exception:
            # The optional shared cache never blocks a fresh provider attempt.
            cache_errors += 1
        calls += 1
        try:
            content, metadata = extract(source['url'])
            # Keep the provider's focused snippet: it often holds the answer while
            # the extracted page starts with navigation and boilerplate.
            original = source.get('text') or ''
            snippet = clip_words(original.split('\n', 1)[0], 600) if original.strip() else ''
            combined = content if not snippet or snippet[:80] in content else snippet + '\n' + content
            source['retrieved_at'] = int(time.time())
            generic = content[:4000]
            source['text'] = focus_text(query, combined, 4000) if query else generic
            source['excerpt'] = source['text'][:450]
            source['content_type'] = 'extracted_page'
            source['fingerprint'] = hashlib.sha256(source['text'].encode()).hexdigest()
            title = metadata.get('title')
            if isinstance(title, str) and title.strip():
                source['title'] = title[:300]
            description = metadata.get('description')
            if isinstance(description, str):
                source['description'] = description[:500]
            try:
                # The shared cache stores a question-independent window.
                source_store.save(dict(source, text=generic))
            except Exception:
                cache_errors += 1
            improved += 1
        except (OSError, ValueError, KeyError, TypeError):
            # A failed extraction never replaces the original searchable snippet.
            pass
    return sources, {'scrape_calls': calls, 'enriched_pages': improved,
                     'cache_hits': cache_hits, 'cache_errors': cache_errors}
