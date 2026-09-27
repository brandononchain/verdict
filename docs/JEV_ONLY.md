# Jev-guided research architecture

Zearch originally used Jev as its only model. The product decision now permits a separate prose writer. Jev remains the decision model: it selects relevant evidence, judges sufficiency and conflict, and checks a completed draft. The writer has no search tools and may only read Jev-selected source snapshots. The name of this file preserves links from earlier releases.

## Interactive path

1. Reserve a bounded daily operational budget and persist a run ID.
2. Retrieve up to three search queries, deduplicate URLs and content, and rank candidates lexically. With `ZEARCH_ENRICHMENT_ENABLED=1`, request rendered Markdown and metadata for up to three ranked public pages via Context.dev. A failed extraction keeps the search provider's text.
3. Submit bounded excerpts to Jev with a best-passage Choice, sufficiency/conflict Noul questions, and relevance Noul questions. Abstain on insufficient evidence and show a source excerpt for disputed evidence.
4. Give up to four Jev-selected sources to the OpenAI Responses API with `store:false` and a 900 output-token cap. Require each of at most three paragraphs to cite a selected numeric source ID.
5. Submit the entire drafted answer and cited source text to Jev. Release the prose only if every paragraph clears the support threshold. Otherwise return the exact selected excerpt. Save source snapshots, typed probabilities, provider usage, and estimated cost.

The second Jev judgment is a probabilistic support check, not a guarantee of truth or a formal proof. Citation numbers only point to stored snapshots. Search ranking is lexical; this is not an exhaustive web index or an AGI claim. Source content is untrusted and must not supply instructions. No raw draft is sent to the client before Jev checks it.

## Context-like data roadmap

The live adapter uses the public Context.dev scrape endpoint as an optional upstream service. We reproduce useful behavior in Zearch's own pipeline and never copy proprietary service code: bounded extraction, source metadata, content fingerprints, citation snapshots, and recurring investigation diffs. The current adapter does not provide our own browser fleet, proxy pool, universal extraction schema, batch scheduler, or robust semantic change detection.

Next, add an owned URL inventory with per-domain freshness policy and robots/terms compliance; a durable extraction queue and cache keyed by canonical URL, content hash and timestamp; typed schema extraction with validation and source spans; and scheduled monitors that compare normalized content before rerunning Jev. Treat private/person enrichment as a separate opt-in feature with retention and provenance rules. Separate the crawler's operating cost and rights policy from answer-model costs.

References: https://docs.context.dev/introduction, https://docs.context.dev/agent-quickstart, https://developers.openai.com/api/reference/cli/resources/responses/methods/create.
