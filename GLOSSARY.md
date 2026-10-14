# Glossary

Domain terms used in Metis-Auto docs, code, and issues. Use these terms; avoid the listed synonyms. Requirements: [`docs/project/requirements.md`](docs/project/requirements.md). Last updated 2026-10-14 (Stage 1).

| Term | Meaning | Avoid |
|---|---|---|
| **Session** | An ordered conversation of user and bot messages, identified by a session ID. | "chat", "thread" |
| **Turn** | One user message plus the bot response(s) associated with it. | — |
| **Request** | What Metis-Auto answers: the current user message plus optional history, instructions, retrieved context, attachments, and structured-input config (FR-REQ-01). | "query" in code (fine in prose) |
| **Instructions** | The system-level text logged on bot messages. It is *not proven* to be the provider system prompt (A-03). | "system prompt" (unless proven) |
| **Retrieved context (RAG)** | The logged `rag.context` strings. A missing `rag` means **unknown**, not "no retrieval" (FR-REQ-04). | — |
| **Attempt** | One unit of work for a request: a cache lookup or a model call, including escalations and failovers. Each has its own ID. | "try", "call" (ambiguous) |
| **Pairing** | The heuristic link from a bot record to its request in logged data: the latest preceding user message by array order. It always carries a pairing-quality flag. | "request log", "1:1" |
| **Model label** | A logged `model` string. It is not a billing entity (A-07). | "model" when the label is meant |
| **Catalogue** | Versioned configuration of the models Metis-Auto may use, with verified capabilities and equivalence groups. | — |
| **Routing decision** | The chosen target model, with candidates, policy version, reason, and features (FR-ROUTE-02). | — |
| **Policy** | A pure, configurable decision component (routing, cache validity, context, escalation). | "strategy" is fine as a synonym in experiment docs |
| **Escalation** | Moving to a *stronger* model because an answer was unsatisfactory (quality). | "fallback" |
| **Failover** | Moving to an *equivalent* model or provider because a call failed (reliability). | "fallback", "retry" |
| **Cascade** | A configured chain of models tried cheapest first, with escalation between them. | — |
| **Cache key composition** | Which components (normalised request, instructions, history, RAG, model, attachments, scope) form a cache key. | — |
| **Sharing scope** | Which requests may reuse a cache entry: `session`, `user`, or `global`. The serving default is `session` ([ADR-0007](docs/adr/0007-cache-sharing-scope.md)). | — |
| **Candidate hit** | A key match found in offline analysis, with no evidence that serving it would be correct. | "hit" (for offline sample results) |
| **Hit correctness / false hit** | Whether a served cached answer was valid for the new request; a false hit is one that was not. | — |
| **Overhead** | Cost and latency added by Metis-Auto itself: features, cache lookup, routing, embeddings, judges. | — |
| **Fidelity** | How a token count or cost was obtained: provider-reported, exact local tokenizer, counting API, or approximation. | "accuracy" |
| **As-logged baseline** | What the logged model labels actually did (ADR-0002). | — |
| **Premium baseline** | A single configured premium model used for every request. Currently a placeholder (ADR-0002). | — |
| **Agreement** | Similarity of an answer to the as-logged answer. It is **not** quality (ADR-0006). | "quality", "accuracy" |
| **Counterfactual source** | How a run obtains answers the logs don't contain: new calls, recorded/mocked responses, or proxy metrics. | — |
| **Opaque category** | One of the four unnamed data strata. Never interpreted (A-02). | category names as meanings |
| **Run mode** | Whether an event came from replay, simulation, or live traffic. | — |
