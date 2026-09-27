# Zearch delivery gates

Brand invariant: monochrome, approved connected-loop mark, **A space for discovery.** Model contract: Jev selects and checks evidence; a separate writer drafts cited prose. See [the architecture](JEV_ONLY.md).

## Implemented slices

| Milestone | Shipped slice | Remaining acceptance gate |
|---|---|---|
| M1 · Research | Web evidence, Jev typed choice/sufficiency/conflict judgment, exact cited excerpt or abstention; durable private runs, spend reservations, and automatic PostgreSQL schema initialization | Live Railway/Jev/Tavily canaries, human-supported citation and cost review |
| M2 · Depth | Bounded one/three-query retrieval, lexical ranking, source deduplication, typed Jev evidence selection, evaluation harness | Calibration on real questions, contradiction review, semantic ranking, live enrichment quality and provider calibration |
| M3 · Knowledge | Private text notes/imports with explicit opt-in, owner-scoped history/deletion, quota meter | Accounts and cross-device identity, ACLs, document extraction, retention and deletion propagation |
| M4 · Adaptive UI | Familiar conversation layout, source cards, safe basic Markdown, tables and expandable details | Real-answer mobile, keyboard and screen-reader review; concise evidence hierarchy validated with users |
| M5 · Discovery | Saved investigations, manual/daily/weekly queue, leases, pause/expiry, stale-run reconciliation, source-text diffs | Provisioned worker, live restart/retry canaries, meaningful change review, opted-in notifications |

Live research needs provider credentials, contracted prices and a database. The new writer and enrichment adapter are implemented with offline tests but remain unverified against live providers. `/api/decide` is retired from exposed hosted/local routes; no mock fallback is active. The repository contains legacy prototype code, which should be removed in a later cleanup after the migration is secure.

## Quality and economics

Run the 20-case review set for factual, current, ambiguous, adversarial and unsupported questions. Record Jev's selected source, sufficiency judgment, abstention, source quality, claim support, latency and cost. A source citation is provenance, not proof. Every Jev decision and web request must stay within the global/session budget; provider account caps remain essential. Anonymous session quotas do not constitute paid entitlements. Do not sell subscriptions before accounts, signed billing webhooks and an immutable credit ledger are implemented and tested.

The writer can produce short paragraphs from Jev-selected evidence; Jev can reject the draft and show the selected excerpt. This gate is probabilistic, so it still needs human quality review. Treat AGI and unlimited search as ambitions, not claims of shipped capability.
