# Jev patterns adopted by Zearch

Reference: [cobusgreyling/Jev](https://github.com/cobusgreyling/Jev), MIT, unofficial TypeSafe showcase. We studied its `jev-fanout`, `jev-route`, `jev-guardrail` skills and anti-patterns. No copied source code or bundled test data is required for these workflow principles.

| Pattern | Zearch implementation |
| --- | --- |
| One request, independent questions | `jev_research.state_and_questions` fans out best passage Choice, sufficiency and conflict Noul, and per-candidate relevance Noul. `verify` fans out paragraph support and attribution in a second call after the answer exists. |
| Choice and Noul have different meanings | `judge` has separate selected Choice probability, sufficiency Noul, and conflict Noul gates. The dashboard exposes the resulting evidence decision, not a single misleading confidence number. |
| Code owns effects | Jev judges evidence. Python decides when to write an answer, schedule a monitor, claim a job, or export data. Source text is treated as evidence, never instructions. |
| Generative model writes prose | The writer composes paragraphs from selected sources. Jev checks the draft before it appears. Jev is never asked to generate a paragraph, image, or styleguide. |
| Literal extraction and code arithmetic | Page counts, asset totals, change hashes, dates, budgets, and batch progress are computed in code. |
| Evaluation before threshold changes | Preserve `evals/` cases and compare provider/model changes before tuning Choice or Noul gates. Pin a Jev model only after calibrating those thresholds against Zearch's cases. |

The showcase's Smart Home fixture and agent routing labels are demonstrations, not search data; importing them would not improve the search index. Monitor diffs are candidates for review even when Jev generated a new cited answer. Future semantic change scoring should use a bounded Jev fan-out over old and new passages with a separate budget and calibration set; the current monitor deliberately uses deterministic text changes.
