# Jev-only architecture

**Product invariant:** Jev is Zearch's only AI model. Search providers retrieve documents; ordinary code ranks and extracts candidate passages; Jev evaluates typed questions and selects one candidate or abstains. No text-generating model writes the answer. The UI presents a selected source excerpt with a citation and a brief deterministic explanation of how to read it.

TypeSafe's Jev API accepts `state`, `model`, and `questions` at `/v1/systemone`; Choice, Noul and Score produce structured values and probabilities. Jev does not generate free-form prose. The product can have a familiar conversational layout and follow-up retrieval while remaining honest about that limitation. Sources can be wrong; a selected passage is not a verified claim.

## Pipeline

1. Reserve global/session research budget and create a durable run.
2. Retrieve and deduplicate public web evidence; include private text notes only on explicit opt-in.
3. Extract bounded passages deterministically. Submit question and candidates as state to Jev in **one** call with a best-passage Choice plus sufficiency and conflict Noul questions.
4. Require the selected ID to match a supplied candidate and enforce sufficiency/choice gates. If evidence is insufficient, abstain. If candidates may conflict, ask the user to review them.
5. Compose only fixed UI phrases and the selected exact excerpt. Store the validated typed judgment, model, tokens, source snapshot and cost estimate. Cite the source; mark private notes clearly.

Jev never invents an answer sentence. At this stage it does not synthesize a multi-source essay or do extended reasoning. Deep mode retrieves more candidate documents but still makes a bounded single Jev judgment. Rich original prose would require a different model or a future generation capability from TypeSafe, which would change this invariant and require an explicit product decision.

References: https://docs.typesafe.ai/introduction and https://docs.typesafe.ai/introduction/quickstart.
