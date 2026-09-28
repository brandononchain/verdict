# Zearch

**A space for discovery.**

An open-source Jev-guided research engine with a monochrome conversational interface. Zearch retrieves web evidence, Jev selects passages and judges sufficiency, an OpenAI writer composes cited paragraphs, and Jev checks them before release. See [the architecture](docs/JEV_ONLY.md), [delivery gates](docs/DELIVERY.md), [build roadmap](docs/ROADMAP.md), [business model](docs/MONETIZATION.md), and [brand](BRAND.md).

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

Search uses one web query; Deep research makes three bounded queries for primary and conflicting evidence. Compare makes three queries oriented around strengths and tradeoffs. Code ranks and deduplicates sources. Optional Context.dev extraction enriches up to three pages when configured. Jev selects passages and judges sufficiency/conflict; a writer drafts a concise, cited answer; then Jev separately judges factual support and citation attribution for each paragraph. Attribution judgments are recorded in shadow mode by default while the existing support threshold controls release; set `ZEARCH_ATTRIBUTION_GATE=1` only after live review validates the additional rejection behavior. Drafting and verification use the same bounded source window, which includes Jev's inspected passage even near the end of a capture. Provider snippets precede page text so navigation does not crowd out the answer. When a single extracted passage fails Jev's sufficiency gate, the writer may draft from the best full sources; Jev must independently approve the draft before it is released. Failed verification returns the Jev-selected passage or an explicit abstention. Follow-ups use previous questions for retrieval; private notes are sent to Jev and the writer when “Use my notes” is selected.

Current BTC-USD price questions use a fresh Coinbase Exchange last-trade ticker with a timestamp and source citation. The numeric quote is rendered directly from validated structured data; it is not a Jev or writer estimate. A stale or unreachable ticker returns an explicit unavailable message rather than an old web-page price. The quote is venue-specific and can differ across exchanges.

For covered technical and science topics, search prefers the publisher's own domain while still allowing independent results. Ranking combines query coverage, provider score and a bounded primary-source boost; the matched domain list is deliberately auditable and incomplete. Selected sources retain their canonical URL, the bounded queries that found them, ranking factors and selection reasons. New runs retain a bounded candidate URL inventory for human retrieval review. Reported publication dates are validated provider metadata and kept distinct from Zearch's page capture time. Source cards show the passage Jev inspected, with offsets into the captured text. Jev's paragraph verification sees only the evidence actually cited in that paragraph. Source presence and automated support judgments do not replace human review of citation quality.

M8's first owned-data slice assigns each saved source snapshot a content-and-capture version ID. Optional extracted-page reuse requires an exact HTTPS hostname in `source_cache_policy.json`, with a recorded permission basis, review date and TTL between five minutes and seven days. The committed policy has no enabled domains. Fresh search still runs on every question; eligible, unexpired Context.dev extractions can replace a repeat extraction. Cache hits retain their original capture timestamp, reduce actual scrape calls, and never increase the spending reservation. Expired extracts are pruned on writes. A tombstone blocks future cache reuse for a canonical URL and redacts retained run snapshots containing that URL. This is not a general crawl or a rights determination.

M8.2 includes an opt-in revalidation worker. After a domain has an approved cache policy, `python source_revalidation.py enqueue https://approved.example/page` queues one canonical URL. `python source_revalidation.py work` claims at most one job; `python source_revalidation.py report` shows job states and the past 14 days of reserved call estimates. The worker is idle unless `ZEARCH_REVALIDATION_ENABLED=1`, `CONTEXT_DEV_API_KEY`, `ZEARCH_SCRAPE_USD_PER_CALL`, `ZEARCH_DAILY_REVALIDATION_CALLS` and `ZEARCH_DAILY_REVALIDATION_USD` are configured. Defaults for both daily caps are zero. Each attempt reserves its estimated cost before contacting Context.dev, runs with a 90-second lease, and retries at most three times with bounded backoff. Set the caps to a separately approved spend envelope. The repository does not provision a recurring worker invocation or enable any cache domain by default.

Inline citations open the owner-scoped captured source, highlight Jev's inspected character range when present, and show the capture version ID. The source title still links to the original page for comparison. `python source_store.py tombstone https://example.org/page` is an operator deletion action: it removes the shared extract and pending rechecks, redacts retained answers containing that canonical URL across owners, clears affected investigation snapshots, and excludes the URL from future Jev evidence. The operator operation scans retained runs inside one database transaction, so schedule it outside peak traffic while the beta dataset is small. It cannot retract content already delivered to a client before the deletion transaction. This is a source takedown, not a user's delete-run action.

Your workspace supports owner-scoped saved answers and deletion, 20 plain-text notes (up to 40,000 characters each), and 20 private `.txt`, `.md` or bounded `.docx` documents (up to 128 KB and 80,000 extracted characters). Relevant private excerpts are sent to Jev and the writer only when “Use my notes” is selected, never in the public web query. Deleting a note or document redacts retained answers that used it. The anonymous signed HttpOnly browser cookie expires after 30 days. Anonymous limits can be reset by clearing cookies, so keep global and provider caps enabled.

Passwordless account sync is implemented but **disabled by default**. Configure `ZEARCH_EMAIL_AUTH_ENABLED=1`, `ZEARCH_MAIL_HOST`, `ZEARCH_MAIL_PORT` (465 SSL or STARTTLS on another port), `ZEARCH_MAIL_USER`, `ZEARCH_MAIL_PASSWORD`, and `ZEARCH_MAIL_FROM` as server-side variables. Provider credentials stay server-side; the one-time code is sent by email and never returned by the API. Codes expire in 10 minutes and have five attempts; mail requests are bounded per address and globally. Successful sign-in creates a database-backed 30-day HttpOnly account session. A user explicitly claims their current anonymous workspace after sign-in, then can see history on another device. Sign-out revokes one session; account deletion erases private data and revokes every session. Keep the feature off until outbound mail and the live sign-in/deletion rehearsal pass. No Supabase is required; accounts and documents use Railway Postgres. Run `python account_store.py` from a trusted scheduled worker to prune expired codes and sessions; the same cleanup happens opportunistically on a new sign-in request. PDF/OCR and team ACLs remain separate future work.

The answer renderer supports safe headings, lists, code, bounded tables and expandable Details. HTML and model-authored links are not executed. Source cards provide the underlying evidence. Jev support probabilities do not prove the answer is true.

The M10 presentation slice can show language-labeled code blocks and toggle a two-column cited numeric table into a bar chart. The chart is derived from the checked answer and retains the table and captured citations; it does not generate new facts. A completed answer can be exported as a PDF research brief or plain text, with its question, answer, source list and capture IDs. The export is generated on request from the owner's saved run, served without caching, and becomes unavailable when that run is deleted or redacted. It is a readable copy of the checked answer, not a new verification step or a full source archive. Generated images and video remain future work; see the [rich output contract](docs/RICH_OUTPUTS.md). The workspace can separately download a paginated JSON export of its private notes, documents, investigations, answers, and captured evidence, or delete those records while preserving daily metering. Browser session ownership alone does not provide cross-device identity.

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

Tests use isolated SQLite and mocked provider responses; no paid calls occur. `python evals/run.py --limit 3` previews the versioned 100-case review set without provider calls. `python evals/run.py --execute --limit 3 --output batch-01.jsonl` explicitly incurs provider costs through normal budgets and persists results. Use `python evals/review.py init batch-01.jsonl review-01.jsonl` for blank human scorecards; see [the review protocol](evals/REVIEW.md). Human citation inspection and scoring are required. `python usage_report.py` is an operator-only aggregate of retained runs by mode: estimated cost, stage and total latency, failure stages and kinds, search failures, Jev gates, draft fallbacks, and source tiers. It does not print prompts or owner IDs and is not a billing ledger. New runs carry timing and ranking traces in their existing records; older runs without them are omitted from those metrics.

Disable `ZEARCH_RESEARCH_ENABLED` to halt new research; disable `ZEARCH_DISCOVERY_ENABLED` to stop new worker claims. Schema creation is additive; rolling back code does not erase stored records. Pricing hypotheses are not purchasable plans.
