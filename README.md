# Zearch

**A space for discovery.**

An open-source Jev-only research engine with a monochrome conversational interface. Zearch retrieves public web evidence, asks TypeSafe's Jev typed questions about it, and displays a selected source passage with a citation or abstains. Jev is the only AI model in the research path. It does not generate prose. See [the architecture](docs/JEV_ONLY.md), [delivery gates](docs/DELIVERY.md), [business model](docs/MONETIZATION.md), and [brand](BRAND.md).

## Local setup

Python 3.11+:

```sh
python -m pip install -r requirements.txt
# Set the variables documented in .env.example in your process environment.
python research_store.py
python server.py
```

Open http://localhost:8765. SQLite is for local development. The application does not automatically load .env files. Keep real credentials outside the repository. The old decision demo returns 410; it cannot return a mock result from any exposed route.

## Hosted activation

Vercel Python Functions serve `/api/research`. Add a pooled PostgreSQL `DATABASE_URL`, a random `ZEARCH_SESSION_SECRET` of at least 32 characters, `TAVILY_API_KEY`, `TYPESAFE_API_KEY`, `JEV_MODEL` (defaults to `jev-latest`), and current pricing inputs in `.env.example`. Configure Preview and Production separately. Apply `python research_store.py` from a trusted environment with that database URL. Then enable `ZEARCH_RESEARCH_ENABLED=1` and redeploy.

GET `/api/research` reports configuration/database readiness, not provider health. Apply provider spending caps too. A live canary must ask factual, ambiguous and unsupported questions, open citations, follow up, reload a saved answer and verify another browser cannot read it. Human review should check whether Jev's chosen excerpt actually supports the query. Provider calls, PostgreSQL behavior and live quality have not yet been verified.

## Features in the current release

Search uses one web query; Deep research makes up to three bounded query variations. Code ranks candidates lexically and removes duplicate sources. Jev chooses a passage and judges evidence sufficiency/conflict in a single typed request. Answers are exact excerpts selected by Jev, not original multi-source essays. Follow-ups use previous questions for retrieval; private notes are sent to Jev only when “Use my notes” is selected.

Your workspace supports owner-scoped saved answers and deletion, 20 plain-text notes (up to 40,000 characters each), `.txt`/`.md` imports, investigations and daily usage display. Deleting a note does not erase existing answers containing an excerpt from it; delete those separately. A signed HttpOnly browser cookie expires after 30 days. Cross-device accounts, rich document extraction, retention automation and billing remain outstanding. Anonymous limits can be reset by clearing cookies, so keep global and provider caps enabled.

The answer renderer supports safe headings, lists, code, bounded tables and expandable Details. HTML and model-authored links are not executed. Jev's selected answer is short; source cards provide more evidence.

## Discovery worker

Save a completed answer as an investigation. Refresh jobs search the saved question against the public web without private notes or prior conversational context. Text diffs show changed source content, not proven changes in underlying facts.

Install a recurring external invocation of `python discovery.py` with the same database, secret, Jev/search keys and pricing inputs as production; then enable `ZEARCH_DISCOVERY_ENABLED=1` on worker and web. Each invocation schedules due investigations and claims at most one queued job. Daily/weekly schedules expire 29 days after creation. Expired worker leases become failed without automatic paid retries; stale interactive runs are reconciled. No scheduler or notification service is provisioned by this repository.

## Tests and evaluation

```sh
python -m unittest discover -s tests -v
node tests/renderer.test.js
node --check app.js
python -m py_compile research.py jev_research.py research_store.py discovery.py
```

Tests use isolated SQLite and a mocked **typed Jev response**; no paid calls occur. `python evals/run.py` lists review cases without provider calls. `python evals/run.py --execute --limit 3 --depth deep` explicitly incurs provider costs through normal budgets and persists results. Human scoring is required. `python usage_report.py` reports aggregate estimated cost and latency of retained runs only; it is not a billing ledger.

Disable `ZEARCH_RESEARCH_ENABLED` to halt new research; disable `ZEARCH_DISCOVERY_ENABLED` to stop new worker claims. Schema creation is additive; rolling back code does not erase stored records. Pricing hypotheses are not purchasable plans.
