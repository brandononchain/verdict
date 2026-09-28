# M6.4 quality release gate

Run `python evals/quality_gate.py review-cohort.jsonl`. It prints a mode-specific report and exits nonzero on `HOLD`. The default `quality-policy.json` deliberately has no baseline ID or thresholds, so the current state is always `HOLD`.

The cohort must contain exactly one completed, fully human-reviewed run for **each of the 100 versioned case IDs**. Every row needs matching category/mode/time classification, opened sources, nonnegative total elapsed time, and a nonnegative estimated provider cost. Abstention must be scored. Duplicate or missing cases hold the gate; choose one run per case before calculating release metrics. This prevents a good rerun from silently hiding a failed first attempt in the pinned baseline. Keep all other attempts in the separate audit log.

After the 100-case baseline is reviewed, record an immutable baseline identifier and fill the per-mode minimum pass rates for usefulness, citation support, source quality, abstention, and freshness where applicable. Set per-mode maximum p95 elapsed milliseconds and estimated provider cost in USD using that measured distribution plus the product's cost/latency goals. Commit the policy with a rationale and the pinned cohort. The gate compares a later pinned cohort against those thresholds. A `GO` means only that these declared metrics passed for that cohort; it is not a public-release decision or proof of general accuracy. Keep provider costs reconciled separately from these estimates.

The local test constructs a synthetic 100-case fixture to verify gate behavior; it is never treated as a live quality result. The first production observations are in [LIVE_BASELINE.md](LIVE_BASELINE.md), with M6.3 still in progress under the normal daily caps.
