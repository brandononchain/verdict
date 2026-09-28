# M6.3 live canary log — September 28, 2026 UTC

This is an initial production observation, **not** a representative quality baseline or an M6 release pass. Five completed Search runs were submitted through the production UI under the normal session quota. The next attempted run was refused before execution by the daily allowance; it is excluded below. All costs are Zearch's provider estimates, not reconciled invoices. Local fixture tests do not count as live quality results.

| Case | Version | Jev gate → answer path | Result | Time | Estimated provider cost | Citation inspection |
|---|---|---|---|---:|---:|---|
| `technical-01` HTTP 429 | Before passage change | abstain → selected excerpt | **False abstention.** MDN and Cloudflare snippets explained 429 and optional `Retry-After`, but the answer said it could not find a clear passage. Draft was rejected. | 4.4 s | $0.013514 | No claims in answer; source previews and RFC 6585 checked separately. |
| `factual-01` Moon | Before passage change | answer → verified prose | Correct synchronous rotation and libration nuance. | 4.4 s | $0.012665 | Both cited NASA pages opened; each paragraph supported. |
| `unsupported-02` exact future GPU price | Before passage change | abstain → verified prose | Correctly refused a precise future value, but repeated itself in three paragraphs and cited rumors, a video and weak price pages. | 4.3 s | $0.020331 | **Partial only:** cited pages not all opened; do not count as a full citation score. |
| `technical-01` HTTP 429 rerun | After adjacent-passage change | answer → verified prose | Directly answered rate limiting, optional `Retry-After`, and bounded retry/backoff. | 5.7 s | $0.014988 | All cited MDN, Cloudflare and Postman pages opened; claims supported. RFC 6585 independently confirms the optional header. |
| `current-01` Python stable release | After adjacent-passage change, before capture-time change | abstain → verified prose | Identified Python 3.14.7 from the official list correctly, but added a long caveat because source capture time was absent from the writer's input. | 4.7 s | $0.015432 | **Partial only:** official Python release list opened and version/date confirmed; secondary citations not all opened. |

Observed five-run sum: **$0.076930 estimated provider cost**. Median elapsed time was 4.4 seconds; observed maximum was 5.7 seconds. These figures cover one mode, a tiny selected sample, and do not establish p95 performance, margin, or general answer quality.

## Changes and verification

1. Owner-scoped Research approach now exposes Jev gate, answer path, draft fallback, elapsed time and estimated provider cost on saved runs. It does not expose other users' records.
2. The Jev evidence selector now keeps up to two sentences adjacent to the best matching sentence within the existing 450-character cap. On the repeated HTTP 429 question, the gate changed from abstain to answer; Jev verified the resulting prose. The result costs about $0.001474 more and took 1.3 seconds longer in these two runs. This is an observation, not a causal latency estimate.
3. Capture time now travels to the writer and paragraph verifier and appears under sources as **page capture**, distinct from a fact's observation time. This was unit tested but **not live rerun** for Python because the normal daily allowance refused the next request.

## Next capped batch

After the normal allowance reset, rerun `current-01` to check the capture-time wording and open every cited page. Add a Compare, an adversarial/unsupported, and a follow-up case under the same spend caps. Score each completed run with the M6.2 rubric; log failures by their earliest material stage. Extend across days until 100 distinct completed cases have human citation reviews. Set release thresholds from that distribution and holdouts, not from these five attempts.
