"""Live grounded answer pipeline. No mock answers or client-supplied evidence."""
import json
import ipaddress
import math
import os
import re
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

import research_store as db

MAX_INPUT_BYTES = 100_000
MAX_EVIDENCE_CHARS = 24_000


class Unavailable(Exception):
    pass


def configuration():
    required = ["ZEARCH_SESSION_SECRET", "TYPESAFE_API_KEY", "TAVILY_API_KEY",
                "ZEARCH_JEV_INPUT_USD_PER_MILLION",
                "OPENAI_API_KEY", "ZEARCH_WRITER_MODEL",
                "ZEARCH_WRITER_OUTPUT_USD_PER_MILLION"]
    # Default rates apply to Tavily basic search and the pinned writer model only.
    if os.environ.get("ZEARCH_WRITER_MODEL") != "gpt-5.4-mini":
        required.append("ZEARCH_WRITER_INPUT_USD_PER_MILLION")
    if os.environ.get('ZEARCH_ENRICHMENT_ENABLED') == '1':
        required += ['ZEARCH_SCRAPE_USD_PER_CALL']
    if os.environ.get("VERCEL"):
        required.append("DATABASE_URL")
    missing = [key for key in required if not os.environ.get(key)]
    if len(os.environ.get("ZEARCH_SESSION_SECRET", "")) < 32:
        missing.append("ZEARCH_SESSION_SECRET (at least 32 characters)")
    if os.environ.get("ZEARCH_RESEARCH_ENABLED") != "1":
        missing.append("ZEARCH_RESEARCH_ENABLED=1")
    return missing


def ready():
    return not configuration()


def rates():
    writer_default = '0.75' if os.environ.get('ZEARCH_WRITER_MODEL') == 'gpt-5.4-mini' else None
    values = [Decimal(os.environ['ZEARCH_JEV_INPUT_USD_PER_MILLION']),
              Decimal(os.environ.get('ZEARCH_SEARCH_USD_PER_CALL') or '0.008'),
              Decimal(os.environ.get('ZEARCH_WRITER_INPUT_USD_PER_MILLION') or writer_default),
              Decimal(os.environ['ZEARCH_WRITER_OUTPUT_USD_PER_MILLION'])]
    if os.environ.get('ZEARCH_ENRICHMENT_ENABLED') == '1':
        values.append(Decimal(os.environ['ZEARCH_SCRAPE_USD_PER_CALL']))
    else:
        values.append(Decimal(0))
    if any(not value.is_finite() or value <= 0 for value in values[:4]) or not values[4].is_finite() or values[4] < 0:
        raise Unavailable('Research pricing configuration is invalid')
    return values


def reservation(depth='standard'):
    jev_rate, search_rate, writer_in, writer_out, scrape_rate = rates()
    # One selection, up to two Jev checks and two bounded drafts.
    provider_credits = 3 if depth == 'crawl' else 1 if depth == 'scrape' else 3 if depth in ('deep', 'compare') else 1
    optional_scrapes = 0 if depth in ('scrape', 'crawl') else 3
    return math.ceil(250_000 * jev_rate + 40_000 * writer_in +
        1800 * writer_out + (search_rate * provider_credits + scrape_rate * optional_scrapes) * 1_000_000)


def limits():
    return {"global_calls": int(os.environ.get("ZEARCH_DAILY_GLOBAL_RUNS", "100")),
            "user_calls": int(os.environ.get("ZEARCH_DAILY_SESSION_RUNS", "10")),
            "global_budget": int(Decimal(os.environ.get("ZEARCH_DAILY_GLOBAL_USD", "10")) * 1_000_000),
            "user_budget": int(Decimal(os.environ.get("ZEARCH_DAILY_SESSION_USD", "1")) * 1_000_000)}


def validate(body):
    if not isinstance(body, dict):
        raise ValueError("Expected a JSON object")
    query = body.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("Enter a question of 1–2000 characters")
    request_id = body.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,80}", request_id):
        raise ValueError("Invalid request identifier")
    parent = body.get("parent_id")
    if parent is not None and (not isinstance(parent, str) or not re.fullmatch(r"[a-f0-9]{32}", parent)):
        raise ValueError("Invalid follow-up identifier")
    depth = body.get('depth', 'standard')
    if depth not in ('standard', 'deep', 'compare', 'scrape', 'crawl') or not isinstance(body.get('use_knowledge', False), bool):
        raise ValueError('Invalid research options')
    if depth in ('scrape', 'crawl'):
        from web_ingest import target
        target(body.get('target_url'))
        if body.get('use_knowledge'):
            raise ValueError('Private notes are not supported in URL collection')
    elif body.get('target_url') is not None:
        raise ValueError('A URL target requires Scrape or Crawl mode')
    return query.strip(), request_id, parent


def safe_url(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 32 for c in url):
        return None
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
            return None
        if p.port not in (None, 80, 443) or p.hostname.lower() in ('localhost', 'metadata.google.internal') or p.hostname.lower().endswith(('.local', '.internal')):
            return None
        try:
            if not ipaddress.ip_address(p.hostname).is_global:
                return None
        except ValueError:
            pass
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))
    except ValueError:
        return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def open_provider(url, payload, key, timeout=20):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json",
        "User-Agent": "Zearch/1.0"})
    # Credentials are sent only to fixed provider endpoints and never redirected.
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)


def _post_search(payload):
    with open_provider("https://api.tavily.com/search", payload, os.environ["TAVILY_API_KEY"]) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise Unavailable("Search response exceeded its size limit")
        return json.loads(raw)


def search(query):
    import retrieval
    from provenance import publication_date
    payload = {"query": query[:4000], "search_depth": "basic", "max_results": 8,
               "include_answer": False, "include_raw_content": "text",
               "include_published_date": True}
    preferred = retrieval.primary_domains(query)
    if preferred:
        payload.update(include_domains=preferred, include_domains_mode='prefer')
    # Provider assumption (unverified offline): `topic` and `time_range` are
    # honored by /search. They are sent only for explicit news intent, and a
    # provider rejection retries once without them.
    extras = {}
    if retrieval.recency_intent(query) == 'news':
        extras = {'topic': 'news', 'time_range': retrieval.news_time_range(query)}
    try:
        data = _post_search(dict(payload, **extras))
    except urllib.error.HTTPError as exc:
        if not extras or exc.code not in (400, 422):
            raise
        data = _post_search(payload)
    sources, seen, remaining = [], set(), MAX_EVIDENCE_CHARS
    for row in data.get("results", []):
        if not isinstance(row, dict):
            continue
        url = safe_url(row.get("url"))
        snippet = row.get("content") or ""
        raw_content = row.get("raw_content") or ""
        # The provider's focused snippet often contains the answer while page
        # extraction begins with navigation, cookie banners, and unrelated text.
        content = (snippet + "\n" + raw_content) if isinstance(snippet, str) and isinstance(raw_content, str) else ""
        if not url or url in seen or not isinstance(content, str) or not content.strip():
            continue
        seen.add(url)
        text = retrieval.focus_text(query, content, min(6000, remaining))
        if not text:
            break
        remaining -= len(text)
        captured_at = int(time.time())
        published = publication_date(row.get('published_date'), captured_at)
        provenance = "provider_metadata" if published else "unknown"
        if not published:
            published = retrieval.text_date(text, captured_at)
            provenance = "page_text" if published else "unknown"
        sources.append({"n": len(sources) + 1, "url": url,
                        "title": str(row.get("title") or url)[:300],
                        "domain": urllib.parse.urlsplit(url).hostname,
                        "text": text, "excerpt": text[:450],
                        "retrieved_at": captured_at,
                        "published_date": published,
                        "retrieval_provider": "tavily",
                        "published_date_provenance": provenance,
                        "provider_score": row.get('score'),
                        "content_type": "page" if row.get("raw_content") else "snippet"})
        if len(sources) == 8:
            break
    if not sources:
        raise Unavailable("No usable sources were returned. Try a more specific question.")
    return sources


def estimate(usage):
    jev_rate, search_rate, writer_in, writer_out, scrape_rate = rates()
    tokens = usage.get('input_tokens')
    calls = usage.get('search_calls', 1)
    extracts, crawls = usage.get('extract_calls', 0), usage.get('crawl_calls', 0)
    if type(tokens) is not int or tokens < 0 or type(calls) is not int or calls < 0 or calls > 3:
        return None
    if type(extracts) is not int or type(crawls) is not int or not 0 <= extracts <= 1 or not 0 <= crawls <= 1 or extracts + crawls > 1:
        return None
    writer = usage.get('writer') or {}
    wi, wo, scrape = writer.get('input_tokens', 0), writer.get('output_tokens', 0), usage.get('scrape_calls', 0)
    if any(type(n) is not int or n < 0 for n in (wi, wo, scrape)) or scrape > 3:
        return None
    return math.ceil(tokens * jev_rate + wi * writer_in + wo * writer_out +
                     ((calls + extracts + 2 * crawls) * search_rate + scrape * scrape_rate) * 1_000_000)


def prepare(owner, body):
    query, request_id, parent = validate(body)
    target_url = None
    if body.get('depth') in ('scrape', 'crawl'):
        from web_ingest import target
        target_url = target(body['target_url'])
    if not ready():
        raise Unavailable("Live research is being configured. Please check back shortly.")
    history = db.context(owner, parent)
    record, fresh = db.reserve(owner, uuid.uuid4().hex, request_id, query, parent,
                               os.environ.get("JEV_MODEL", "jev-latest"), reservation(body.get("depth", "standard")), limits(),
                               body.get("depth", "standard"), body.get("use_knowledge", False),
                               target_url)
    return record, fresh, history


def run(owner, record, history):
    rid, query = record["id"], record["query"]
    answer, sources, usage = "", [], {'stage_ms': {}}
    started = time.monotonic()
    current_stage = 'initialization'
    def measured(name, action, *args):
        nonlocal current_stage
        current_stage = name
        start = time.monotonic()
        try:
            return action(*args)
        finally:
            usage['stage_ms'][name] = round((time.monotonic() - start) * 1000)
    def finish_metrics():
        usage['total_ms'] = round((time.monotonic() - started) * 1000)
    finalized = False
    try:
        yield {"type": "start", "id": rid}
        import market_data
        mode = record.get('depth', 'standard')
        quote_symbol = market_data.quote_symbol(query) if mode in ('standard', 'deep') else None
        if quote_symbol:
            yield {'type': 'status', 'text': 'Checking the live market quote'}
            try:
                source, answer = measured('market_quote', market_data.quote, quote_symbol)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise Unavailable(f'A fresh {quote_symbol}-USD quote is unavailable. Please try again shortly.') from exc
            sources = [source]
            import source_store
            sources, removed = source_store.excluded(sources)
            if removed:
                raise Unavailable('This market source is unavailable.')
            source['source_version_id'] = source_store.version_id(source)
            usage.update({'input_tokens': 0, 'search_calls': 0, 'market_data': f'Coinbase Exchange {quote_symbol}-USD last trade',
                          'answer_format': 'validated_market_quote'})
            db.save(owner, rid, status='streaming', sources=sources)
            yield {'type': 'research', 'report': {'queries': [], 'search_calls': 0,
                   'ranking': 'fresh structured Coinbase Exchange ticker'}}
            yield {'type': 'sources', 'sources': sources}
            yield {'type': 'delta', 'text': answer}
            finish_metrics()
            db.save(owner, rid, status='complete', answer=answer, sources=sources,
                    usage=usage, estimated_cost=estimate(usage))
            finalized = True
            yield {'type': 'complete', 'run': db.get_run(owner, rid)}
            return
        import retrieval
        parent, standalone, seed = None, query, []
        if record.get('parent_id') and history:
            try:
                parent = db.get_run(owner, record['parent_id'])
            except Exception:
                parent = None
            titles = [str(x.get('title') or '') for x in ((parent or {}).get('sources') or [])[:2] if isinstance(x, dict)]
            standalone = retrieval.standalone_question(query, history, titles)
            if standalone != query and mode in ('standard', 'deep', 'compare'):
                seed = [x for x in ((parent or {}).get('sources') or [])[:3]
                        if isinstance(x, dict) and x.get('url') and not x.get('market')]
        followup = {'standalone': standalone, 'today': time.strftime('%Y-%m-%d', time.gmtime())}
        previous = next((m['content'] for m in reversed(history or []) if m.get('role') == 'assistant'), '')
        if previous:
            followup['previous'] = retrieval.clip_words(re.sub(r'\s+', ' ', re.sub(r'\[\d+\]', '', previous)), 300)
        if standalone != query:
            usage['standalone_question'] = standalone
        if mode in ('scrape', 'crawl'):
            yield {'type': 'status', 'text': 'Reading the page' if mode == 'scrape' else 'Crawling up to five pages'}
            import web_ingest
            sources, report = measured('retrieval', web_ingest.collect, record['target_url'], mode, query)
        else:
            yield {"type": "status", "text": "Searching the web"}
            sources, report = measured('retrieval', retrieval.retrieve, query, history, mode, search, standalone, seed)
        import source_store
        sources, removed = source_store.excluded(sources)
        report['tombstoned_sources'] = removed
        if removed:
            from retrieval import canonical
            allowed_urls = {source['canonical_url'] for source in sources if source.get('canonical_url')}
            for field in ('candidate_urls', 'selected_urls'):
                report[field] = [url for url in report.get(field, []) if canonical(url) in allowed_urls]
        usage.update(report)
        if record.get('use_knowledge'):
            import workspace_store
            private = measured('private_knowledge', workspace_store.knowledge, owner, standalone)
            # Keep selected private snippets separate from public web retrieval;
            # only trim the web results when private snippets need the room.
            if private:
                sources = sources[:6] + private[:2]
            for n, source in enumerate(sources, 1):
                source['n'] = n
        if not sources:
            raise Unavailable('No usable evidence was found. Try a more specific question.')
        yield {'type': 'status', 'text': 'Reading sources'}
        import enrichment
        sources, enrich_report = measured('enrichment', enrichment.enrich, sources, standalone) if mode not in ('scrape', 'crawl') else (
            sources, {'scrape_calls': 0, 'enriched_pages': 0, 'cache_hits': 0, 'cache_errors': 0})
        for source in sources:
            source.setdefault('source_version_id', source_store.version_id(source))
        usage.update(enrich_report)
        report.update(enrich_report)
        yield {'type': 'research', 'report': report}
        db.save(owner, rid, status="streaming", sources=sources)
        yield {"type": "sources", "sources": sources}
        yield {'type': 'status', 'text': 'Jev is judging the evidence'}
        import jev_research
        judgment, selected, model_usage, candidates = measured('jev_selection', jev_research.judge, standalone, sources, mode)
        def apply_spans(found):
            by_number = {source['n']: source for source in sources}
            for candidate in found:
                source = by_number.get(int(candidate['id']))
                if source is not None:
                    source['evidence_span'] = [candidate['span_start'], candidate['span_end']]
                    source['excerpt'] = candidate['passage']
        apply_spans(candidates)
        db.save(owner, rid, status='streaming', sources=sources)
        yield {'type': 'sources', 'sources': sources}
        usage['input_tokens'] = model_usage.get('input_tokens', 0)
        if model_usage.get('estimated'):
            usage['usage_estimated'] = True
        if mode == 'deep' and retrieval.needs_second_pass(judgment):
            # One gap-driven search inside the already reserved third provider call.
            yield {'type': 'status', 'text': 'Looking for what is missing'}
            extra = retrieval.gap_query(query, candidates, judgment, standalone)
            added, extra_report = measured('second_pass', retrieval.second_pass, standalone, sources, extra, search)
            usage['search_calls'] = min(3, usage.get('search_calls', 1) + 1)
            usage['second_pass'] = extra_report
            if added:
                sources = sources + added
                sources, removed = source_store.excluded(sources)
                for source in sources:
                    source.setdefault('source_version_id', source_store.version_id(source))
                db.save(owner, rid, status='streaming', sources=sources)
                yield {'type': 'sources', 'sources': sources}
                yield {'type': 'status', 'text': 'Jev is judging the evidence'}
                judgment, selected, model_usage, candidates = measured('jev_reselection', jev_research.judge, standalone, sources, mode)
                apply_spans(candidates)
                db.save(owner, rid, status='streaming', sources=sources)
                yield {'type': 'sources', 'sources': sources}
                usage['input_tokens'] += model_usage.get('input_tokens', 0)
                if model_usage.get('estimated'):
                    usage['usage_estimated'] = True
        usage['judgment'] = judgment
        answer = jev_research.format_answer(judgment, selected, candidates, sources, standalone)
        usage['answer_format'] = 'jev_selected_excerpt'
        # A short selected passage can fail Jev's first sufficiency gate
        # even when the full retrieved snippets support a concise answer. Let
        # the writer try those sources, but publish only after Jev verifies its
        # actual paragraphs against the cited full evidence.
        wide = 6 if mode == 'deep' else 4
        if judgment['gate'] == 'answer':
            draft_ids = judgment['evidence_ids']
        elif judgment['gate'] in ('abstain', 'review'):
            draft_ids = (([judgment['selected']] if judgment.get('selected') else []) +
                         [n for n in judgment.get('relevant_ids', []) if n != judgment.get('selected')])[:wide]
            if not draft_ids:
                draft_ids = [source['n'] for source in sources[:wide]]
        else:
            draft_ids = []
        if mode == 'compare' and draft_ids:
            # The focused per-side sources come first so Jev's single pick
            # cannot evict one side of the comparison from the four-source window.
            existing = {source['n'] for source in sources}
            focus = [n for n in report.get('compare_focus', []) if n in existing] or [source['n'] for source in sources[:2]]
            draft_ids = list(dict.fromkeys(focus + draft_ids + [source['n'] for source in sources[:4]]))[:4]
        if draft_ids:
            yield {'type': 'status', 'text': 'Writing from selected evidence'}
            import writer
            import answer_contract
            try:
                try:
                    draft, writer_usage = measured('writer', writer.compose, query, sources, draft_ids, mode, False, followup)
                    usage['writer_attempts'] = 1
                except writer.WriterError:
                    # Transient provider or format failure: retry once with the reserved second draft.
                    yield {'type': 'status', 'text': 'Retrying the draft'}
                    usage['writer_failed_attempts'] = 1
                    draft, writer_usage = measured('writer_retry', writer.compose, query, sources, draft_ids, mode, False, followup)
                    usage['writer_attempts'] = 2
                usage['writer'] = writer_usage
                yield {'type': 'status', 'text': 'Jev is checking the draft'}
                approved, check, check_usage = measured('jev_verification', jev_research.verify, standalone, draft, sources, draft_ids, wide if mode == 'deep' else 4)
                usage['input_tokens'] += check_usage.get('input_tokens', 0)
                usage['draft_check'] = check
                limit = 6 if mode == 'deep' else 4
                if not approved and mode in ('standard', 'deep', 'compare') and usage['writer_attempts'] < 2 and not jev_research.supported_prefix(draft, check, limit):
                    # One bounded revision. The revised text is checked again
                    # against the same captured sources before it can be shown.
                    yield {'type': 'status', 'text': 'Rechecking a shorter answer'}
                    try:
                        parts = answer_contract.units(draft, limit)
                        rejected = [parts[i] for i in jev_research.failing_units(draft, check, limit) if i < len(parts)]
                    except ValueError:
                        rejected = []
                    try:
                        revised, revised_usage = measured('writer_revision', writer.compose,
                            query, sources, draft_ids, mode, True, followup, rejected)
                        usage['writer_attempts'] = 2
                        usage['writer'] = {
                            'input_tokens': writer_usage.get('input_tokens', 0) + revised_usage.get('input_tokens', 0),
                            'output_tokens': writer_usage.get('output_tokens', 0) + revised_usage.get('output_tokens', 0),
                            'model': revised_usage.get('model', writer_usage.get('model'))}
                        revised_ok, revised_check, revised_cost = measured('jev_recheck',
                            jev_research.verify, standalone, revised, sources, draft_ids, limit)
                        usage['input_tokens'] += revised_cost.get('input_tokens', 0)
                        usage['revision_check'] = revised_check
                        if revised_ok:
                            approved, draft, check = True, revised, revised_check
                            usage['draft_check'] = revised_check
                    except (writer.WriterError, jev_research.JevError):
                        usage['revision_failed'] = True
                if approved:
                    answer = draft
                    usage['answer_format'] = 'jev_verified_prose'
                    usage['draft_source_ids'] = draft_ids
                else:
                    usage['draft_rejected'] = True
                    usage['draft_fallback_reason'] = 'unsupported_draft'
                    supported = jev_research.supported_prefix(draft, check, limit)
                    if supported:
                        answer = supported
                        usage['answer_format'] = 'jev_verified_partial_prose'
                        usage['draft_source_ids'] = draft_ids
            except (writer.WriterError, jev_research.JevError) as exc:
                usage['draft_rejected'] = True
                usage['draft_fallback_reason'] = 'writer_error' if isinstance(exc, writer.WriterError) else 'verification_error'
        if mode in ('scrape', 'crawl') and (judgment['gate'] == 'abstain'
                or judgment['gate'] == 'review') and usage['answer_format'] == 'jev_selected_excerpt':
            answer = jev_research.captured_overview(candidates, sources)
            if judgment['gate'] == 'review':
                answer += '\n\nThe captured pages may disagree on a needed fact. Check the sources before relying on these excerpts.'
            usage['answer_format'] = 'captured_excerpts'
        _, removed = source_store.excluded(sources)
        if removed:
            answer = 'This answer is unavailable because a source was removed.'
            sources = []
            usage = {'redacted_source': True}
        yield {'type': 'delta', 'text': answer}
        finish_metrics()
        cost = estimate(usage)
        db.save(owner, rid, status="complete", answer=answer, sources=sources, usage=usage, estimated_cost=cost)
        finalized = True
        yield {"type": "complete", "run": db.get_run(owner, rid)}
    except GeneratorExit:
        if not finalized:
            usage['failure_stage'] = current_stage
            usage['failure_kind'] = 'disconnected'
            finish_metrics()
            db.save(owner, rid, status="interrupted", answer=answer, sources=sources, usage=usage, error="Connection closed")
        raise
    except Exception as exc:
        usage['failure_stage'] = current_stage
        usage['failure_kind'] = type(exc).__name__
        finish_metrics()
        message = str(exc) if isinstance(exc, (Unavailable, ValueError)) or type(exc).__name__ == "JevError" else "Research could not finish. Please try again."
        db.save(owner, rid, status="error", answer=answer, sources=sources, usage=usage, error=message)
        yield {"type": "error", "id": rid, "error": message}
