# M6.2 human review protocol

`cases-v1.json` is a frozen, versioned set of 100 questions: ten each for factual, technical, current, comparison, ambiguous, unsupported, adversarial, conflict, synthesis and follow-up cases. Each case declares a mode, time sensitivity, expected evidence and a specific review focus. `stable` means a durable answer can be checked against sources; `current` means the answer must be checked at the run's observation time. Do not hard-code today's release, price, leader or rate into the case. A changed case or rubric needs a new corpus version.

## Run a capped batch

- `python evals/run.py --limit 3` previews cases without provider calls.
- `python evals/run.py --ids followup-01 --limit 1` previews the parent and child in order.
- `python evals/run.py --execute --ids technical-01 --limit 1 --output batch-01.jsonl` makes paid calls under normal database reservations and caps. Each batch needs a new output path. A follow-up runs its parent first, so it uses two reservations. A parent failure skips its child. Keep output files private; they contain answer and source snapshots.
- Generate a blank scorecard with `python evals/review.py init batch-01.jsonl review-01.jsonl`. Fill each JSONL row manually, then run `python evals/review.py report review-01.jsonl`. Do not publish source snapshots or reviewer notes if they include sensitive material.
- New runs also carry the provider candidate URL inventory and ranked URL set. For an optional M7 retrieval review, inspect **every candidate URL**, set `source_relevance_reviewed: true`, and enter the subset of canonical candidate URLs that directly support the question in `relevant_candidate_urls`. Use `[]` when none are relevant. Then run `python evals/retrieval_quality.py review-01.jsonl`. This measures recall within the returned candidate pool, selected precision, and matched publisher share by mode. It does not measure recall over the entire web. Leave the flag false if the candidate pool was not fully reviewed; historical runs lack this inventory.

The runner uses the `operator-evaluation` owner in the configured database. Production defaults allow only ten runs per owner per UTC day and global cost limits also apply. Several small batches across days are required. Execution is explicit; preview and review commands incur no provider cost.

## Scoring each completed run

Read the answer first, then open **every cited URL** and check every material claim against the specific cited passage. Compare to the saved source snapshot and note if the live page changed. Check whether primary sources, timestamps and publication dates are suitable for the question. For unsupported questions, inspect whether the response abstains or invents detail. Record a failure stage even when the answer looks fluent. No automatic Jev verdict counts as a human score.

Enter `reviewer`, ISO 8601 `reviewed_at`, `citations_opened` (boolean), `notes`, and one of `pass`, `fail`, `na` for each dimension:

| Dimension | Pass | Fail | NA |
|---|---|---|---|
| `usefulness` | Directly answers the request at appropriate detail | Evades, misreads, or is materially incomplete | No applicable answer expected |
| `citation_support` | Every material factual claim is supported by its specific citation | Missing, invented or mismatched support | No factual claims and no citations needed |
| `source_quality` | Evidence is relevant and authoritative for the claim | Weak, circular, stale or mismatched provenance | Correct abstention with no usable source |
| `abstention` | Answers when supported, qualifies/abstains when unsupported | Confident unsupported assertion or needless abstention | Never: judge the decision in every case |
| `freshness` | Current facts show appropriate observation/publication date | Current claim lacks valid timing or relies on stale evidence | Stable question with no current claim |

Set `failure_stage` to `retrieval`, `extraction`, `jev_selection`, `writer`, `jev_verification`, `rendering`, `other`, or `none`. Choose the first stage that made the answer materially wrong, and explain downstream effects in `notes`. A `citation_support` pass/fail requires `citations_opened: true`; a current case requires a freshness pass/fail. Rows with missing judgments remain unreviewed, while partial reviews are rejected by the report.

## Release evidence

The report separates modes and categories and counts only complete, fully reviewed runs for quality scores. It also shows p95 duration and estimated provider cost for the recorded attempts, including missing cost records. These are estimates, not a billing ledger. It does not claim quality based on fixtures or unreviewed outputs. M6 needs at least 100 distinct completed cases reviewed with opened citations, an established live baseline and thresholds before tuning. Record the execution date, model IDs and provider configuration with each batch outside the corpus. Review failure traces in `usage_report.py` before deciding thresholds. Keep a holdout for changes after the baseline.

To evaluate a controlled M9 model change, pin separate baseline and candidate review JSONL files covering all 100 cases. Run `python evals/model_compare.py baseline.jsonl candidate.jsonl --policy evals/quality-policy.json`. It rejects missing or duplicate cases, incomplete reviews, mixed model versions within a cohort, reused run IDs, uninspected citations, missing timing/cost and quality regressions by mode. The default policy returns HOLD until the M6.3 measured baseline and thresholds are approved. Its GO output requires the M6.4 gate and no measured pass-rate regression; it is not a substitute for a human review of the cited pages.
