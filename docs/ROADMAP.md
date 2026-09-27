# Zearch build roadmap

**Product promise:** A space for discovery. Ask a question, get a useful answer with evidence you can inspect. Jev judges evidence and verifies claims; a separate writer drafts prose. Zearch is an open-source research engine, not a claim of AGI or unlimited paid compute.

## Current baseline (September 2026)

M1–M5 shipped foundations: monochrome conversation UI, Search/Deep research/Compare, Tavily retrieval, Jev judgments, a bounded OpenAI writer, cited source snapshots, Railway Postgres, private notes, saved investigations, quota reservation, and an optional Context.dev extractor. BTC-USD current quotes use a timestamped exchange ticker. Local tests and a few live canaries pass. This is an invitation-beta baseline, not a general quality or cost proof.

The gates below are ordered by dependency. A milestone is complete only when its evidence is recorded, not when its code is merged. Keep production caps on throughout.

| Milestone | Build | Pass condition |
|---|---|---|
| **M6 · Quality control** | Expand the 20-case set into a versioned 100-question corpus across factual, current, comparison, ambiguous, unsupported, adversarial, and follow-up tasks. Record answer usefulness, citation support per claim, source quality, abstention correctness, latency, and cost by mode. Create a review UI/report and trace every failure to retrieval, extraction, Jev, writer, or rendering. | Human reviewers open cited pages and score at least 100 completed runs. Establish the baseline and release thresholds before tuning. No provider-response fixtures count as live quality results. |
| **M7 · Retrieval and provenance** | Improve question planning, diversify providers or queries within explicit spend reservations, hybrid lexical/semantic retrieval, authority matching, publication and capture timestamps, canonical URLs, and source deduplication. Persist why each source was selected. | On the M6 set, primary-source coverage and relevant-source recall improve over the recorded baseline; no regression in unsupported-answer rate or budget. Current questions show dated evidence or an explicit freshness limitation. |
| **M8 · Owned data layer** | Build URL inventory, rights/robots policy, extraction queue, cache with per-domain freshness rules, normalized Markdown and typed metadata, content hashes, source spans, and deletion/tombstone propagation. Keep Context.dev as an optional adapter while Zearch owns the records and indexes. | Repeated research reuses permitted fresh extracts, stale records revalidate, failed jobs retry safely, and each visible citation resolves to the exact captured source span/version. Measure extract cost and success by domain. |
| **M9 · Answer engine** | Refine the Jev → writer → Jev contract: evidence sufficiency, conflict handling, paragraph/claim citation checks, concise answer first, expandable detail, follow-up context, and explicit uncertainty. Evaluate model versions behind a controlled switch. | Meet thresholds set in M6 for useful answers, supported cited claims, correct abstention, and p95 latency in each mode. A bad or missing source cannot be turned into a confident answer. |
| **M10 · Accounts and knowledge** | Add durable account IDs, cross-device history, workspace ACLs, private document ingestion, retrieval permissions, retention and export/deletion workflows. Keep private content out of public web queries. | Multi-user isolation and deletion are exercised end to end; imports are attributable to an owner; a second account cannot access another account's runs, notes, or source snapshots. |
| **M11 · Discovery service** | Provision a recurring worker, per-investigation schedules, normalized change detection, recheck thresholds, user opt-in notifications, and pause/cancel controls. Differentiate page text changes from fact changes. | A scheduled investigation survives deployment/restart, executes once per due window, respects budget and expiry, and sends only meaningful reviewed changes to opted-in users. |
| **M12 · Metering and business model** | Reconcile provider costs; implement plan entitlements, immutable customer credit ledger, signed billing webhooks, checkout/portal, top-ups, refunds, team seats and spend caps. Package Explore, Plus, and Team around measured usage, with Deep research priced in credits. | Two weeks of invitation-beta cost and retention data precede public prices. Duplicate/out-of-order webhooks, concurrency at zero balance, cancellation, and refunds pass end-to-end tests. Target contribution margin is evaluated on actual costs, not a forecast. |
| **M13 · Public release** | Security/abuse review, accessibility and mobile pass, uptime/latency dashboards, incident response, contributor docs, versioned API and self-host guide, and license/third-party data rights review. | An external beta cohort can complete Search, Deep research, Compare, saved knowledge and billing flows; release thresholds remain green for two weeks with rollback rehearsed. |

## Work order within the next milestone

1. **M6.1: Instrument runs (implemented).** Persist stage timing, provider error classes, source ranking reasons, writer fallback reasons, and Jev verdicts without storing secrets. The operator CLI reports aggregates by mode. Validate these fields on live runs during M6.3; historical records have no traces.
2. **M6.2: Build the review set.** Add representative questions, expected evidence characteristics, and a human scoring rubric. Separate stable facts from time-sensitive cases whose correct value changes.
3. **M6.3: Evaluate production.** Run a small capped batch, open citations, label failures, and set thresholds from the measured baseline. Fix the largest failure class first, then rerun the same set plus new holdouts.

## Design and economics rules

- The answer appears first. Sources, research approach, and richer detail remain inspectable without overwhelming the reading path.
- Every factual paragraph has resolvable citations. A citation is provenance; claim support still needs validation and human sampling.
- A current price or release is never inferred from an undated web page. Show the venue/source and observation time, or state the freshness limit.
- Jev is the decision and verification model. The writer has no browsing tools and receives only bounded source snapshots. Deterministic structured data such as exchange ticks can render directly.
- No unlimited provider spend, uncapped discovery jobs, or paid entitlement tied only to an anonymous cookie.
- Ship each milestone behind a rollout gate with budget limits, quality evidence, and a rollback path.
