# Sustainable research business

## Product model

| Plan | Value | Economic control |
|---|---|---|
| Explore | Try cited search | Small daily allowance, bounded answer length, no scheduled jobs |
| Plus | Daily research, saved knowledge, deeper investigations | Monthly included research credits, explicit optional prepaid top-ups |
| Team | Shared knowledge and recurring discovery | Per-seat subscription plus pooled research credits, workspace spend caps |

These are proposed packaging, not purchasable plans. Dollar prices and allowances remain unset until live cost and retention measurements exist. No unlimited paid-model or crawl promise. Avoid advertising or paid source ranking in the core answer experience.

## Implemented foundation

Every research run reserves conservative micro-USD against global and session UTC-day budgets in one database transaction before upstream work. Duplicate request identifiers replay their existing run. Store returned token usage and estimated provider cost alongside the run. Failed requests retain the operational reservation because upstream billing may have occurred. These are infrastructure safety budgets, NOT a customer credit ledger or an invoice. The operational estimate now accounts for Jev input tokens, writer input/output tokens, search calls and optional page scrapes. The reservation bounds two Jev calls, one 900-token writer draft and three scrapes. This is still an estimate rather than a reconciled bill.

## Billing implementation gate (M12)

The M12.1 internal foundation now stores account plan/status/period end, an append-only credit ledger and a materialized balance checked against its entries. Trusted code can grant a credit event once globally, reserve against an active entitlement, and settle exactly once with a bounded refund. Replayed or conflicting grant, reservation and settlement references are rejected or returned idempotently. Concurrent zero-balance reservations cannot overspend. Credit units are internal integers; no public exchange rate, plan allowance or price has been assigned. This ledger is not wired into research or exposed by an API, so it cannot bill or charge anyone. Beta account deletion purges the unused credit records with the account; financial record retention must be designed before real payments are accepted.

Before charging: hosted checkout and portal, signed and deduplicated billing webhooks, cancellation/renewal ordering, a transparent allowance meter, provider cost reconciliation and a published failed-run refund policy. Reserve customer credits transactionally with the operational research reservation, settle measured use exactly once, refund unused reservation according to policy. Never trust plan or price identifiers from browser input. Payment settlement must not depend on the return-to-site redirect. Test renewal failure, duplicate and out-of-order webhooks, top-up replay, subscription downgrade, and concurrent research at zero balance.

## Unit economics

Track revenue per active payer, useful completed answers, p50/p95 cost by research mode, search/Jev/search/extraction/storage costs, payment fees, support, retention, allowance exhaustion, and abuse. Contribution = net revenue minus these variable costs. Initial design target: 75% contribution margin; this is a target, not a measured result. Included usage budget must fit revenue after payment/support/storage reserves. Price deep investigations separately in credits so casual subscribers do not subsidize unbounded automation. Display the credit estimate before expensive work and require opt-in for top-ups.

Go/no-go: launch a small invitation beta, measure at least two weeks of usage, establish model-specific costs and quality, then set public pricing. Provider account caps and the application global cap stay enabled. Anonymous session limits alone do not prevent abuse and must not support a paid launch.

## Release 2 instrumentation

Deep research reserves three search attempts before execution; partial search failures remain counted because providers may charge. The workspace now shows daily run use/reset and the operator report separates standard/deep completion, missing-cost records, estimated costs and p95 timing. A versioned 100-case evaluation harness supplies qualitative review prompts and blank human scorecards. This enables pricing decisions; it does not itself prove a sustainable margin.

Customer billing remains disabled. Durable account IDs and a separate internal credit ledger are implemented, but checkout and signed webhook handling are absent. Avoid coupling anonymous browser sessions to paid balances. Do not represent the daily operational quota as a purchased credit balance.
