# Zearch

**A space for discovery.**

An open-source Jev-guided research engine with a monochrome conversational interface. Zearch retrieves web evidence, Jev selects passages and judges sufficiency, an OpenAI writer composes cited paragraphs, and Jev checks them before release. See [the architecture](docs/JEV_ONLY.md), [delivery gates](docs/DELIVERY.md), [business model](docs/MONETIZATION.md), and [brand](BRAND.md).

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

Vercel Python Functions serve `/api/research`. Railway Postgres is supported through its external `DATABASE_PUBLIC_URL`; put its value in Vercel's server-side `DATABASE_URL`. The backend initializes its schema automatically on the first database-backed request. See [Railway database setup](docs/RAILWAY_DATABASE.md) for the exact variables and activation order. The application currently opens short-lived direct Postgres connections; no pooler is bundled.

GET `/api/research` reports configuration/database readiness, not provider health. Apply provider spending caps too. A live canary must ask factual, ambiguous and unsupported questions, open citations, follow up, reload a saved answer and verify another browser cannot read it. Human review should check whether Jev's chosen excerpt actually supports the query. Provider calls, PostgreSQL behavior and live quality have not yet been verified.

## Features in the current release

Search uses one web query; Deep research makes three bounded queries for primary and conflicting evidence. Compare makes three queries oriented around strengths and tradeoffs. Code ranks and deduplicates sources. Optional Context.dev extraction enriches up to three pages when configured. Jev selects passages and judges sufficiency/conflict, the writer drafts up to three cited paragraphs, and Jev checks each paragraph. A failed check returns the exact selected excerpt. Follow-ups use previous questions for retrieval; private notes are sent to Jev and the writer when “Use my notes” is selected.

Your workspace supports owner-scoped saved answers and deletion, 20 plain-text notes (up to 40,000 characters each), `.txt`/`.md` imports, investigations and daily usage display. Deleting a note does not erase existing answers containing an excerpt from it; delete those separately. A signed HttpOnly browser cookie expires after 30 days. Cross-device accounts, rich document extraction, retention automation and billing remain outstanding. Anonymous limits can be reset by clearing cookies, so keep global and provider caps enabled.

The answer renderer supports safe headings, lists, code, bounded tables and expandable Details. HTML and model-authored links are not executed. Source cards provide the underlying evidence. Jev support probabilities do not prove the answer is true.

## Discovery worker

Save a completed answer as an investigation. Refresh jobs search the saved question against the public web without private notes or prior conversational context. Text diffs show changed source content, not proven changes in underlying facts.

Install a recurring external invocation of `python discovery.py` with the same database, secret, Jev/search/writer keys and pricing inputs as production; then enable `ZEARCH_DISCOVERY_ENABLED=1` on worker and web. Each invocation schedules due investigations and claims at most one queued job. Daily/weekly schedules expire 29 days after creation. Expired worker leases become failed without automatic paid retries; stale interactive runs are reconciled. No scheduler or notification service is provisioned by this repository.

## Tests and evaluation

```sh
python -m unittest discover -s tests -v
node tests/renderer.test.js
node --check app.js
python -m py_compile research.py jev_research.py writer.py enrichment.py research_store.py discovery.py
```

Tests use isolated SQLite and mocked provider responses; no paid calls occur. `python evals/run.py` lists review cases without provider calls. `python evals/run.py --execute --limit 3 --depth deep` explicitly incurs provider costs through normal budgets and persists results. Human scoring is required. `python usage_report.py` reports aggregate estimated cost and latency of retained runs only; it is not a billing ledger.

Disable `ZEARCH_RESEARCH_ENABLED` to halt new research; disable `ZEARCH_DISCOVERY_ENABLED` to stop new worker claims. Schema creation is additive; rolling back code does not erase stored records. Pricing hypotheses are not purchasable plans.
