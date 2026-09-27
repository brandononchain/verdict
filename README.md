# Zearch

**A space for discovery.**

An open-source research interface with a locked monochrome identity. The new research path retrieves web evidence and streams a generated answer with inspectable citations. The original JEV/TypeSafe typed-decision prototype remains in the codebase as legacy endpoints.

## Current release

M1 foundation is implemented. Live activation requires server configuration and database migration. M2–M5 are planned, not claimed complete. See [delivery gates](docs/DELIVERY.md), [business model](docs/MONETIZATION.md), and [brand](BRAND.md).

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
python -m py_compile research.py research_http.py research_store.py server.py
```

Tests use isolated SQLite and mocked providers. No paid provider requests occur in tests. PostgreSQL and live-provider validation remain release gates.

## Data and access

Runs are scoped to a signed HttpOnly browser-session cookie. Its access expires after 30 days; records are not automatically deleted. Local history stores only IDs and questions. Clearing history removes local shortcuts, not server data. Cross-device accounts, deletion UI, retention automation and uploads belong to M3. Do not accept sensitive uploads in this beta. Keep ZEARCH_RESEARCH_ENABLED=0 until operational configuration is complete.

To roll back research availability, set ZEARCH_RESEARCH_ENABLED=0 and redeploy. Schema creation is additive; reverting code does not delete records. The old `/api/decide` and `/api/search` endpoints retain prototype behavior and must not be mistaken for this production research contract.
