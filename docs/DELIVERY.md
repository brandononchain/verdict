# Zearch delivery gates

Brand invariant: monochrome, approved connected-loop mark, **A space for discovery.** Model invariant: **Jev is the only AI model**. See [the Jev-only contract](JEV_ONLY.md).

## Implemented slices

| Milestone | Shipped slice | Remaining acceptance gate |
|---|---|---|
| M1 · Research | Web evidence, Jev typed choice/sufficiency/conflict judgment, exact cited excerpt or abstention; durable private runs and spend reservations | PostgreSQL migration, live Jev/Tavily canaries, human-supported citation and cost review |
| M2 · Depth | Bounded one/three-query retrieval, lexical ranking, source deduplication, typed Jev evidence selection, evaluation harness | Calibration on real questions, contradiction review, semantic/learned ranking only if it respects Jev-only model policy |
| M3 · Knowledge | Private text notes/imports with explicit opt-in, owner-scoped history/deletion, quota meter | Accounts and cross-device identity, ACLs, document extraction, retention and deletion propagation |
| M4 · Adaptive UI | Familiar conversation layout, source cards, safe basic Markdown, tables and expandable details | Real-answer mobile, keyboard and screen-reader review; concise evidence hierarchy validated with users |
| M5 · Discovery | Saved investigations, manual/daily/weekly queue, leases, pause/expiry, stale-run reconciliation, source-text diffs | Provisioned worker, live restart/retry canaries, meaningful change review, opted-in notifications |

The new Jev path is not live until credentials, prices and database are configured. `/api/decide` is retired from exposed hosted/local routes; no mock fallback or generative-model answer path is active. The repository contains legacy prototype code, which should be removed in a later cleanup after the migration is secure.

## Quality and economics

Run the 20-case review set for factual, current, ambiguous, adversarial and unsupported questions. Record Jev's selected source, sufficiency judgment, abstention, source quality, claim support, latency and cost. A source citation is provenance, not proof. Every Jev decision and web request must stay within the global/session budget; provider account caps remain essential. Anonymous session quotas do not constitute paid entitlements. Do not sell subscriptions before accounts, signed billing webhooks and an immutable credit ledger are implemented and tested.

Jev cannot author the fluid paragraphs of a generative chat model. The UI can feel like a conversation, but Jev-only answers must be evidence selections or deterministic compositions. Treat AGI and unlimited search as ambitions, not claims of shipped capability.
