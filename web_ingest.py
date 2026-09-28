"""Bounded, public-URL extract and same-host crawl through the existing Tavily key."""
import json
import os
import re
import time
from urllib.parse import urlsplit

from research import Unavailable, open_provider, safe_url
from retrieval import canonical

MAX_PAGES = 5
MAX_RESPONSE = 1_000_000


def target(url):
    clean = safe_url(url)
    if not clean or urlsplit(clean).scheme != 'https':
        raise ValueError('Enter a public HTTPS page URL')
    host = urlsplit(clean).hostname or ''
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', host):
        raise ValueError('Enter a public HTTPS page URL')
    # Provider-side fetching is used; Zearch never sends user URLs to its own HTTP client.
    return clean


def _request(endpoint, payload):
    with open_provider('https://api.tavily.com/' + endpoint, payload,
                       os.environ['TAVILY_API_KEY'], timeout=55 if endpoint == 'crawl' else 25) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise Unavailable('The page extraction exceeded its response limit')
    result = json.loads(raw)
    if not isinstance(result, dict) or not isinstance(result.get('results'), list):
        raise Unavailable('The extraction provider returned an invalid response')
    return result


def collect(url, mode):
    clean = target(url)
    if mode == 'scrape':
        data = _request('extract', {'urls': clean, 'extract_depth': 'basic',
                                   'format': 'markdown', 'include_usage': True})
    elif mode == 'crawl':
        data = _request('crawl', {'url': clean, 'max_depth': 1, 'max_breadth': 4,
                                 'limit': MAX_PAGES, 'allow_external': False,
                                 'select_domains': ['^' + re.escape(urlsplit(clean).hostname) + '$'],
                                 'extract_depth': 'basic', 'format': 'markdown',
                                 'include_images': False, 'include_usage': True})
    else:
        raise ValueError('Invalid collection mode')
    host = urlsplit(clean).hostname
    sources, seen = [], set()
    for row in data['results'][:MAX_PAGES]:
        if not isinstance(row, dict):
            continue
        page_url = safe_url(row.get('url'))
        if not page_url or urlsplit(page_url).scheme != 'https':
            continue
        if mode == 'scrape' and canonical(page_url) != canonical(clean):
            continue
        if mode == 'crawl' and urlsplit(page_url).hostname != host:
            continue
        key = canonical(page_url)
        content = row.get('raw_content')
        if key in seen or not isinstance(content, str) or len(content.strip()) < 40:
            continue
        seen.add(key)
        content = content[:4000]
        sources.append({'n': len(sources) + 1, 'url': page_url, 'canonical_url': key,
                        'title': str(row.get('title') or urlsplit(page_url).path.strip('/') or host)[:300],
                        'domain': host, 'text': content, 'excerpt': content[:450],
                        'retrieved_at': int(time.time()), 'content_type': 'extracted_page',
                        'retrieval_provider': 'tavily_extract' if mode == 'scrape' else 'tavily_crawl',
                        'published_date_provenance': 'unknown', 'source_tier': 'web'})
    if not sources:
        raise Unavailable('No usable public page content was returned for this URL')
    report = {'queries': [], 'search_calls': 0, 'extract_calls': int(mode == 'scrape'),
              'crawl_calls': int(mode == 'crawl'), 'crawl_pages': len(sources) if mode == 'crawl' else 0,
              'failed_pages': len(data.get('failed_results') or []),
              'candidate_urls': [source['canonical_url'] for source in sources],
              'selected_urls': [source['canonical_url'] for source in sources],
              'ranking': f'bounded {mode} of a public HTTPS URL; Jev selects evidence from captured pages'}
    return sources, report
