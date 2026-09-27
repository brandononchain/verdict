# Zearch

**A space for discovery.**

An open-source research interface with a locked monochrome identity. The new research path retrieves web evidence and streams a generated answer with inspectable citations. The original JEV/TypeSafe typed-decision prototype remains in the codebase as legacy endpoints.

## Current release

M1 foundation and working M2–M5 increments are implemented: bounded deep retrieval, private text knowledge, structured answer rendering, and durable discovery jobs. Live activation requires server configuration and database migration. Full milestone acceptance, accounts and paid billing remain outstanding. See [delivery gates](docs/DELIVERY.md), [business model](docs/MONETIZATION.md), and [brand](BRAND.md).

## Local setup

Python 3.11+ and Node for JavaScript syntax validation:

```sh
python -m pip install -r requirements.txt
# Set the variables documented in .env.example in your process environment.
python research_store.py
python server.py
```

Open http://localhost:8765. SQLite is used locally unless DATABASE_URL is set. The application does not automatically load .env files. Keep real credentials outside the repository.

## Hosted setup

Vercel Python Functions serve `/api/research`. Add a pooled PostgreSQL DATABASE_URL, a random session secret of at least 32 characters, Tavily API key, gateway credential, selected gateway model ID, and the current pricing rates in .env.example. Configure Preview and Production separately. Apply `python research_store.py` from a trusted environment with that DATABASE_URL. Finally enable ZEARCH_RESEARCH_ENABLED=1 and redeploy.

Gateway uses OpenAI-compatible `/v1/chat/completions`; choose a model supporting streaming and max_tokens. Test it before launch. Pricing inputs are operator estimates, not billing authority; configure provider spending caps too. Missing configuration returns an honest setup state with search disabled. GET `/api/research` returns readiness; it does not make a paid health-check call.

Run a live canary after configuration: ask a factual question, open a citation, ask a follow-up, reload its #r/ID URL, verify another browser cannot read it, and inspect stored usage/error records. Test deployed streaming explicitly; local fixture tests do not prove provider or platform behavior.

## Validation

```sh
python -m unittest discover -s tests -v
node --check app.js
node tests/renderer.test.js
python -m py_compile research.py research_http.py research_store.py server.py
```

Tests use isolated SQLite and mocked providers. No paid provider requests occur in tests. PostgreSQL and live-provider validation remain release gates.

## Data and access

Runs are scoped to a signed HttpOnly browser-session cookie. Its access expires after 30 days; records are not automatically deleted. Local history stores only IDs and questions. Clearing history removes local shortcuts, not server data. The workspace supports owner-scoped deletion and .txt/.md imports (40,000 characters, 20 notes). Selecting Use my notes sends relevant snippets to the configured model. Deleting a note does not erase existing generated answers; delete those separately. Cross-device accounts, rich document extraction, and retention automation remain outstanding. Keep ZEARCH_RESEARCH_ENABLED=0 until operational configuration is complete.

To roll back research availability, set ZEARCH_RESEARCH_ENABLED=0 and redeploy. Schema creation is additive; reverting code does not delete records. The old `/api/decide` and `/api/search` endpoints retain prototype behavior and must not be mistaken for this production research contract.

## M2–M5 increment

- Search / Deep research selects one or three bounded provider searches. Ranking uses lexical BM25, URL/content deduplication and domain diversity. This is not neural reranking or automatic claim verification.
- Your workspace lists saved answers, private text notes, investigations and daily run usage. Ownership uses the signed browser session; account sync is not implemented.
- Answer rendering supports safe headings, lists, code, bounded tables and expandable Details. Model-authored HTML and arbitrary links are not executed.
- Save investigation on a completed answer. Refresh jobs search the saved question against the public web without conversation context or private notes. Diffing compares retrieved source text, not factual truth.

Re-run `python research_store.py` before activating this release; schema additions are idempotent and work with existing M1 records. Until migrated, readiness fails closed.

## Discovery worker

Install a recurring external invocation of `python discovery.py` with the same database, secret, provider and pricing environment as production; then set ZEARCH_DISCOVERY_ENABLED=1 on both worker and web deployment. Each invocation schedules due investigations and executes at most one queued job. Invoke every minute; add bounded worker capacity only after observing throughput/cost. This release does not provision a scheduler or send notifications.

Daily/weekly schedules expire 29 days after creation, so anonymous schedules cannot run indefinitely. Pause cancels queued work; active work finishes. Five-minute leases prevent competing workers from claiming the same job. Expired leases become failed and require an explicit refresh; uncertain paid calls are never automatically repeated. The worker also reconciles research stuck for over ten minutes. All calls use the same global/session budget reservation as interactive research.

## Evaluation and economics

`python evals/run.py` lists cases without provider calls. `python evals/run.py --execute --limit 3 --depth deep` explicitly runs paid evaluations through normal budgets and persists results. Human review of claim support and usefulness is required; no quality score is synthesized by the runner. `python usage_report.py` outputs aggregate cost/latency for retained runs only, without prompts or private notes. Deleted runs are absent from this diagnostic report; this is not a financial ledger.
