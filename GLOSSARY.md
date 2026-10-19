# Glossary

Domain terms used in Metis-Auto docs, code, and issues. Use these terms; avoid the listed synonyms. Requirements: [`docs/project/requirements.md`](docs/project/requirements.md). Last updated 2026-10-19 (Demo milestone A).

| Term | Meaning | Avoid |
|---|---|---|
| **Session** | An ordered conversation of user and bot messages, identified by a session ID. | "chat", "thread" |
| **Turn** | One user message plus the bot response(s) associated with it. | — |
| **Request** | What Metis-Auto answers: the current user message plus optional history, instructions, retrieved context, attachments, and structured-input config (FR-REQ-01). | "query" in code (fine in prose) |
| **Instructions** | The system-level text logged on bot messages. It is *not proven* to be the provider system prompt (A-03). | "system prompt" (unless proven) |
| **Retrieved context (RAG)** | The logged `rag.context` strings. In the sample, a missing `rag` key means **absent** (the export lists it only when present; Q-37, 2026-10-19); a value the log can't tell is **unknown**, never "no retrieval" (FR-REQ-04). | — |
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
| **Port** | An interface (in `metis_auto.ports`) for a swappable boundary: provider client, cache store, embedder, tokenizer, event sink, judge, data source ([ADR-0009](docs/adr/0009-repository-structure-and-dependency-rules.md)). | "service", "driver" |
| **Adapter** | A concrete implementation of a port: fake, recorded, or live provider client, store, sink, or backend. It contains no business rules. | "client" (when the abstraction is meant) |
| **Composition root** | `metis_auto.wiring`: the only place that builds concrete objects from configuration and injects them. | "factory" (too generic) |
| **Promotion** | Moving a candidate strategy from `experiments/` into `src/metis_auto/` after it passes the promotion criteria (evidence, tests, config entry, docs, decision record). | "merging the experiment" |
| **Measurement** | Anything the pipeline obtains through a port (token counts, embeddings, model-based features, judge scores). Taken in `application` and passed to `domain` as data (principle P-1, [ADR-0010](docs/adr/0010-request-pipeline-shape.md)). | — |
| **Attempt kind** | Why an attempt happened: `primary`, `retry`, `failover`, or `escalation` ([ADR-0013](docs/adr/0013-unified-attempt-model.md)). | — |
| **Attempt policy** | The pure policy that chooses the next attempt, or returns or fails, from the state of all attempts so far. | "retry logic" |
| **Detector** | A pluggable check that flags a successful answer as unsatisfactory. Its verdict records value and threshold. | "validator" |
| **Equivalence group** | Catalogue models that are interchangeable for failover. Declared in config, never inferred. Also a cache-key component. | — |
| **Partition key** | Every cache-key component except the current message. The semantic tier matches it exactly ([ADR-0011](docs/adr/0011-cache-key-and-lookup-design.md)). | — |
| **Fingerprint** | A keyed hash of content, used in place of content in keys, events, and reports ([ADR-0015](docs/adr/0015-keyed-content-fingerprints.md)). | "hash" when content is meant |
| **Composition record** | Per-component sizes, fingerprints, and actions (kept, trimmed, summarised, dropped) for one model input. No content. | "prompt log" |
| **Coverage** | In an evaluation run, the fraction of cases for which the counterfactual source produced an answer ([ADR-0014](docs/adr/0014-counterfactual-answers-via-model-client.md)). | — |
| **Span** | A timed stage of a request (e.g. `route`, `cache_lookup.exact`, `model_call`). Overhead is the sum of pre-model spans. | — |
| **Contract** | A typed data model passed between components, in `metis_auto.contracts` ([contracts.md](docs/architecture/contracts.md), [ADR-0017](docs/adr/0017-contract-modelling-with-pydantic.md)). | "DTO", "schema" (for the models) |
| **Component state** | Whether an optional request component is `present`, `absent`, or `unknown` (P-6). Request components default to `unknown`. | "null", "empty" |
| **Privacy class** | The sensitivity of a contract field: `content`, `fingerprint`, `reference`, `derived`, or `operational` ([contracts.md §2.2](docs/architecture/contracts.md#22-privacy-classes)). Only `content` must stay inside the content boundary. | "PII level" |
| **No answer** | A model result meaning the counterfactual source has nothing for this target (`ModelNoAnswer`). It lowers coverage; it is not an error. | "miss", "error" |
| **Key ID** | A short identifier of the fingerprint key (`kid1:…`), recorded so fingerprints made with different keys are never compared. | — |
| **Walking skeleton** | The whole request pipeline running end to end offline with fakes and synthetic data, before real strategies exist (`metis_auto.wiring.walking_skeleton`, Stage 5). | "prototype", "demo" |
| **Cache key draft** | A composed cache key before fingerprinting (`CacheKeyDraft`). The cache policy builds it; the measurement service seals it into a `CacheKey` with the fingerprint key. | — |
| **Swap point** | A place where an implementation is chosen by configuration: a `ports` protocol or a domain policy interface plus a `wiring` registry entry ([module_reference.md](docs/architecture/module_reference.md#swap-points-qa-repl-one-interface--one-config-entry)). | "plugin" |
| **Settings layer** | One source of configuration in the precedence order: policy code defaults, `config/defaults.toml`, an experiment file or run profile, the runtime file (`config/local.toml`), `METIS__*` environment overrides, caller overrides ([ADR-0019](docs/adr/0019-configuration-format-layers-and-secrets.md)). | "config level" |
| **Run profile** | A versioned settings file loaded at the experiment layer for a fixed purpose, e.g. `config/profiles/walking_skeleton.toml`. | — |
| **Config hash** | `cfg1:` + 16 hex of SHA-256 over the non-secret, non-local settings plus reference version IDs; recorded in every event's `Versions`. | "settings ID" |
| **Spend ledger** | The persistent, cumulative record of live spend (`data/spend/ledger.jsonl`) that enforces the lifetime and per-run caps across all runs ([ADR-0018](docs/adr/0018-live-calls-for-development-under-a-lifetime-budget.md)). | "budget file" |
| **Metis wrapper** | Metis's direct-to-model endpoints (one API key, one base URL per model family) used for live calls ([metis_wrapper_api.md](docs/references/metis_wrapper_api.md)). | "Metis bot API" (a different product) |
| **Tokenizer table** | `config/reference/tokenizers.toml`: for each catalogue `tokenizer_ref`, the backend, the pinned file (URL, sha256), the fidelity, the evidence, and the chat template ([token_accounting.md §2](docs/architecture/token_accounting.md)). | — |
| **Tokenizer asset** | A tokenizer file fetched once by `scripts/fetch_tokenizer_assets.py`, pinned by sha256, stored under `data/tokenizers/` (git-ignored). Never downloaded at run time. | "model download" |
| **Chat template** | The framing tokens a provider adds around each message (role markers, BOS, reply priming); counted as **template overhead**, an approximation until checked against reported usage. | "prompt template" (that is the instructions) |
| **Context tier** | A price band chosen by a call's input tokens (e.g. gpt-5.4's ≤ 270,000 and long-context rows); it prices every token type of the call. | "context window" (a model limit) |
| **Cost caveat** | A code on a computed cost naming a known way it may differ from the bill, e.g. `reasoning_not_counted` (lower bound) or `answer_length_assumed` (baseline estimate). | — |
| **Premium-baseline estimate** | The premium model's cost on the full, uncompressed context with the served answer re-counted by its tokenizer; never a call (brief §5). | "premium cost" (it is an estimate) |
| **Savings decomposition** | premium baseline − routing − compression − cache − provider-cache savings + extra cost = actually paid, per message and per session, exact in Decimal (brief §6, ADR-0020). | — |
| **Extra cost** | The decomposition's remainder: Metis overhead, failed, retried, and escalated attempts, and local-vs-reported count differences. | "error term" |
| **EXP-ID** | An experiment's ID, `exp-<area>-<nnn>` (`cache`, `route`, `ctx`, `cost`, `eval`); its folder is `experiments/<area>/<EXP-ID>-<slug>/` (framework.md §2). | "experiment number" |
| **Candidate hit** | An offline match between a request and an earlier cached (logged) answer under a key variant; not a safe hit until hit correctness is measured (ADR-0006). | "cache hit" (for offline results) |
| **Key variant** | One key composition × message treatment × unknown treatment, e.g. `msg_only.lit.strict`; narrow variants are measurement only (P-5). | — |
| **Unknown as wildcard** | A measurement-only key rule: an unknown component matches anything, bounding the opportunity hidden by unknowns; never a serving rule. | — |
| **Candidate index** | The swap point of cache-candidate experiments (`CandidateIndex`): stores earlier cases' key material and returns a match. | — |
| **Label mapping** | The reference file mapping a dataset's logged model labels to catalogue models, with a fidelity (`exact_id`, `alias`) or an unmapped reason; used by the as-logged baseline. | "model mapping" |
| **Producer** | Who produced an assistant turn: a catalogue model ID or `cache` (`Turn.producer`; absent for user turns, unknown when not recorded). Sticky routing reads it from the request (A-64). | "author" |
| **Sticky routing (v1)** | Routing that keeps a session on its **anchor** model while messages stay similar, re-routes and re-anchors on a very different message, keeps greetings on the anchor (or sends them to the cheapest model while unanchored), never letting them anchor, and raises the anchor on escalation (brief §7, ADR-0023). | "session routing" |
| **Anchor** | The model a sticky session stays on: set by the first substantive message, replaced on re-anchoring, raised (never lowered) by an escalation. Reconstructed from producers on every request. | — |
| **Substantive message** | A message that may anchor: not served from cache and not a greeting or small talk. Never "short = trivial". | "non-trivial" |
| **Coding intent** | A message that asks for code or programming help but contains no code: a configured keyword with a request cue ("how", «بنویس»), or a word template ("write ... function"). A placeholder feature (A-71), separate from code presence. | "code request" |
| **Greeting / small talk** | A short message made only of phrases from the configured Persian + English list (e.g. سلام, مرسی, hi, thanks). | — |
| **Effective cost** | Routing's expected cost of one answer on a model, with its expected hidden reasoning tokens billed as output (routing plan §3). | "price" (for this) |
| **Bot-level scope (demo)** | The DEMO cache setting that shares entries across users of one bot (global scope only when instructions are present). Not a serving option (ADR-0023). | "global cache" |
| **Demo seed** | DEMO ONLY: a few logged first-turn sample answers served on an exact message match, shown locally, never sent to a provider. | — |
