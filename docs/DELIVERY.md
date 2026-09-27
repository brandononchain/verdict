# Zearch delivery plan

Brand lock: monochrome, approved connected-loop mark, **A space for discovery.**

## Release 1: M1 research foundation

Implemented: server-controlled Tavily retrieval, actual gateway token streaming, source links, follow-up context, durable run records, private browser-session ownership, idempotency, atomic daily spend reservations, interruption handling, and explicit failure states. No mock fallback in `/api/research`. Original TypeSafe decision endpoints remain legacy and are not used by the new UI.

Not yet production validated: paid provider calls, PostgreSQL execution/concurrency, deployed streaming latency and model quality. Availability reports configuration/database readiness only, not provider health. Do not open paid signup before these gates pass.

Limits: source identifiers are validated, but entailment is not. Retrieved pages may be incomplete; source instructions remain untrusted. Follow-ups include up to three earlier answers; retrieval includes two earlier questions. Anonymous sessions are not accounts. Clearing cookies can bypass session quotas; the global cap remains. A provider budget must also be set because cost estimates are not invoices. Function termination can leave a pending/streaming run; the configured discovery worker reconciles runs older than ten minutes. Browser stopping closes the response but provider cancellation is best effort.

## Release 2: M2–M5 working increments

| Area | Implemented now | Still required for full acceptance |
|---|---|---|
| M2 | Three bounded search attempts, query diversification, lexical BM25, duplicate removal, domain diversity, retrieval trace, 20-case human-review evaluation harness | Learned/semantic reranker, calibrated planning and contradiction checks, live quality/cost benchmark |
| M3 | Private text notes/imports, query-relevant snippets with explicit opt-in, server history and deletion, quota meter | Accounts, cross-device ownership, workspace ACLs, embeddings/hybrid retrieval, document parsers and retention automation |
| M4 | Safe headings/lists/code/tables, concise-first prompt, expandable Details, responsive workspace UI | Live streamed-answer usability review, full keyboard/screen-reader validation, structured response contract beyond Markdown |
| M5 | Saved investigations, manual/daily/weekly jobs, durable leases, deduplication, pause/expiry, stale-run reconciliation, source-text diffs | Provisioned worker, live recovery validation, semantic change assessment, opted-in notifications |

These increments are executable and tested with isolated SQLite and provider fixtures. They do not establish production readiness. Readiness requires the additive migration and provider configuration; schedules remain hidden until ZEARCH_DISCOVERY_ENABLED=1. No external notifications are sent.

Validation: 29 Python tests plus Node renderer tests cover quotas, private data, HTTP streaming/reload, concurrent scheduling/claiming, worker completion, stale leases, unsafe-link handling, and parsing. PostgreSQL and paid-provider integration are explicitly unverified. Run the evaluation harness with --execute only when ready to incur the configured provider costs.

## Milestone gates

| Milestone | Next implementation | Required evidence before completion |
|---|---|---|
| M1 · Real answers | Configure providers/Postgres, migrate, run live canary | Live question, follow-up, reload, cited answer, provider error, owner isolation; measured cost and latency |
| M2 · Research depth | Typed research plan, bounded parallel query expansion, semantic reranking, evidence contradiction checks | Evaluation corpus across factual, current, ambiguous, comparison, and adversarial queries; citation entailment and abstention review; p50/p95 costs |
| M3 · Knowledge | Accounts, owner/workspace ACLs, durable conversation listing/deletion, upload extraction, hybrid retrieval | Cross-tenant denial tests, deletion propagation, upload size/type limits, source permissions enforced before retrieval |
| M4 · Adaptive output | Structured response schema, concise answer first, validated comparison tables, optional expanded detail | Mobile/keyboard/screen-reader review, malicious content tests, usability trials; rich cards only when useful |
| M5 · Discovery | Saved investigations, durable scheduler/queue, retries/leases, evidence snapshots and meaningful change detection | Restart/retry recovery, idempotent notification delivery, per-job budgets, stale-run reconciliation and pause controls |

Sequence: activate M1; benchmark M2; add identity and billing with M3; expand presentation with M4; release recurring research with M5. Each release must include migration/rollback instructions and observed evidence. No milestone is complete simply because a scaffold exists.

## Architecture decisions

Vercel serves UI and short interactive research. PostgreSQL stores ownership, conversations, source snapshots, runs, usage ledger, entitlements, and jobs. Longer investigations move to durable workers; no in-request infinite agent loop. TypeSafe/JEV can govern finite routing or evidence decisions after calibration. Generative synthesis is a separate adapter. Use explicit typed contracts at every boundary and preserve source provenance.

Quality target: useful answers with inspectable evidence. AGI and unlimited data are aspirations, not shipped capabilities or pricing promises.
