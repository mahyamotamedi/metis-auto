# Metis-Auto — Requirements, Quality Attributes, and Scope (Stage 1)

Status: **provisional** as a whole until Stage 1 review; each item carries its own status. Last updated 2026-10-14.
Related: [context](context.md) · [assumptions & questions](assumptions_and_questions.md) · [progress](progress.md) · [glossary](../../GLOSSARY.md) · [ADR-0005 scope](../adr/0005-current-phase-scope.md) · [ADR-0006 evaluation metrics](../adr/0006-evaluation-metric-definitions.md).

This document turns the project brief and the sample EDA into requirements. Every later design element (architecture section, contract, module, config file, experiment) must cite at least one ID from here or one hypothesis/experiment ID (§7).

---

## 1. How to read this document

**ID scheme.**
- `FR-<AREA>-NN` is a functional requirement.
- `QA-<NAME>` is a quality attribute.
- `NG-NN` is a non-goal.
- `BR-NN` is a brief requirement in the data-support map (§6).

**Source codes.**
- `B§x`: section of the [brief](../brief/project-draft.pdf).
- `MP§x`: section of the [master prompt](../../metis_claude_code_master_prompt.md).
- `F-n` / `H-n` / `U-n` / `C-n`: sample signals, hypotheses, unknowns, and conflicts in [context.md](context.md). `F-n` and other sample-EDA sources mean "**informed by**" a provisional signal, never "established by" ([ADR-0008](../adr/0008-sample-eda-is-exploratory.md)). No requirement depends on an exact sample value.
- `A-n` / `Q-n`: the [register](assumptions_and_questions.md).
- `ADR-n`: [decision records](../adr/).

**Kind** (master prompt §3.6):
- `current`: the architecture and contracts must satisfy it now, and the offline harness must support it where applicable.
- `future`: the design leaves an extension point but does not detail it.
- `spec`: speculative; noted only, and the design must not preclude it.

**Status:** `decided` · `provisional` (working answer, may change with evidence) · `open` (needs a decision or data).

**Phases** (see [ADR-0005](../adr/0005-current-phase-scope.md)):
- **Current phase:** offline foundation. Architecture, contracts, skeletons, offline replay, accounting, and the exact-cache baseline.
- **Online phase:** a later gateway serving live traffic with the same policies.

Unless a requirement says otherwise, it applies to both phases. Wherever "configurable" appears, the value is configuration, not code (MP§4).

---

## 2. Goals

| ID | Goal | Source |
|---|---|---|
| G-1 | Lower the cost of answering requests. | B§1, B§2 |
| G-2 | Do so without materially lowering response quality. "Material" is defined provisionally in QA-QUAL (Q-13). | B§1, MP§1 |
| G-3 | Do so without materially raising latency. The overhead budget is defined provisionally in QA-LAT (Q-14). | B§1, MP§1 |
| G-4 | Remove manual model choice from users and applications. | B§2 "decision fatigue" |
| G-5 | Hide provider fragmentation behind one highly available entry point. | B§2 "API fragmentation" |
| G-6 | Make tokens, cost, savings, latency, quality, and routing decisions observable. | B§2 "unit economics", B§3.3 |
| G-7 | Generalise across the four opaque usage categories rather than fit one. | B§4, A-02 |

Every goal must be *demonstrated with evidence*. None is assumed to be achievable (MP§1).

---

## 3. Functional requirements

### 3.1 Request model and identity (`FR-REQ`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-REQ-01 | A request consists of the current user message plus optional: conversation history, instructions (system-level text), retrieved context, attachments (type and reference), and structured-input configuration. Each component may be **present**, **absent**, or **unknown**. | B§4, data overview, C-03, C-04 | current | decided |
| FR-REQ-02 | The system mints its own IDs: request, session, and one ID per *attempt* (cache lookup, model call, escalation, failover). All attempts link to their request. | A-05, EDA "full dataset" list | current | decided (names fixed in Stage 4, [contracts.md §2.4](../architecture/contracts.md#24-identifiers-and-correlation-a-05)) |
| FR-REQ-03 | Offline replay builds requests from logged sessions using a pairing heuristic (A-04), re-implemented and tested rather than taken from the EDA helpers (FR-DATA-08). It carries a **pairing-quality flag** per request (clean / multiple bots / no preceding user / skipped consecutive user) and never presents pairs as a clean 1:1 log. | A-04, context §4 | current | decided |
| FR-REQ-04 | "Unknown" is distinct from "absent". For example, a missing `rag` field in logged data is *unknown retrieval state*, not *no retrieval*. Null model/instructions are unknown. | C-04, F-3 | current | decided |
| FR-REQ-05 | Logged timestamps are carried as naive values with timezone marked unknown. The online phase records timezone-aware UTC. Analyses state which timestamp (`created_at` vs message) they use. | A-06, C-01 | current | provisional |
| FR-REQ-06 | Offline replay processes each session's turns in order, and only uses information available before each turn (no look-ahead into later turns or the logged answer, except as the evaluation reference). | MP§4 offline-first, counterfactual problem | current | decided |

### 3.2 Feature extraction (`FR-FEAT`)
Feature extraction is shared by routing, caching, context handling, and evaluation stratification.

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-FEAT-01 | Extract cheap, deterministic features per request:<ul><li>language/script mix (Persian, English, mixed, other)</li><li>length (chars, plus a token estimate with its method)</li><li>code presence</li><li>attachment presence, type, and count</li><li>turn depth and history size</li><li>instruction presence, size, and hash group</li><li>RAG presence and size</li><li>structured-input proxy presence</li></ul> | B§3.1, F-1…F-5, A-08 | current | decided (exact feature set provisional) |
| FR-FEAT-02 | Provide a **semantic-intent** feature. The method is open: embedding clusters, a small classifier, or an LLM call. Its cost and latency count as overhead (FR-ROUTE-04). | B§3.1 | current | open |
| FR-FEAT-03 | Language detection is a first-class, tested component that handles Persian/Arabic-script ambiguity and mixed text. | B§4 ("core part of the task"), F-2 | current | decided |
| FR-FEAT-04 | Features are pure functions of the request and configuration. Each output records its feature-set version. | MP§4 (pure policies) | current | decided |
| FR-FEAT-05 | Features are derived values or hashes, never raw content. | A-09, CLAUDE.md | current | decided |

### 3.3 Routing (`FR-ROUTE`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-ROUTE-01 | Given features, the model catalogue, and a policy configuration, select a target model and provider for each request that is not served from cache. | B§3.1 | current | decided |
| FR-ROUTE-02 | Every routing decision records: the chosen target, the eligible candidates, the policy name and version, a machine-readable reason, and references to the features used. | B§2 ("track … routing decisions"), U-06 | current | decided |
| FR-ROUTE-03 | Routing policies are interchangeable behind one interface and selected by configuration. Required now: a **fixed-model** policy (it implements the baselines) and a **rule-based** policy. Classifier, embedding, learned, and LLM-based routers are experiments. **No winner is pre-selected.** | MP§5 Stage 8, ADR-0002 | current | decided |
| FR-ROUTE-04 | Router overhead is measured and attributed separately from the answering model: feature extraction, any embedding, and any model call the router makes. This covers both latency and cost. | B§3.1 constraint | current | decided |
| FR-ROUTE-05 | Only models whose catalogue entry supports the request are eligible. This covers attachment modality, context length, and any other declared capability. A capability that the catalogue has not verified counts as **unsupported** for eligibility, and the decision is flagged. | MP§3.8 (no fabricated capabilities), C-06 | current | provisional |
| FR-ROUTE-06 | An application or user may explicitly request a model. Whether and how a policy honours that is configurable. | U-05 (unknown whether users chose models) | future | open |
| FR-ROUTE-07 | The same policy code runs in offline replay and in the online phase without rewriting. | MP§4 | current | decided |

### 3.4 Exact cache (`FR-XCACHE`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-XCACHE-01 | Serve a stored response when a new request's cache key exactly matches a stored entry **and** every validity rule passes. | B§2, H-3 | current | decided |
| FR-XCACHE-02 | Key composition is configurable. It always includes the normalised request, plus a chosen subset of hashes of: instructions, history (full or windowed), RAG context, routing target/model, attachments, and a scope (FR-XCACHE-05). The **default for serving is the conservative full composition**. Narrower keys exist for measurement only, until evidence justifies serving with them. | F-6, F-7, MP§2 caching signal | current | decided |
| FR-XCACHE-03 | Request normalisation is configurable: literal, whitespace-collapsed, or NFKC+casefold+whitespace. These are the EDA variants. | EDA methodology | current | decided |
| FR-XCACHE-04 | Validity rules are configurable. Defaults:<ul><li>a TTL;</li><li>requests with attachments are **not** eligible (their content is unseen; A-19);</li><li>only completed, non-error, non-truncated responses are stored;</li><li>a time-sensitivity rule, whose method is open.</li></ul> | U-08, TODO-07 | current | provisional |
| FR-XCACHE-05 | Every entry has a configurable **sharing scope**: `session`, `user`, or `global`. Instruction group is a key component (FR-XCACHE-02), not a scope. The **serving default is `session`** for anything that serves users. Offline experiments measure **cross-session** and **cross-user** reuse candidates **separately**, to size the opportunity before a decision. The final policy is an open product/privacy decision (Q-16). The sample has no user identifier (B§4), so cross-user candidates can only be measured once the data has a privacy-safe user ID. | B§4 (users not distinguished), F-6 (11 groups cross sessions), Q-16 | current | decided (default and configurability); open (final policy) |
| FR-XCACHE-06 | Every lookup emits an event recording: eligibility (and the reason if ineligible), key variant, hit/miss, and the matched entry ID. | MP§4 everything measurable | current | decided |
| FR-XCACHE-07 | Offline results report **candidate hits** per key variant, labelled as candidates and not safe hits. Each is paired with a hit-correctness estimate (ADR-0006). | F-7, C-09 | current | decided |
| FR-XCACHE-08 | The store sits behind an interface. In-memory now; persistent (e.g. PostgreSQL) after the full dataset arrives. | MP§5 Stage 8 | current (interface) / future (persistent) | decided |
| FR-XCACHE-09 | A cache store holds sensitive content. It needs a retention limit and an invalidation operation (by entry, by scope, by instruction group). | A-09 | future | provisional |

### 3.5 Semantic cache (`FR-SCACHE`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-SCACHE-01 | Serve a stored response when a new request is **similar enough** to a stored one and the same validity and scope rules as the exact cache pass. | B§3.2, H-4 | current (design) / future (implementation after exact baseline) | decided |
| FR-SCACHE-02 | Similarity applies only to the *request part*, and optionally recent history. All other key components (instructions group, model target, scope, RAG state) must match exactly unless an experiment justifies relaxing one. | F-7 | current | provisional |
| FR-SCACHE-03 | The embedder, similarity function, index/store, and threshold are each swappable by configuration. The embedder must handle Persian and mixed text. | A-08, MP§5 Stage 8 | current | decided |
| FR-SCACHE-04 | Thresholds are chosen from a measured hit-rate vs false-hit trade-off. They are never fixed in advance, and hit rate is never reported alone. | C-09, ADR-0006 | current | decided |
| FR-SCACHE-05 | Embedding cost and latency count as pipeline overhead in cost and latency metrics. | QA-COST, QA-LAT | current | decided |
| FR-SCACHE-06 | An optional answer-validity check (verifier) may run before serving a semantic hit. Its cost counts as overhead. | B§3.2 ("conceptually identical") | spec | open |

### 3.6 Context construction and reduction (`FR-CTX`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-CTX-01 | A configurable context policy builds the model input from the request components. The system records the resulting **composition**: per component, its size, hash, and whether it was kept, trimmed, summarised, or dropped. It records no content. | U-04, F-4 | current | decided |
| FR-CTX-02 | Context strategies are swappable. **Pass-through** is the reference. Experimental strategies:<ul><li>history windowing</li><li>history summarisation</li><li>RAG trimming</li><li>instruction deduplication or compaction</li><li>stable-prefix ordering, to benefit from provider-side prompt caching where a provider supports it</li></ul> | H-1, H-2 | current | decided (strategies are experiments) |
| FR-CTX-03 | No reduction strategy is promoted without a quality-preserving ablation against pass-through (QA-QUAL). | MP§5 Stage 8 | current | decided |
| FR-CTX-04 | When the built input exceeds the target model's context limit (from the catalogue), a configurable overflow rule applies: trim, re-route to a larger-context model, or reject. An event is emitted. | MP§3.8 | current | provisional |
| FR-CTX-05 | Claims about provider-side prompt caching (eligibility, discount, minimum prefix) come only from verified provider documentation, with source and date. | MP§3.8 | current | decided |

### 3.7 Cascade and escalation (`FR-CASC`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-CASC-01 | Optionally answer with a cheaper model first, and escalate to a stronger one when an *unsatisfactory-response* signal fires. | B§3.2, H-6 | current (design) | decided |
| FR-CASC-02 | Unsatisfactory-response detectors are pluggable. Candidate signals:<ul><li>provider error, refusal, empty, or truncated output (finish reason)</li><li>language mismatch with the request</li><li>format or validation failure</li><li>length heuristics</li><li>confidence signals, where a provider exposes them (verify first)</li><li>a judge model's score</li></ul>Which signals are usable is **open**. | U-07, TODO-06 | current | open |
| FR-CASC-03 | The escalation chain, maximum depth, and a per-request deadline are configurable. | QA-LAT | current | provisional |
| FR-CASC-04 | Every attempt's tokens, cost, and latency are charged to the request, including discarded answers. | QA-COST | current | decided |
| FR-CASC-05 | Each escalation emits an event with the triggering detector, its value, and the threshold. | MP§4 | current | decided |

### 3.8 Failover and retries (`FR-FAIL`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-FAIL-01 | On a provider failure (error, timeout, rate limit, unavailability), retry or fail over to an **equivalent** model on another provider, per configuration. | B§3.2, A-15 | current (design) | decided |
| FR-FAIL-02 | Failover and escalation are distinct. Failover keeps the capability tier, for reliability. Escalation raises the tier, for quality. Both are recorded with distinct event types. | Glossary | current | decided |
| FR-FAIL-03 | Model equivalence groups for failover are declared in catalogue configuration. They are never inferred from labels. | A-07, C-02 | current | decided |
| FR-FAIL-04 | Retries are bounded (count, backoff, timeout). Every attempt is recorded. | EDA "full dataset" list | current | decided |
| FR-FAIL-05 | Provider health tracking (e.g. circuit breaking) to skip known-down providers. | B§2 | future | provisional |
| FR-FAIL-06 | Failure behaviour is testable offline through fault-injecting fake adapters. | ADR-0003 | current | decided |
| FR-FAIL-07 | The availability target is unknown (A-15, Q-04). The design must not claim an SLA. | C-10 | current | open |

### 3.9 Token and cost accounting (`FR-ACCT`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-ACCT-01 | For each model call, report input, output, and total tokens, plus cached-input and reasoning tokens where they are reported. Each count carries its **method/fidelity**: provider-reported, exact local tokenizer, provider counting API, or approximation. | MP§5 Stage 7, U-01, H-7 | current | decided |
| FR-ACCT-02 | Cost = tokens × price from a **versioned price table**. Each entry has: model, token type, unit, currency, effective date, source, and check date. An unknown price yields **"not computed"**, never zero and never a guess. | MP§3.8, ADR-0002 | current | decided |
| FR-ACCT-03 | Request cost sums every attempt (answer, escalation, failover, failed calls) and all overhead (router, embeddings, judge, verifier). | QA-COST | current | decided |
| FR-ACCT-04 | A cache hit records **avoided cost** as a counterfactual estimate. The estimate states its method: which model it assumes and how tokens were counted. | B§3.3 ("tokens saved via caching") | current | decided |
| FR-ACCT-05 | Savings = baseline cost − actual cost, against both baselines (ADR-0002). An unset premium baseline yields "not computed". | ADR-0002 | current | decided |
| FR-ACCT-06 | Provide a pre-call cost estimate for the live-run spending cap. | ADR-0003 | current | decided |
| FR-ACCT-07 | Logged model labels map to priced models through a curated mapping. Each mapping carries a fidelity. Labels such as `default`/`workflow` and null labels are unmapped unless the data owner explains them. | A-07, A-16, C-02 | current | decided |

### 3.10 Observability (`FR-OBS`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-OBS-01 | Emit structured, request-correlated events at every decision point: request received, features extracted, cache lookup (exact and semantic), routing decision, context built, model attempt start and end, escalation, failover, response returned, and evaluation result. | B§2, MP§4 | current | decided |
| FR-OBS-02 | Each event carries: IDs (FR-REQ-02), a timestamp, the lifecycle span it measures, durations, the versions in force (policy, config, feature set, price table, catalogue), and a run ID. It carries **no raw content**: hashes and derived values only. | A-09, MP§4 | current | decided |
| FR-OBS-03 | One event schema is shared by offline replay and the online phase. A run-mode field distinguishes replayed, simulated, and live events. | MP§4 | current | decided |
| FR-OBS-04 | The event model can produce every field in the EDA's "Requirements for the Full Dataset" list ([eda_results.md](../sample_eda/eda_results.md)). | MP§2 | current | decided |
| FR-OBS-05 | Everything the deferred dashboard would need must be derivable from events alone, so the dashboard can be added later **without redesigning the event model** (Q-17). That means: tokens, cost, savings (both baselines), latency per span, and routing decisions with their reasons. Aggregates include These are: tokens and cost saved by caching, cost reduction from routing, latency distribution, routing mix, hit and false-hit rates, escalation rate, and failover rate. | B§3.3 | current (derivation) / future (UI) | decided |
| FR-OBS-06 | The event sink is pluggable. Local files (e.g. JSON Lines) now; a database or metrics backend later. "Real-time" display is an online-phase concern. | B§2 ("in real time"), ADR-0005 | current (interface) / future (real-time) | provisional |

### 3.11 Evaluation (`FR-EVAL`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-EVAL-01 | An offline replay harness runs the request pipeline over dataset sessions (FR-REQ-03, FR-REQ-06). Provider adapters are fake, recorded, or (opt-in) live. | MP§4, ADR-0003 | current | decided |
| FR-EVAL-02 | Baselines: **as-logged** (mandatory) and **single premium model** (a configurable placeholder until Q-05 is resolved). Further baselines, such as always-cheapest, are configuration. | B§4.1, ADR-0002 | current | decided |
| FR-EVAL-03 | Metrics, as redefined in ADR-0006:<ul><li>quality (agreement with as-logged, plus judge scores where feasible)</li><li>cache hit rate together with hit correctness</li><li>cost per request vs. baselines</li><li>latency vs. baseline, split into measurable overhead and live-only end-to-end time</li><li>escalation rate, failover rate, and router overhead</li></ul> | B§4.1, C-07…C-09 | current | decided |
| FR-EVAL-04 | Each run declares its **counterfactual source**: new calls, recorded/mocked responses, or proxy metrics. Results show it. | context §8 | current | decided |
| FR-EVAL-05 | Judges are pluggable and versioned. LLM-as-a-judge is optional and opt-in (it costs money and sends data out). Judge bias is stated. Calibration against a human-labelled subset is planned. | B§4.1, ADR-0003, TODO-05 | current (interface) / future (calibration) | provisional |
| FR-EVAL-06 | Results are reported overall **and per stratum**: opaque category, language, length bucket, turn depth, and presence of RAG, instructions, or attachments. A result that holds overall but fails in one stratum must be visible. | B§4 (generalise), A-02 | current | decided |
| FR-EVAL-07 | Runs are reproducible. Each records its configuration, code version, data hash, seed, and component versions. | MP§5 Stage 8 | current | decided |
| FR-EVAL-08 | Each run reports how many records were excluded or flagged because of pairing quality or unknown metadata. | A-04 | current | decided |
| FR-EVAL-09 | Small-sample results carry their sample sizes and uncertainty intervals (e.g. bootstrap). With 100 sessions, many strata are tiny. | data overview | current | provisional |

### 3.12 Data handling (`FR-DATA`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-DATA-01 | `data/sample_data/raw/` is read-only. Derived data is written elsewhere, and the raw file's hash is checked by tests. | CLAUDE.md | current | decided |
| FR-DATA-02 | Data access goes through an interface. Nothing outside the data layer depends on storage location or format. | MP§5 Stage 9 | current | decided |
| FR-DATA-03 | Synthetic fixtures model the domain generically: multilingual with Persian well represented, multi-turn, and optional RAG, attachments, and instructions. They do **not** reproduce sample-specific quirks. They contain no real content and are clearly labelled synthetic. | CLAUDE.md, MP§5 Stage 9, ADR-0008 | current | decided |
| FR-DATA-04 | Onboarding the full dataset needs changes only in the data layer and configuration. | MP§5 Stage 9 | future | decided |
| FR-DATA-05 | No final persistent schema is designed before the full dataset is inspected. **Met 2026-11-01:** the full EDA is done; a local (not production) schema exists under [ADR-0027](../adr/0027-local-postgresql-foundation.md). | MP§1 | current | decided |
| FR-DATA-06 | Contracts and data interfaces are not shaped around sample quirks. Sample-specific handling lives in a sample loader/adapter. | ADR-0008 | current | decided |
| FR-DATA-07 | Full-dataset onboarding begins with a full EDA in its own home, separate from the sample EDA. It uses re-implemented, tested analysis code, and re-checks every sample signal and the data-owner questions. | ADR-0008 | future | decided |
| FR-DATA-08 | No system code imports, copies, or builds on the sample-EDA helpers. Needed analysis logic (language detection, normalisation, pairing, near-duplicates, size estimates) is re-implemented with tests. | ADR-0008 | current | decided |

### 3.13 Unified interface and provider adapters (`FR-API`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-API-01 | There is one entry point that takes a request and returns a response plus metadata, hiding provider differences. In the current phase this is an in-process Python API used by replay and by the smoke test. | B§2, ADR-0005 | current | decided |
| FR-API-02 | Provider adapters normalise request format, response, usage, finish reasons, and error types into internal contracts. Provider specifics never leak into policies. | MP§4 provider-agnostic core | current | decided |
| FR-API-03 | A network gateway exposing FR-API-01, implemented as a **separate external-API adapter layer** that translates a wire format into internal contracts. Provisional default wire format: **OpenAI-compatible chat-completions style**. Its exact field coverage is to be verified against public documentation when the gateway is in scope, never assumed. Whether this matches what production Metis clients use is unknown (Q-15). Internal contracts must not depend on the wire format. | B§2, Q-15 | future | provisional |
| FR-API-04 | Streaming responses (and time-to-first-token as a metric). | EDA "full dataset" list (TTFT) | future | open |

### 3.14 Financial model and dashboard — brief Action 3, optional (`FR-FIN`)

| ID | Requirement | Source | Kind | Status |
|---|---|---|---|---|
| FR-FIN-01 | A pricing model (fixed subscription vs. dynamic) showing end-user economics vs. premium-direct. It needs verified prices and full-dataset volumes. | B§3.3 | future | provisional (deferred, ADR-0005) |
| FR-FIN-02 | A user-facing dashboard UI. Its data enabler (FR-OBS-05) is current; the UI is not. | B§3.3 | future | provisional (deferred, ADR-0005) |

---

## 4. Quality attributes and how each is measured

Thresholds are **configuration and open questions**, not numbers invented here. "Offline" means the replay harness with fakes or recorded responses; "live" means opt-in real calls under the spending cap (ADR-0003).

| ID | Attribute | Metric(s) | How measured · data source | Phase | Target | Caveats |
|---|---|---|---|---|---|---|
| **QA-COST** | Cost per request | Mean and total cost per request; savings vs. as-logged and vs. premium baseline (absolute and %); cost broken down by component (answer, escalation, failover, overhead); avoided cost from cache. | FR-ACCT over replayed or live runs. Tokens come with a fidelity label, prices with source and date. | Offline (estimated), live (reported usage) | Open: "lower than both baselines at acceptable quality" | Depends on prices (TODO-02), tokenizer fidelity (H-7), and true prompt composition (U-04). An unknown price is "not computed". |
| **QA-QUAL** | Response quality | (1) **Agreement** with the as-logged answer: similarity from a Persian-capable embedding model. (2) Judge score (LLM or human) on a stratified subset. (3) Non-inferiority vs. a baseline. (4) Cache hit correctness (QA-QUAL applies to served cache hits too). **Primary signal: LLM-as-a-judge**, calibrated against a small human-rated set. Agreement (1) is **secondary only**. | Offline with recorded or new answers. A judge is opt-in (it costs money). Human ratings are needed for calibration. | Offline / live | **Provisional (Q-13):** mean judge score drops ≤ 3% vs. baseline overall, **and** no stratum (opaque category, language) drops > 5%. Revisit with the full dataset. | Logged answers are not gold (C-07). Pairing is heuristic. A judge has its own biases. Agreement measures similarity, not correctness. |
| **QA-LAT** | Latency | (a) **Pipeline overhead**: wall-clock of feature extraction, cache lookup, routing, and context building, p50/p95. (b) **Model latency**: TTFT and total per attempt. (c) **End-to-end** = (a) + all attempts, vs. baseline. | (a) is measured offline on the local machine, with the hardware recorded. (b) and (c) are measured only live or with recorded latencies. Logged timestamp gaps are **not** used (F-9, C-08). | (a) offline; (b), (c) live | **Provisional (Q-14):** Metis's own overhead (a), excluding model response time, ≤ **100 ms at p95**. End-to-end tolerance is open. Revisit once real model latencies are measured. | Local overhead numbers are indicative only. Cascades add latency on escalation, which must be reported. |
| **QA-REL** | Reliability | Request success rate; failover rate; retries per request; behaviour under injected faults (each fault type → expected outcome). | Offline via fault-injecting fakes (FR-FAIL-06). Live failure rates come only from live runs or the full dataset. | Offline (behaviour), live (rates) | Availability target is open (Q-04, A-15) | The sample has no failure events. |
| **QA-PRIV** | Privacy | Zero raw content in events, logs, exported tables, fixtures, and commits. Data sent to external providers or judges happens only by opt-in. | Automated checks: tests assert that events and exports contain only allowed field types; review checklist at each stage. | Both | Zero violations | Content is treated as sensitive despite the brief's PII claim (C-12). The cache store holds content by necessity (FR-XCACHE-09). |
| **QA-REPL** | Replaceability | A new routing, cache, context, or judge strategy, embedder, tokenizer, store, price table, or provider is added by implementing **one interface plus one config entry**, with no edits to orchestration. | Checked at Stages 5 and 8 by adding a second implementation, and by an import-direction check (policies don't import adapters or experiments). | Both | Holds for every pluggable component listed in MP§3.9 | — |
| **QA-TEST** | Testability | Policies are pure and unit-tested. The pipeline smoke test runs offline with no keys. Network tests are opt-in only. | pytest. The CI-equivalent command runs with network disabled. | Both | All default tests pass offline | — |
| **QA-REPRO** | Reproducibility | The same config, code version, data hash, and seed give the same results. Run records are complete. | Run manifest (FR-EVAL-07). Re-running a recorded run reproduces its metrics. | Offline | Exact for offline runs with recorded responses | Live calls are non-deterministic; record their responses for re-use. |

QA-REPRO is added beyond the attributes the master prompt lists, because experiment comparability (Stage 8) depends on it.

---

## 5. Non-goals for the current phase

Recorded in [ADR-0005](../adr/0005-current-phase-scope.md). Each can be revisited by a new decision record.

| ID | Non-goal | Why / when it may return |
|---|---|---|
| NG-01 | Production deployment, or integration with production Metis systems, data, or code. | No access (MP§1). Later, by agreement. |
| NG-02 | A final **production** database schema. A local PostgreSQL for source data and evaluation datasets is in scope since 2026-11-01 ([ADR-0027](../adr/0027-local-postgresql-foundation.md)); no serving code reads it. | What Metis runs in production is unknown. |
| NG-03 | A network gateway: HTTP server, client authentication, multi-tenancy, client rate limiting. | Online phase (FR-API-03). |
| NG-04 | Live provider calls by default. | Opt-in only, with a cap (ADR-0003). |
| NG-05 | Brief Action 3: pricing engine and dashboard UI. | Optional in the brief. Needs verified prices and volumes. Its data enabler (FR-OBS-05) is in scope. |
| NG-06 | Choosing a winning routing or cache strategy, or training a production router. | Evidence comes from Stage 8+ experiments and the full dataset. |
| NG-07 | Understanding attachment content (image or audio analysis). Only presence, type, and count are used. | Future, if routing evidence calls for it (A-12). |
| NG-08 | Interpreting category names, or tuning for one category. | B§4, A-02. Permanent. |
| NG-09 | Streaming, tool/function calling, and structured-output passthrough. | Not in the data or brief. Future (FR-API-04). |
| NG-10 | Self-hosting or fine-tuning models. | Not in the brief. Speculative. |
| NG-11 | Running a human-labelling programme. Only the plan is in scope. | Needs people and budget (TODO-05). |
| NG-12 | Billing or invoicing end users. | Product concern outside the middleware. |
| NG-13 | Load, scale, or high-availability infrastructure testing. | Online phase. |

---

## 6. Brief requirements → what can support them

Legend:
- **Sample now:** what the 100-session sample supports today.
- **Full dataset:** what needs the larger dataset (assuming it carries the EDA's requested fields; Q-11).
- **Live calls:** what needs real provider calls (opt-in, ADR-0003).

| ID | Brief requirement | Sample now | Full dataset | Live calls | Requirements |
|---|---|---|---|---|---|
| BR-01 | Feature: language (B§3.1, B§4) | Design only. The EDA's script heuristic is a simplified signal, not a validated detector. | Build and evaluate a tested detector at scale, including rare languages. | — | FR-FEAT-01, FR-FEAT-03 |
| BR-02 | Feature: semantic intent | Exploratory only; no labels. | Clustering and labelling at scale. | If an LLM-based intent method is tried | FR-FEAT-02 |
| BR-03 | Feature: code presence | Detector can be built. Only 9 user messages (1.9%) are code-like by the EDA heuristic (`text_indicators_by_role.csv`), and 0 contain fenced code. Too few to evaluate. | Enough positives to evaluate. | — | FR-FEAT-01 |
| BR-04 | Feature: attachments (image/audio) | Presence and type for image only (15 items). | Audio, if present (A-12). | — | FR-FEAT-01, NG-07 |
| BR-05 | Route simple→cheap, complex→advanced | Design and rule prototypes. **No outcome evaluation**: there are no difficulty or quality labels, and only the as-logged answer exists. | Distribution of request types; more as-logged pairs. | **Needed** for counterfactual answers from other models (or recorded once and reused). | FR-ROUTE-*, FR-EVAL-04 |
| BR-06 | Classifier is cheap (latency and cost) | Local overhead measurable (QA-LAT a). | — | If the router calls a model | FR-ROUTE-04 |
| BR-07 | Semantic cache | Candidate analysis only: lexical and embedding similarity on 465 messages. **No safe-hit evidence** (F-7). | Needed for meaningful hit rates and false-hit estimation. | Judge or verifier for hit correctness (optional) | FR-SCACHE-*, FR-XCACHE-* |
| BR-08 | Cascade on unsatisfactory answer | Design only. 11 short/error-like proxy rows (EDA). There is no unsatisfactory signal. | Retry, escalation, and failure fields, if present. | **Needed** to observe cheap-model failures and escalation outcomes. | FR-CASC-* |
| BR-09 | Provider failover | Design plus fault-injection tests. | Failure and retry events, if present. | Real failure rates and latencies. | FR-FAIL-* |
| BR-10 | Pricing engine (optional) | — | Volumes per workload. | Verified prices (public pricing pages, not calls) | FR-FIN-01, NG-05 |
| BR-11 | Dashboard (optional) | Event aggregates derivable from replay. | Same, at scale. | Real latency | FR-OBS-05, FR-FIN-02 |
| BR-12 | Real-time tracking of tokens, savings, routing | Event model and offline aggregates. Tokens are estimated, not billed. | Billed tokens, if present (U-01). | Provider-reported usage | FR-OBS-*, FR-ACCT-* |
| BR-13 | Quality: similarity of routed vs. actual answers, plus judge | As-logged answers exist, but routed answers don't; agreement can be computed only for answers produced later. | More reference answers. | **Needed** to produce routed answers and to run an LLM judge. | QA-QUAL, FR-EVAL-03/05 |
| BR-14 | Cache hit rate | Candidate rates per key variant (Stage 8 baseline). | Real rates with hit correctness. | Optional judge | FR-XCACHE-07, FR-SCACHE-04 |
| BR-15 | Cost per query vs. premium baseline | Estimated tokens only (tokenizer-specific), on hypothetical prompt composition. | Billed tokens and real composition (U-01, U-04). | Verified prices; premium model chosen (Q-05) | QA-COST, FR-ACCT-* |
| BR-16 | Latency vs. baseline | Pipeline overhead only. Logged gaps are **not** latency. | Lifecycle latency fields, if present. | **Needed** for model latency and end-to-end time. | QA-LAT |
| BR-17 | Generalise across the four categories | Per-category stratified reporting (small n). | Adequate n per stratum. | — | FR-EVAL-06, NG-08 |
| BR-18 | Unified, highly available gateway | In-process API and fake adapters. | — | Real adapters | FR-API-*, FR-FAIL-* |

All "Sample now" entries are exploratory: the sample is small and may not be representative (ADR-0008).

**Takeaway:** the sample supports **design, feature extraction, candidate analysis, overhead measurement, and fault-injection testing**. It cannot support any claim about **quality, real savings, real latency, or safe-cache share**. Those need live calls, the full dataset, or both.

---

## 7. Traceability

**Rule (decided).** Every later design element cites what it serves:
- architecture sections, components, contracts, modules, config files, and experiments;
- citing at least one `FR-*`, `QA-*`, or `NG-*` ID (for an explicit boundary), or a hypothesis/experiment ID;
- hypotheses are `H-n` in [context.md §5.2](context.md); experiments will be `EXP-*` IDs, assigned in Stage 8 plans, each naming the `H-n` it tests.

An element with no trace is either missing a requirement (add one, with a source) or should not exist. The Stage 10 review audits this.

**Requirement area → hypotheses → where it is designed or built.**

| Area | Hypotheses | Stage 2 home ([structure](../architecture/repository_structure.md)) | Stage 3 view | Stage 4 contracts ([contracts.md](../architecture/contracts.md)) | Stage 5 skeleton | Implemented in |
|---|---|---|---|---|---|---|
| FR-REQ | — | `contracts`, `data_access` | [lifecycle, data flow](../architecture/request_lifecycle.md) | yes | yes | Stage 5, Stage 9 (replay pairing) |
| FR-FEAT | H-5 | `domain` | [routing flow](../architecture/routing.md) | yes | yes | Stage 8+ experiments |
| FR-ROUTE | H-5, H-6 | `domain`; `experiments/routing/` | [routing flow](../architecture/routing.md) | yes | fixed-model reference | Stage 8+ experiments |
| FR-XCACHE | H-3 | `domain`, `adapters`; `experiments/caching/` | [caching flow](../architecture/caching.md) | yes | no-op/in-memory | **Stage 8 baseline** |
| FR-SCACHE | H-4 | `domain`, `adapters`; `experiments/caching/` | [caching flow](../architecture/caching.md) | yes | interface | later experiment |
| FR-CTX | H-1, H-2 | `domain`; `experiments/context/` | [context flow](../architecture/context_construction.md) | yes | pass-through | later experiment |
| FR-CASC | H-6 | `domain`, `application` | [attempts flow](../architecture/attempts.md) | yes | interface | later experiment |
| FR-FAIL | — | `application`, `adapters` | [attempts flow](../architecture/attempts.md), [providers](../architecture/providers.md) | yes | fake adapter with faults | Stage 5 (fakes) |
| FR-ACCT | H-7 | `domain`, `config/`; `experiments/cost/` | [overview CMP-09](../architecture/overview.md#3-component-catalogue), [data flow](../architecture/request_lifecycle.md#4-data-flow-and-privacy-boundary) | yes | interface | **Stage 7** |
| FR-OBS | — | `contracts`, `adapters`, `evaluation` | [observability](../architecture/observability.md) | yes | event emitter | Stage 5 (file sink) |
| FR-EVAL | all | `evaluation`; `experiments/evaluation/` | [offline evaluation flow](../architecture/evaluation.md) | yes | runner stub | **Stage 8** |
| FR-DATA | — | `data_access`, `analysis`; `experiments/full_eda/` | [data flow](../architecture/request_lifecycle.md#4-data-flow-and-privacy-boundary), [future database](../architecture/deployment_and_data.md#4-future-database-integration-extension-point-not-a-schema) | yes | interface | **Stage 9** |
| FR-API | — | `application`; future `gateway` | [high-level](../architecture/overview.md#2-high-level-architecture), [deployment](../architecture/deployment_and_data.md) | yes | in-process entry | Stage 5 |
| FR-FIN | — | placeholder only | — | — | — | deferred (NG-05) |
| QA-* | — | — | each view states which QAs it serves | — | — | measured in Stage 8 runs |

---

## 8. Open items raised by this stage

Recorded in the [register](assumptions_and_questions.md):
- **New questions:** Q-13 (quality tolerance δ), Q-14 (latency budget), Q-15 (future gateway API compatibility), Q-16 (cache sharing scope), Q-17 (confirm Action 3 deferral). All were answered on 2026-10-14; see the register for status. Q-15 stays open.
- **New assumptions:** A-18 … A-22.

Deferred to later stages:
- concrete thresholds (configuration, Stage 6/8)
- the model catalogue and prices (Stage 7)
- event and contract field names (Stage 4)
- experiment IDs (Stage 8)
