"""Live grounded answer pipeline. No mock answers or client-supplied evidence."""
import json
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
                "ZEARCH_JEV_INPUT_USD_PER_MILLION", "ZEARCH_SEARCH_USD_PER_CALL"]
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
    values = [Decimal(os.environ[key]) for key in (
        'ZEARCH_JEV_INPUT_USD_PER_MILLION', 'ZEARCH_SEARCH_USD_PER_CALL')]
    if any(not value.is_finite() or value <= 0 for value in values):
        raise Unavailable('Research pricing configuration is invalid')
    return values


def reservation(depth='standard'):
    jev_rate, search_rate = rates()
    return math.ceil(MAX_INPUT_BYTES * jev_rate + search_rate *
        (3 if depth == 'deep' else 1) * 1_000_000)


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
    if body.get('depth', 'standard') not in ('standard', 'deep') or not isinstance(body.get('use_knowledge', False), bool):
        raise ValueError('Invalid research options')
    return query.strip(), request_id, parent


def safe_url(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 32 for c in url):
        return None
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
            return None
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


def search(query):
    with open_provider("https://api.tavily.com/search", {
        "query": query[:4000], "search_depth": "basic", "max_results": 6,
        "include_answer": False, "include_raw_content": "text",
    }, os.environ["TAVILY_API_KEY"]) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise Unavailable("Search response exceeded its size limit")
        data = json.loads(raw)
    sources, seen, remaining = [], set(), MAX_EVIDENCE_CHARS
    for row in data.get("results", []):
        if not isinstance(row, dict):
            continue
        url = safe_url(row.get("url"))
        content = row.get("raw_content") or row.get("content") or ""
        if not url or url in seen or not isinstance(content, str) or not content.strip():
            continue
        seen.add(url)
        text = content[:min(6000, remaining)]
        if not text:
            break
        remaining -= len(text)
        sources.append({"n": len(sources) + 1, "url": url,
                        "title": str(row.get("title") or url)[:300],
                        "domain": urllib.parse.urlsplit(url).hostname,
                        "text": text, "excerpt": text[:450],
                        "retrieved_at": int(time.time()),
                        "content_type": "page" if row.get("raw_content") else "snippet"})
        if len(sources) == 6:
            break
    if not sources:
        raise Unavailable("No usable sources were returned. Try a more specific question.")
    return sources


def estimate(usage):
    jev_rate, search_rate = rates()
    tokens = usage.get('input_tokens')
    calls = usage.get('search_calls', 1)
    if type(tokens) is not int or tokens < 0 or type(calls) is not int or calls < 1 or calls > 3:
        return None
    return math.ceil(tokens * jev_rate + calls * search_rate * 1_000_000)


def prepare(owner, body):
    query, request_id, parent = validate(body)
    if not ready():
        raise Unavailable("Live research is being configured. Please check back shortly.")
    history = db.context(owner, parent)
    record, fresh = db.reserve(owner, uuid.uuid4().hex, request_id, query, parent,
                               os.environ.get("JEV_MODEL", "jev-latest"), reservation(body.get("depth", "standard")), limits(),
                               body.get("depth", "standard"), body.get("use_knowledge", False))
    return record, fresh, history


def run(owner, record, history):
    rid, query = record["id"], record["query"]
    answer, sources, usage = "", [], {}
    finalized = False
    try:
        yield {"type": "start", "id": rid}
        yield {"type": "status", "text": "Searching the web"}
        import retrieval
        sources, report = retrieval.retrieve(query, history, record.get('depth', 'standard'), search)
        usage.update(report)
        if record.get('use_knowledge'):
            import workspace_store
            private = workspace_store.knowledge(owner, query)
            # Keep selected private snippets separate from public web retrieval.
            sources = sources[:6] + private[:2]
            for n, source in enumerate(sources, 1):
                source['n'] = n
        if not sources:
            raise Unavailable('No usable evidence was found. Try a more specific question.')
        yield {'type': 'research', 'report': report}
        db.save(owner, rid, status="streaming", sources=sources)
        yield {"type": "sources", "sources": sources}
        yield {'type': 'status', 'text': 'Jev is judging the evidence'}
        import jev_research
        judgment, selected, model_usage, candidates = jev_research.judge(query, sources)
        usage.update(model_usage)
        usage['judgment'] = judgment
        usage['answer_format'] = 'source_excerpt_selected_by_jev'
        answer = jev_research.format_answer(judgment, selected, candidates, sources)
        yield {'type': 'delta', 'text': answer}
        cost = estimate(usage)
        db.save(owner, rid, status="complete", answer=answer, sources=sources, usage=usage, estimated_cost=cost)
        finalized = True
        yield {"type": "complete", "run": db.get_run(owner, rid)}
    except GeneratorExit:
        if not finalized:
            db.save(owner, rid, status="interrupted", answer=answer, sources=sources, usage=usage, error="Connection closed")
        raise
    except Exception as exc:
        message = str(exc) if isinstance(exc, (Unavailable, ValueError)) or type(exc).__name__ == "JevError" else "Research could not finish. Please try again."
        db.save(owner, rid, status="error", answer=answer, sources=sources, usage=usage, error=message)
        yield {"type": "error", "id": rid, "error": message}
