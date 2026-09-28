# Evidence-bound rich output contract

Zearch answers can be more than prose, but the medium never bypasses research verification. Jev selects and checks evidence; the writer chooses a useful presentation of that evidence. The browser renders a small, non-executing format. Search, Deep research and Compare share the same contract.

## Shipped baseline

- Text, headings, lists, compact tables, language-labeled code blocks and expandable Details use a safe Markdown subset. HTML and model-authored links are text, not executable elements.
- A complete, Jev-checked two-column table with 2–20 nonnegative numeric values, a single unit and a resolvable citation on every value can toggle to a bar chart. The source table stays available. This is a display transform of checked numbers, not an independent model answer or generated dataset.
- Code is displayed, never run. Its explanatory text and fenced block form one Jev verification unit. Unsupported code falls back to selected evidence or an abstention.
- Private notes and documents enter the evidence set only after the user's per-query opt-in; they never enter the public web query.
- A completed saved answer can be exported as a bounded PDF or plain text research brief. Its owner-scoped endpoint includes the question, answer and source appendix with capture IDs where available. It does not independently verify the answer or include full captured pages. Deleted and redacted runs no longer export. The same browser-session ownership limit applies until account sign-in is enabled.

## Versioned artifact envelope for the next slices

Use server-created typed parts alongside the canonical answer text, not raw HTML or untrusted Markdown extensions. A part has `schema_version`, `kind`, `artifact_id`, `owner`, `run_id`, `created_at`, `status`, `source_version_ids`, `verification`, and a bounded kind-specific payload. Only the API can set `owner`, `run_id`, or a storage URL. The browser fetches parts through owner-scoped endpoints and uses a strict kind allowlist.

| Kind | Input and verification | Delivery rule |
|---|---|---|
| Chart / graph | Structured series with units, observation times, point-level citations and source capture versions. Validate finite numbers, units and bounds; Jev checks the interpretation and claims. | Render locally from validated data; show an accessible source table and limitations. |
| Code | Language, bounded plain text, cited explanation. Jev checks claimed behavior against evidence. | Syntax highlighting and copy only; never execute in the browser. |
| Image | Separately generated or licensed asset, prompt/rights metadata and provenance. Factual labels need Jev-checked sources. | Scan, store privately, serve with explicit content type and owner ACL; label generated media. |
| Video | Separately generated or licensed asset with job status, duration, rights and provenance. Any factual narration needs a checked script. | Async capped job; owner-scoped playback with safe media headers, no arbitrary embeds. |
| Document | Future model-authored documents require a typed input, verified claims and explicit artifact version. The current PDF/text brief is a server-rendered copy of one saved checked answer. | Owner-scoped download and source appendix; deletion revokes current brief URLs. Durable authored files need immutable versions, storage ACLs and deletion propagation. |

The writer does not receive arbitrary browsing, code execution, file write, or unrestricted media tools. Artifacts require separate reservations, provider cost accounting, content limits, retention controls, and failure states. If rendering or verification fails, keep a supported text answer when available and report that the artifact could not be produced. Do not present a generated illustration as a photograph or a simulated financial series as observed data.

## Acceptance before enabling media

Exercise cross-account denial, source tombstones, deletion, expired links, malformed payloads, XSS/content sniffing, provider failure, accessibility, mobile layout, and per-kind cost caps. Review factual claims in the artifact itself, not just the accompanying paragraph. The M6/M9 live human cohort remains a release prerequisite for the answer quality claim.
