# Module Interaction Reference (Stage 5; updated in Stages 6, 7, 7.5, and 8)

Status: **matches the code as of 2026-10-18**. The *Imports* column is checked mechanically by `tests/architecture/test_module_reference.py`: every module under `src/metis_auto/` (except `contracts/` and `__init__.py` re-export files) must have exactly one row, and its *Imports* cell must equal the `metis_auto` sub-packages it imports, outside its own sub-package. Other columns are hand-written; update them in the same change as the code.
Index: [architecture README](README.md). Components: [overview §3](overview.md#3-component-catalogue). Layers and import rules: [repository_structure.md §3](repository_structure.md#3-dependency-rules).

This document answers, for every module: **who calls it, what it calls, what data goes in and out, what configuration it needs, whether it is business or infrastructure logic, and whether it is meant to become stable.**

## How to read it

- **Imports (checked):** `metis_auto` sub-packages the module imports, e.g. `domain.accounting`. `contracts`, `ports`, and `settings` are listed as whole packages (they have no sub-packages). Imports inside the module's own sub-package are listed under *Called by / calls* instead.
- **Kind:** *business* (pure decisions, `domain`), *orchestration* (`application`: measures and coordinates), *infrastructure* (`adapters`, `data_access`), *evaluation*, *composition* (`wiring`), *interface* (`ports`).
- **Status:** *stable* (meant to stay; changes are normal maintenance), *reference* (a decided reference implementation that alternatives are compared against), *provisional* (works; shape may change with evidence), *skeleton* (signature and docstring only; raises `NotImplementedError` with a TODO naming the stage), *test double* (fake for offline use). Nothing under `src/` is experimental: candidates live in `experiments/` until promoted (repository_structure §6.2).
- **Contracts** (`contracts/*`, 16 modules) are documented in [contracts.md](contracts.md) and [contracts_reference.md](contracts_reference.md). They import nothing internal and are used by every module below.

## Request flow at a glance

`scripts/run_walking_skeleton.py` → `wiring.walking_skeleton` → `wiring.pipeline.build_pipeline` → `application.pipeline.RequestPipeline.handle`, which runs one method per stage ([ADR-0010](../adr/0010-request-pipeline-shape.md)):

| Stage | Pipeline method | Measures with | Decides with |
|---|---|---|---|
| 0 receive | `_receive` | `IdSource`, `Clock` | — |
| 1 measure | `_measure` | `application.measurement.MeasurementService.measure` | — |
| 2 features | `_extract_features` | — | `domain.features.extract_features` |
| 3 route | `_route` | — | `domain.routing.route` + injected `RoutingPolicy` |
| 4 cache lookup | `_cache_lookup` | `MeasurementService.seal_key`, `CacheStore.get` | `domain.caching` (`select_scope`, `eligibility`, `compose_key`, `validate_entry`) |
| 5 context | `_plan_for` | `MeasurementService.target_counts` | injected `ContextStrategy` |
| 6 attempts | `_attempt_loop`, `_attempt` | `ModelClient.invoke`, `MeasurementService.counted_usage` / `overhead_for`, `SpendGuard` | `domain.attempts.next_action`, detectors, `domain.accounting.cost_of` / `pre_call_estimate` |
| 7 store | `_store_answer` | `CacheStore.put` | `domain.caching.store_decision` |
| 8 respond | `_respond`, `_finish` | `Clock` | `domain.accounting.total_cost` |

Every stage emits its event through `application.events.EventRecorder` → `EventSink`.

---

## `ports` — interfaces (CMP-10…16, CMP-26)

| Module | CMP | Responsibility | Called by / calls | Imports (checked) | In → out | Config | Kind | Status |
|---|---|---|---|---|---|---|---|---|
| `ports/model_client.py` | 10 | `ModelClient`: `invoke`, `source` | called by `application.pipeline`; implemented by `adapters.providers` | `contracts` | `ModelInvocation` → `ModelResult` | — | interface | stable |
| `ports/cache.py` | 11 | `CacheStore` (`get`, `put`), `VectorIndex` (`add`, `query`); no validity rules | called by `application.pipeline`; implemented by `adapters.stores` | `contracts` | `Fingerprint` → `CacheEntry`; `Embedding` → `IndexMatch` | — | interface | stable |
| `ports/measurement.py` | 12, 13 | `Tokenizer` (`count`), `Embedder` (`embed`) | called by `application.measurement`; implemented by `adapters.tokenizers`, `adapters.embedders` | `contracts` | text → `TokenCount` / `Embedding` | — | interface | stable |
| `ports/events.py` | 14 | `EventSink` (`emit`, `close`) | called by `application.events`; implemented by `adapters.sinks` | `contracts` | `Event` → — | — | interface | stable |
| `ports/judge.py` | 15 | `Judge` (`score`); input contract open (O-6) | called by `evaluation.metrics` (Stage 8); implemented by `adapters.judges` | `contracts` | `Request` + `ModelResponse` → `JudgeScore` | — | interface | provisional |
| `ports/data.py` | 18 | `DataSource` (`dataset`, `sessions`) | called by evaluation/analysis via wiring; implemented by `data_access` | `contracts` | — → `Session` stream | — | interface | stable |
| `ports/system.py` | 16, 26 | `Clock`, `IdSource`, `SpendLedger` | called by `application`; implemented by `adapters.system` | `contracts` | — → UTC time, ms, IDs, `Money` | — | interface | stable |

## `domain` — pure decisions (CMP-04…09)

| Module | CMP | Responsibility | Called by / calls | Imports (checked) | In → out | Config | Kind | Status |
|---|---|---|---|---|---|---|---|---|
| `domain/features/extractor.py` | 04 | Derived features; unknown stays `None` | called by `application.pipeline` (stage 2) | `contracts`, `domain.accounting` | `Request` + `RequestMeasurements` → `RequestFeatures` | `FeatureConfig` | business | provisional (language, code detection TODO Stage 8) |
| `domain/routing/base.py` | 05 | `RoutingPolicy` protocol, `PolicyChoice`, `RequestedModelMode` | used by `routing.policy`, `routing.fixed_model`, `wiring.pipeline` | `contracts` | — | — | business | stable |
| `domain/routing/eligibility.py` | 05 | Shared eligibility filter: modality (verified only), context fit, enabled, minimum window | called by `routing.policy.route` | `contracts` | `RequestFeatures` + `ModelCatalogue` → eligible entries, `Exclusion`s | `EligibilityConfig` | business | reference |
| `domain/routing/policy.py` | 05 | `route`: eligibility → policy → `RoutingDecision`; never routes to an ineligible model | called by `application.pipeline` (stage 3); calls `routing.eligibility`, the injected policy | `contracts` | `RequestFeatures` + `ModelCatalogue` → `RoutingDecision` | `RoutingConfig` | business | provisional (tier selection, requested-model modes TODO) |
| `domain/routing/fixed_model.py` | 05 | `fixed_model` policy (also the premium baseline) | built by `wiring.pipeline`; called by `routing.policy.route` | `contracts` | eligible entries → `PolicyChoice` | `FixedModelConfig` | business | reference |
| `domain/caching/policy.py` | 06 | Scope, eligibility, key draft, validity at lookup, store rules | called by `application.pipeline` (stages 4, 7) | `contracts` | `Request`, `RequestMeasurements`, `RoutingDecision`, `CacheEntry` → `CacheKeyDraft`, `CacheLookupResult`, `CacheStoreDecision` | `CachePolicyConfig`, `KeyVariant` | business | provisional (semantic tier, normalisation treatments, tier rule TODO Stage 8) |
| `domain/caching/normalise.py` | 06 | Message treatments before fingerprinting: `literal`, `whitespace`, `nfkc_casefold_ws` (FR-XCACHE-03); Persian folding not done | called by `evaluation.cache_candidates` (serving still `literal` only) | — | text, treatment → text | treatment name | business | decided (treatments); serving use open |
| `domain/context/policy.py` | 07 | `ContextStrategy` protocol, `ContextConfig`, overflow rule (`check_fit`) | used by `context.pass_through`, `wiring.pipeline` | `contracts` | input tokens + `CatalogueEntry` → `OverflowOutcome` | `ContextConfig` | business | provisional (trim TODO Stage 8) |
| `domain/context/pass_through.py` | 07 | Reference strategy: keep everything, default order, composition record | built by `wiring.pipeline`; called by `application.pipeline` (stage 5); calls `context.policy` | `contracts`, `domain.accounting` | `Request` + `RequestMeasurements` + `TargetTokenCounts` → `ContextPlan` | `ContextConfig` | business | reference |
| `domain/attempts/policy.py` | 08 | `next_action`: primary, retry, failover, escalation, return, fail | called by `application.pipeline` (stage 6) | `contracts` | `AttemptState` + `ModelCatalogue` → `AttemptAction` | `AttemptPolicyConfig` | business | reference (context-overflow rebuild TODO) |
| `domain/attempts/detectors.py` | 08 | Truncation and empty-output detectors; "any fired" rule | built by `wiring.pipeline`; called by `application.pipeline` | `contracts` | `ModelResponse` → `DetectorVerdict`s | detector names in `AttemptPolicyConfig` | business | provisional (more detectors are Stage 8 experiments) |
| `domain/accounting/tokens.py` | 09 | Token sums with worst-fidelity rule | called by features, context, `accounting.cost`, `application.measurement` | `contracts` | `TokenCount`s → `TokenCount` | — | business | stable |
| `domain/accounting/cost.py` | 09 | Cost from usage and tiered prices (uncached / cached input, cache writes, output; tier by input tokens; caveats); totals; pre-call estimate; provider-cache discount; "not computed" never zero | called by `application.pipeline`, `application.accounting`, `accounting.baseline`; calls `accounting.tokens` | `contracts` | `TokenUsage` + `CatalogueEntry` + `PriceTable` → `Cost`, `CostEstimate` | `AccountingConfig` | business | stable (Stage 7, ADR-0020) |
| `domain/accounting/overhead.py` | 09 | Chat-template overhead from a `ChatTemplate` and part roles; content + framing | called by `application.measurement`, `accounting.baseline`; calls `accounting.tokens` | `contracts` | `ChatTemplate` + roles → `TokenCount` | — | business | stable (templates provisional, A-55) |
| `domain/accounting/baseline.py` | 09 | Premium-baseline estimate (brief §5): full context + overhead, answer re-counted; caveats | called by `application.accounting`; calls `accounting.cost`, `.overhead`, `.tokens` | `contracts` | counts + `CatalogueEntry` + `PriceTable` → `AccountedUsage` | — | business | stable (Stage 7) |
| `domain/accounting/savings.py` | 09 | Savings decomposition (brief §6), fixed order, exact sum; per message and summed per session | called by `application.accounting`; (Demo) the UI through wiring | `contracts` | `Cost`s → `SavingsDecomposition` | — | business | stable (Stage 7; consumed by the Demo milestone) |

## `application` — measurement and orchestration (CMP-01…03, CMP-17)

| Module | CMP | Responsibility | Called by / calls | Imports (checked) | In → out | Config | Kind | Status |
|---|---|---|---|---|---|---|---|---|
| `application/measurement/fingerprints.py` | 02 | HMAC-SHA-256 fingerprints, key ID, sealing key drafts (ADR-0015 am. 1; reproduces the test vectors) | called by `measurement.service`; built by `wiring.pipeline` | `contracts` | purpose + payload → `Fingerprint`; `CacheKeyDraft` → `CacheKey` | fingerprint key (secret) | orchestration | stable |
| `application/measurement/service.py` | 02 | Fingerprints, sizes, estimates (stage 1); target counts (5); counted usage with chat-template overhead (6); key sealing (4); `request_roles` | called by `application.pipeline`, `application.accounting`; calls `Tokenizer`, `Clock`, `fingerprints`, `domain.accounting` | `contracts`, `domain.accounting`, `ports` | `Request`, `CatalogueEntry` → `RequestMeasurements`, `TargetTokenCounts`, `TokenUsage`, `CacheKey` | tokenizer registry, chat templates | orchestration | provisional (embeddings, model-based features TODO Stage 8) |
| `application/accounting/service.py` | 09 | `AccountingService`: tokens and cost for a request + answer on a model (`account`); the spend guard's pre-call estimate (`pre_call_estimate`); premium estimate (`premium_estimate`); savings decomposition of a served response (`decompose`) | called by scripts, tests, (Demo) the UI; calls `application.measurement`, `domain.accounting` | `application.measurement`, `contracts`, `domain.accounting` | `Request` + answer (+ `TokenUsage` / `FinalResponse`) → `AccountedUsage`, `SavingsDecomposition` | catalogue, prices | orchestration | stable (Stage 7) |
| `application/events/recorder.py` | 03 | Wraps payloads in `Event` envelopes; start-up privacy check | called by `application.pipeline`; calls `EventSink`, `Clock`, `IdSource` | `contracts`, `ports` | `EventPayload` → `Event` | run ID, run mode, `Versions` | orchestration | stable |
| `application/pipeline/config.py` | 01 | `PipelineConfig`: reference data + each policy's config | built by `wiring`; read by the pipeline | `contracts`, `domain.accounting`, `domain.attempts`, `domain.caching`, `domain.context`, `domain.features`, `domain.routing` | — | — | orchestration | provisional (built from settings in Stage 6) |
| `application/pipeline/spend_guard.py` | 17 | Allow a live attempt only within the cap; charge the actual cost, or, when it is not computed, the pre-call estimate and then stop live calls for the run (ADR-0021) | called by `pipeline.pipeline`; calls `SpendLedger` | `contracts`, `ports` | `CostEstimate` → allow/block; `Cost` → charge | — | orchestration | provisional |
| `application/pipeline/pipeline.py` | 01 | `RequestPipeline.handle`: the fixed stage order, one method per stage | called by scripts, tests, `evaluation.replay`; calls everything in the table above | `application.events`, `application.measurement`, `contracts`, `domain.accounting`, `domain.attempts`, `domain.caching`, `domain.context`, `domain.features`, `domain.routing`, `ports` | `Request` → `FinalResponse` (+ events) | `PipelineConfig` | orchestration | provisional (semantic tier, re-route, savings TODO Stage 8) |

## `adapters` — infrastructure (CMP-10…16, CMP-26)

| Module | CMP | Responsibility | Called by / calls | Imports (checked) | In → out | Config | Kind | Status |
|---|---|---|---|---|---|---|---|---|
| `adapters/providers/fake.py` | 10 | Canned `[SYNTHETIC]` answers; reports no usage | built by wiring; called by the pipeline | `contracts` | `ModelInvocation` → `ModelResponse` | simulated latency | infrastructure | test double |
| `adapters/providers/injecting.py` | 10 | Fault- and quality-injecting decorators (scripted per call) | built by tests/wiring; wraps a `ModelClient` | `contracts`, `ports` | `ModelInvocation` → scripted `ModelResult` | script | infrastructure | test double |
| `adapters/providers/replay.py` | 10 | `ProxyModelClient` (no answers); `ReplayModelClient.logged` (logged answer only when the target is the label's mapped model, else `ModelNoAnswer` with reason) and `.recorded_from` (recordings in `data/recorded/`, keyed by model + in-memory digest of the exact input) | built by `wiring.experiments` for evaluation | `contracts` | `ModelInvocation` → `ModelResponse` / `ModelNoAnswer` | label → model map; recordings directory | infrastructure | stable (Stage 8) |
| `adapters/providers/recording.py` | 10 | Recording decorator: appends each **live** invocation and result to a JSON Lines file under `data/recorded/` (content; git-ignored); a failed write is logged, never raised | built by `wiring.live` around the live client | `contracts`, `ports` | `ModelInvocation` → `ModelResult` (+ record) | path, run ID | infrastructure | writing stable (Stage 7.5); replay lookup TODO Stage 8 |
| `adapters/providers/openai_compat.py` | 10 | **Live** client for OpenAI-compatible chat completions through the Metis wrapper: base URL and generation-limit field per family; SDK retries off (A-33); one message per part (A-55); usage → `TokenUsage` (cached, reasoning, provider-reported model); per-model request options as `extra_body`; finish reason and the nine error classes normalised (ADR-0021). The only importer of `openai` (extra `live`) | built by `wiring.live`; called by the pipeline through the recording decorator | `contracts` | `ModelInvocation` → `ModelResponse` / `ModelError` | API key (secret), endpoint routes, timeout | infrastructure | provisional (Stage 7.5; mappings checked by the live wrapper check) |
| `adapters/stores/memory.py` | 11 | In-memory `CacheStore` and cosine `VectorIndex` | built by wiring per run; called by the pipeline | `contracts` | key → `CacheEntry`; `Embedding` → `IndexMatch` | — | infrastructure | stable (offline) |
| `adapters/tokenizers/approx.py` | 12 | chars ÷ N approximation, labelled `approximation` | built by wiring; called by `application.measurement` | `contracts` | text → `TokenCount` | ref, chars per token | infrastructure | stable as fallback |
| `adapters/tokenizers/assets.py` | 12 | sha256 check of tokenizer files; `TokenizerUnavailable` | called by the tokenizer adapters, `scripts/fetch_tokenizer_assets.py` | — | path + sha256 → path | — | infrastructure | stable |
| `adapters/tokenizers/tiktoken_backend.py` | 12 | Exact counts with a tiktoken encoding (`o200k_base`), loaded offline from a checked file | built by `wiring.tokenizers`; called by `application.measurement` | `contracts` | text → `TokenCount` | encoding, asset, sha256 | infrastructure | stable (extra `tokenizers`) |
| `adapters/tokenizers/hf_backend.py` | 12 | Exact counts from a Hugging Face `tokenizer.json` (DeepSeek-V4-Flash), no Hub access | built by `wiring.tokenizers`; called by `application.measurement` | `contracts` | text → `TokenCount` | asset, sha256 | infrastructure | stable (extra `tokenizers`) |
| `adapters/embedders/fake.py` | 13 | Hash-derived vectors; no meaning | built by tests/wiring | `contracts` | text → `Embedding` | dimensions | infrastructure | test double |
| `adapters/sinks/memory.py` | 14 | Events in a list | built by wiring/tests | `contracts` | `Event` → list | — | infrastructure | test double |
| `adapters/sinks/jsonl.py` | 14 | Events as JSON Lines under `runs/` | built by wiring | `contracts` | `Event` → file | path | infrastructure | stable (offline) |
| `adapters/judges/fake.py` | 15 | Fixed score or "unmeasured" | built by tests | `contracts` | `Request` + `ModelResponse` → `JudgeScore` | score | infrastructure | test double |
| `adapters/system/clock.py` | 16 | `SystemClock`, `FakeClock` | built by wiring/tests | — | — → UTC time, ms | start, step | infrastructure | stable |
| `adapters/system/ids.py` | 16 | UUID and sequential (seeded) ID sources | built by wiring/tests | — | prefix → ID | namespace | infrastructure | stable |
| `adapters/system/ledger.py` | 26 | `InMemorySpendLedger` (one run, one cap; tests) and `FileSpendLedger`: the **persistent, cumulative** ledger (append-only JSON Lines, file lock; lifetime and per-run caps; warnings at 50/80 %; fails closed on a damaged file) | built by `wiring.from_settings` for live runs; called through the spend guard | `contracts` | `Money` → remaining, `BudgetStatus` | ledger path, caps, `warn_at` | infrastructure | provisional (ADR-0018) |

## `data_access` — the data layer (CMP-18)

| Module | CMP | Responsibility | Called by / calls | Imports (checked) | In → out | Config | Kind | Status |
|---|---|---|---|---|---|---|---|---|
| `data_access/sample/loader.py` | 18 | Sample file → generic `Session`s; every sample quirk handled here (contracts.md §4): roles, opaque refs via an injected function, empty → absent, null → unknown `not_in_log`, missing key → absent by default (Q-37) or unknown `key_missing` (alternative, A-61), attachments, plateau-detected `possibly_truncated` flag | built by `wiring.experiments` | `contracts` | file → `Session` | data path, `missing_key`, plateau count | infrastructure | provisional (pulled forward into Stage 8) |
| `data_access/synthetic/generator.py` | 18 | Seeded synthetic sessions | built by wiring | `contracts` | seed → `Session` | seed | infrastructure | skeleton (Stage 9) |
| `data_access/replay_cases/builder.py` | 18 | Sessions → `ReplayCase`s: latest-preceding-user pairing (A-04), flags `clean` / `multiple_answers` / `skipped_consecutive_user` / `unanswered`, exclusion `no_preceding_user`, no look-ahead, answer-side components from the first answer, `answers_disagree` flags | called by `wiring.experiments` | `contracts` | `Session` → `ReplayCase`, `ExclusionCount` | — | infrastructure | provisional (pulled forward into Stage 8) |

## `evaluation` — replay and results (CMP-21…24)

| Module | CMP | Responsibility | Called by / calls | Imports (checked) | In → out | Config | Kind | Status |
|---|---|---|---|---|---|---|---|---|
| `evaluation/replay/harness.py` | 21 | Feed cases to a given pipeline; references never reach it | called by the runner, tests; calls `RequestPipeline.handle` | `application.pipeline`, `contracts` | `ReplayCase` → `ReplayOutcome` | — | evaluation | provisional (ordering, exclusions, coverage TODO Stage 8) |
| `evaluation/baselines/as_logged.py` | 22 | As-logged cost from the case (label mapping → catalogue model, counted on the assumed composition, priced); premium estimate per case (brief §5); "not computed" with a reason | called by `evaluation.runner` | `application.accounting`, `contracts`, `domain.accounting`, `settings` | `ReplayCase` → `Cost`, label resolutions | label mapping, price table, premium model | evaluation | provisional (Stage 8) |
| `evaluation/metrics/aggregate.py` | 23 | ADR-0006 metrics **from events** (`evaluation_scored`, `cache_lookup`, `response_returned`), overall and per stratum (category, turn depth), Wilson intervals; hit rate always with hit correctness; the cache variant table | called by `evaluation.runner` | `contracts`, `domain.accounting` | `Event`s + `ReplayCase`s → `EvaluationResult` | — | evaluation | provisional (judge and agreement TODO) |
| `evaluation/cache_candidates/harness.py` | 23 | Every key variant × scope in one pass, outside the serving path; eligibility (strict / wildcard), `cache_lookup` events, lexical repeat groups and the lexical answer-match signal | called by `evaluation.runner` | `application.events`, `application.measurement`, `contracts`, `domain.caching` | `ReplayCase`s → events + counts | `[experiment.strategy.params]` (bases, treatments, unknown modes) | evaluation | provisional (Stage 8) |
| `evaluation/cache_candidates/index.py` | 23 | `CandidateIndex` (the cache strategy swap point for experiments); `ExactKeyIndex` (serving rule), `WildcardIndex` (measurement only); built-in registry | called by the harness; candidates implement it | `contracts` | `CandidateItem` → matched case ID | strategy params | evaluation | interface provisional; indexes reference |
| `evaluation/runner/runner.py` | 24 | Run one experiment (`pipeline_replay` or `cache_candidates`): admit pairing flags, order cases, per-case baseline events, run, aggregate from the events; write manifest, events, results, extras under `runs/<EXP-ID>/<run-id>/` | called by `scripts/run_experiment.py` via `wiring.experiments`; gets a pipeline or index factory | `application.accounting`, `application.events`, `application.measurement`, `application.pipeline`, `contracts`, `evaluation.baselines`, `evaluation.cache_candidates`, `evaluation.metrics`, `evaluation.replay`, `ports`, `settings` | `ReplayCase`s → `EvaluationResult` (+ files) | `[experiment]` | evaluation | provisional (Stage 8, minimal) |
| `evaluation/runner/compare.py` | 24 | The comparison format: one row per run × key variant × scope × baseline, one column per metric, cells with n and interval or state and reason | called by scripts | `contracts` | (`RunManifest`, `EvaluationResult`)s → rows, Markdown | — | evaluation | provisional |

## `settings` — configuration loading (CMP-19, Stage 6)

| Module | CMP | Responsibility | Called by / calls | Imports (checked) | In → out | Config | Kind | Status |
|---|---|---|---|---|---|---|---|---|
| `settings/model.py` | 19 | `Settings` (frozen, non-secret; `pipeline` sections opaque), `Secrets` (pydantic secret types), reference-table shapes (`EndpointTable`, `BaselineTable`, `TokenizerTable`, `TokenizerSpec`), `ReferenceData`, `LoadedSettings`; cap rules | built by `settings.loader`; read by `wiring` | `contracts` | dicts → typed settings | — | infrastructure | provisional (ADR-0019) |
| `settings/loader.py` | 19 | Layers and precedence; layer rules (defaults-only ceiling, no runtime sections in experiments, no secret-like keys); `.env` reader; `METIS__` overrides; secrets; config hash | called by scripts, `wiring`, tests; calls `settings.reference` | — | files + environment → `LoadedSettings` | `METIS_CONFIG_DIR`, `METIS_RUNTIME_CONFIG` | infrastructure | provisional (ADR-0019) |
| `settings/reference.py` | 19 | `config/reference/*.toml` → `ModelCatalogue`, `PriceTable` (tiers, cache-write variants), endpoints, baselines, tokenizer table; cross-file checks | called by `settings.loader` | `contracts` | TOML → contracts | `[reference]` paths | infrastructure | stable (schema fixed in Stage 7) |

## `wiring` — composition root (CMP-20)

| Module | CMP | Responsibility | Called by / calls | Imports (checked) | In → out | Config | Kind | Status |
|---|---|---|---|---|---|---|---|---|
| `wiring/pipeline.py` | 20 | `build_pipeline` (tokenizers and chat templates injected); registries of **promoted** routing policies, context strategies, detectors; refuses live without a cap; accepts an injected experiment candidate (routing policy, context strategy) with its version (Stage 8) | called by `wiring.from_settings`, `wiring.walking_skeleton`, tests, (Stage 8) the runner | `adapters.system`, `adapters.tokenizers`, `application.events`, `application.measurement`, `application.pipeline`, `contracts`, `domain.attempts`, `domain.context`, `domain.routing`, `ports` | `PipelineConfig` + adapters + key + config hash → `RequestPipeline` | all | composition | provisional |
| `wiring/from_settings.py` | 20 | `LoadedSettings` → `PipelineConfig` (policy types validate `[pipeline.*]`), fingerprint key, file spend ledger, `live_permission` (two keys + caps + API key), `build_pipeline_from_settings` (with tokenizers and templates), `build_accounting_service` | called by scripts, `wiring.walking_skeleton`, tests; calls `wiring.pipeline`, `wiring.tokenizers` | `adapters.system`, `adapters.tokenizers`, `application.accounting`, `application.measurement`, `application.pipeline`, `contracts`, `ports`, `settings` | `LoadedSettings` → components | all | composition | provisional (ADR-0018, ADR-0019) |
| `wiring/experiments.py` | 20 | Experiment config (layer 3) → runner: candidate loading from `experiments/` only (`importlib`, path check), sample cases, data hash, counterfactual client (fake, logged_match, recorded, proxy; live refused), `RunManifest` (git, hardware), run folder | called by `scripts/run_experiment.py`, `scripts/measure_overhead.py`, tests | `adapters.providers`, `adapters.sinks`, `adapters.stores`, `adapters.system`, `adapters.tokenizers`, `application.measurement`, `contracts`, `data_access.replay_cases`, `data_access.sample`, `evaluation.cache_candidates`, `evaluation.runner`, `ports`, `settings` | config path → `PreparedRun` | `[experiment]`, `[reference] label_mapping`, `paths.run_dir` | composition | provisional (Stage 8) |
| `wiring/tokenizers.py` | 20 | One `Tokenizer` per tokenizer-table row; chat templates; labelled chars/4 fallback when the library or asset is missing; status for scripts | called by `wiring.from_settings`, scripts, tests | `adapters.tokenizers`, `contracts`, `ports`, `settings` | `LoadedSettings` → `TokenizerSet` | `[reference] tokenizers`, `paths.tokenizer_assets` | composition | stable (Stage 7) |
| `wiring/live.py` | 20 | `build_live_client`: recording(OpenAI-compatible live client) from settings after `live_permission`; routes per enabled endpoint; the API key leaves the secret holder only here; `live_overrides` (the experiment's `live` key, fixed model, diagnostics); `request_options` (`[model_options]` → request-body fields, checked against each endpoint's allowed options) | called by `wiring.chat`, `wiring.wrapper_check`, scripts, tests | `adapters.providers`, `ports`, `settings` | `LoadedSettings` → `ModelClient` | `[live]`, endpoints, `paths.recorded_dir`, `METIS_API_KEY` | composition | provisional (Stage 7.5) |
| `wiring/chat.py` | 20 | `ChatSession`: history (P-8), fixed target model (rebuilt on switch, cache and run kept), live or fake; content-free `TurnReport` (served by, models, tokens, cost, premium estimate, decomposition per message and session, overhead, budget); `format_report` | called by `scripts/chat.py`, `wiring.wrapper_check`, tests, (Demo) the UI | `adapters.providers`, `adapters.sinks`, `adapters.stores`, `adapters.system`, `application.accounting`, `application.pipeline`, `contracts`, `domain.accounting`, `ports`, `settings` | message → `FinalResponse` + `TurnReport` | settings layers | composition | provisional (Stage 7.5) |
| `wiring/wrapper_check.py` | 20 | The tiny live wrapper check: `plan` (pre-call estimates, no call) and `run` (one synthetic message per test model, one attempt each; reported vs counted tokens, finish reason, cached and reasoning reporting, reported model; content-free); the follow-up probe `probe_plan` / `probe_run` (provider cache, MiMo, DeepSeek thinking off) | called by `scripts/live_wrapper_check.py`, tests | `contracts`, `domain.context`, `ports`, `settings` | `LoadedSettings` → plan rows; results dict | `MAX_TOTAL_ESTIMATE` (0.05 USD) | composition | Stage 7.5 |
| `wiring/walking_skeleton.py` | 20 | Settings from `config/profiles/walking_skeleton.toml` (synthetic catalogue, empty prices); fakes; demo requests | called by `scripts/run_walking_skeleton.py`, tests; calls `wiring.from_settings`, `wiring.pipeline` | `adapters.providers`, `adapters.sinks`, `adapters.stores`, `application.pipeline`, `contracts`, `ports`, `settings` | key → `RequestPipeline` | `config/profiles/walking_skeleton.toml` | composition | provisional |

## Not yet populated

- `analysis` (CMP-25): future, with the full-dataset EDA.
- `scripts/run_walking_skeleton.py`: the walking-skeleton entry point. Outside the package; loads settings, calls `wiring`, prints content-free metadata and the config hash.
- `scripts/show_budget.py`: prints the live budget (cumulative spend vs caps) and why live calls are blocked. Outside the package; calls `settings` and `wiring.from_settings`. Makes no calls.
- `scripts/fetch_tokenizer_assets.py` (Stage 7): downloads the tokenizer files once (network, explicit) and checks their sha256; `--check` verifies only. Calls `settings`, `adapters.tokenizers`, `wiring.tokenizers`.
- `scripts/measure_overhead.py` (Stage 7, brief §11): N walking-skeleton requests, p50/p95/max per span, hit/miss mix, hardware. Calls `wiring`.
- `scripts/estimate_sample_tokens.py` (Stage 7, optional): tokenizer-specific size **estimates** for the sample's text fields, aggregates only. Reads the sample file directly (read-only); calls `wiring.tokenizers`.

## Swap points (QA-REPL: one interface + one config entry)

| To add… | Implement | Register | Select with |
|---|---|---|---|
| a routing policy | `domain.routing.RoutingPolicy` | `wiring.pipeline.ROUTING_POLICIES` | `routing.policy` |
| a context strategy | `domain.context.ContextStrategy` | `wiring.pipeline.CONTEXT_STRATEGIES` | `context.strategy` |
| a detector | `domain.attempts.Detector` | `wiring.pipeline.DETECTORS` | `attempts.detectors` |
| a model client, store, tokenizer, embedder, sink, judge | the `ports` protocol | passed to `build_pipeline` | runtime config (Stage 6: `config/`, `METIS__*`; the live adapter factory is Stage 7.5) |

Candidates under test load from `experiments/` through the Stage 8 mechanism; the registries above hold promoted components only.
