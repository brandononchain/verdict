"""Bounded, public-URL extract and same-host crawl through the existing Tavily key."""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urljoin

from research import Unavailable, open_provider, safe_url
from retrieval import canonical, focus_text

MAX_PAGES = 5
MAX_RESPONSE = 2_000_000
UTILITY_PATH = re.compile(r'^/(?:status|incidents?|uptime|changelog|privacy|terms|legal)(?:/|$)', re.I)
IMAGE_LINK = re.compile(r'!\[([^\]]{0,160})\]\(([^)\s]+)(?:\s+[^)]*)?\)')
MARKDOWN_LINK = re.compile(r'\[[^\]]{0,160}\]\(([^)\s]+)(?:\s+[^)]*)?\)')
EMAIL = re.compile(r'(?<![\w.])([a-zA-Z0-9._%+-]{1,64}@[a-zA-Z0-9.-]{1,190}\.[a-zA-Z]{2,24})(?!\w)')


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


def assets(row, content, page_url):
    """Collect bounded public references from provider output; never download assets."""
    found, seen = [], set()
    def add(value, kind, label=''):
        if not isinstance(value, str):
            return
        candidate = safe_url(urljoin(page_url, value))
        if not candidate or urlsplit(candidate).scheme != 'https' or candidate in seen or len(found) >= 32:
            return
        seen.add(candidate)
        found.append({'kind': kind, 'url': candidate, 'label': label[:120]})
    favicon = row.get('favicon')
    add(favicon, 'favicon', 'Site icon')
    for value in row.get('images', [])[:24] if isinstance(row.get('images'), list) else []:
        if isinstance(value, dict):
            add(value.get('url'), 'image', str(value.get('description') or value.get('alt') or ''))
        else:
            add(value, 'image')
    for alt, link in IMAGE_LINK.findall(content):
        add(link, 'logo' if re.search(r'logo|brand|mark', alt + ' ' + link, re.I) else 'image', alt)
    for link in MARKDOWN_LINK.findall(content):
        if re.search(r'(?:youtube\.com|youtu\.be|vimeo\.com|\.(?:mp4|webm|mov)(?:\?|$))', link, re.I):
            add(link, 'video')
    emails = list(dict.fromkeys(email.lower() for email in EMAIL.findall(content)))[:20]
    metadata = row.get('metadata') if isinstance(row.get('metadata'), dict) else {}
    description = row.get('description') or metadata.get('description')
    return found, emails, str(description or '')[:500]


def collect(url, mode, query=''):
    clean = target(url)
    extract_payload = {'urls': clean, 'extract_depth': 'basic', 'format': 'markdown',
                       'include_images': True, 'include_favicon': True, 'include_usage': True}
    if mode == 'scrape':
        data = _request('extract', extract_payload)
    elif mode == 'crawl':
        broad = (urlsplit(clean).path in ('', '/') and
                 bool(re.search(r'\b(summarize|overview|main topics|site)\b', query, re.I)) and
                 not re.search(r'\b(status|incident|uptime|outage|privacy|legal|terms)\b', query, re.I))
        crawl_payload = {'url': clean, 'max_depth': 1, 'max_breadth': 6,
                                 'limit': MAX_PAGES, 'allow_external': False,
                                 'select_domains': ['^' + re.escape(urlsplit(clean).hostname) + '$'],
                                 **({'exclude_paths': [UTILITY_PATH.pattern]} if broad else {}),
                                 'extract_depth': 'basic', 'format': 'markdown',
                                 'include_images': True, 'include_favicon': True, 'include_usage': True}
        with ThreadPoolExecutor(max_workers=2) as pool:
            home_future = pool.submit(_request, 'extract', extract_payload)
            crawl_future = pool.submit(_request, 'crawl', crawl_payload)
            try:
                home = home_future.result()
            except (OSError, ValueError, Unavailable):
                home = {'results': [], 'failed_results': [{'url': clean}]}
            try:
                data = crawl_future.result()
            except (OSError, ValueError, Unavailable):
                data = {'results': [], 'failed_results': [{'url': clean}]}
        data['results'] = home['results'][:1] + data['results']
        data['failed_results'] = (home.get('failed_results') or []) + (data.get('failed_results') or [])
    else:
        raise ValueError('Invalid collection mode')
    host = urlsplit(clean).hostname
    sources, seen = [], set()
    for row in data['results']:
        if not isinstance(row, dict):
            continue
        page_url = safe_url(row.get('url'))
        if not page_url or urlsplit(page_url).scheme != 'https':
            continue
        if mode == 'scrape' and canonical(page_url) != canonical(clean):
            continue
        if mode == 'crawl' and urlsplit(page_url).hostname != host:
            continue
        if mode == 'crawl' and broad and UTILITY_PATH.match(urlsplit(page_url).path):
            continue
        key = canonical(page_url)
        content = row.get('raw_content')
        if key in seen or not isinstance(content, str) or len(content.strip()) < 40:
            continue
        seen.add(key)
        media, emails, description = assets(row, content[:20_000], page_url)
        content = focus_text(query, IMAGE_LINK.sub('', content[:40_000]), 4000)
        if len(content.strip()) < 40:
            continue
        sources.append({'n': len(sources) + 1, 'url': page_url, 'canonical_url': key,
                        'title': str(row.get('title') or urlsplit(page_url).path.strip('/') or host)[:300],
                        'domain': host, 'text': content, 'excerpt': content[:450],
                        'retrieved_at': int(time.time()), 'content_type': 'extracted_page',
                        'retrieval_provider': 'tavily_extract' if mode == 'scrape' else 'tavily_crawl',
                        'published_date_provenance': 'unknown', 'source_tier': 'web',
                        'description': description, 'assets': media, 'emails': emails})
        if len(sources) == MAX_PAGES:
            break
    if not sources:
        raise Unavailable('No usable public page content was returned for this URL')
    report = {'queries': [], 'search_calls': 0, 'extract_calls': 1,
              'crawl_calls': int(mode == 'crawl'), 'crawl_pages': len(sources) if mode == 'crawl' else 0,
              'failed_pages': len(data.get('failed_results') or []),
              'candidate_urls': [source['canonical_url'] for source in sources],
              'selected_urls': [source['canonical_url'] for source in sources],
              'ranking': f'bounded {mode} of a public HTTPS URL; Jev selects evidence from captured pages'}
    return sources, report
