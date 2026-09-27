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

## Billing implementation gate (M3)

Before charging: verified account ownership, plan entitlements in the database, hosted checkout and portal, signed and deduplicated billing webhooks, cancellation/renewal handling, a reconciled customer credit ledger, transparent allowance meter and failed-run refund policy. Reserve customer credits transactionally, settle measured use exactly once, refund unused reservation according to published policy. Never trust plan or price identifiers from browser input. Payment settlement must not depend on the return-to-site redirect. Test renewal failure, duplicate and out-of-order webhooks, top-up replay, subscription downgrade, and concurrent research at zero balance.

## Unit economics

Track revenue per active payer, useful completed answers, p50/p95 cost by research mode, search/Jev/search/extraction/storage costs, payment fees, support, retention, allowance exhaustion, and abuse. Contribution = net revenue minus these variable costs. Initial design target: 75% contribution margin; this is a target, not a measured result. Included usage budget must fit revenue after payment/support/storage reserves. Price deep investigations separately in credits so casual subscribers do not subsidize unbounded automation. Display the credit estimate before expensive work and require opt-in for top-ups.

Go/no-go: launch a small invitation beta, measure at least two weeks of usage, establish model-specific costs and quality, then set public pricing. Provider account caps and the application global cap stay enabled. Anonymous session limits alone do not prevent abuse and must not support a paid launch.

## Release 2 instrumentation

Deep research reserves three search attempts before execution; partial search failures remain counted because providers may charge. The workspace now shows daily run use/reset and the operator report separates standard/deep completion, missing-cost records, estimated costs and p95 timing. A 20-case evaluation harness supplies qualitative review prompts. This enables pricing decisions; it does not itself prove a sustainable margin.

Customer billing remains disabled. Avoid coupling anonymous browser sessions to paid balances. Before launch, introduce durable account IDs and the separate immutable credit ledger described above; connect checkout only after signed webhook and entitlement tests pass. Do not represent the daily operational quota as a purchased credit balance.
