"""Optional bounded page extraction; search snippets remain usable on provider failure."""
import hashlib
import json
import os
import time

from research import open_provider, safe_url
import source_store

MAX_PAGES = 3


def enrich(sources):
    if os.environ.get('ZEARCH_ENRICHMENT_ENABLED') != '1':
        return sources, {'scrape_calls': 0, 'enriched_pages': 0, 'cache_hits': 0, 'cache_errors': 0}
    key = os.environ['CONTEXT_DEV_API_KEY']
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
            with open_provider('https://api.context.dev/v1/web/scrape', {
                'url': source['url'], 'formats': {'markdown': True},
                'sharedParams': {'mainContentOnly': True}}, key, timeout=15) as response:
                raw = response.read(500_001)
            if len(raw) > 500_000:
                continue
            data = json.loads(raw)
            markdown = data.get('markdown') or {}
            content = markdown.get('data') if isinstance(markdown, dict) else None
            if not isinstance(content, str) or len(content.strip()) < 100:
                continue
            metadata = data.get('metadata') or {}
            source['text'] = content[:4000]
            source['excerpt'] = source['text'][:450]
            source['content_type'] = 'extracted_page'
            source['retrieved_at'] = int(time.time())
            source['fingerprint'] = hashlib.sha256(source['text'].encode()).hexdigest()
            if isinstance(metadata, dict):
                title = metadata.get('title')
                if isinstance(title, str) and title.strip():
                    source['title'] = title[:300]
                description = metadata.get('description')
                if isinstance(description, str):
                    source['description'] = description[:500]
            try:
                source_store.save(source)
            except Exception:
                cache_errors += 1
            improved += 1
        except (OSError, ValueError, KeyError, TypeError):
            # A failed extraction never replaces the original searchable snippet.
            pass
    return sources, {'scrape_calls': calls, 'enriched_pages': improved,
                     'cache_hits': cache_hits, 'cache_errors': cache_errors}
