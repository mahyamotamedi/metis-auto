# Internal Contracts (Stage 4)

Status: conventions and contract set **decided**; individual fields **provisional** (the Stage 5 skeleton now uses them; two additions, §6); price schema **decided** in Stage 7 ([ADR-0020](../adr/0020-token-and-cost-accounting.md)); catalogue shape provisional (limits wait for TODO-10). Last updated 2026-10-18 (Stage 5: `CacheKeyDraft`, `RequestFeatures.known_input_tokens`, schema 0.2; O-2, O-7, O-9 resolved. Stage 6: O-1 resolved, configuration diagram labelled; no contract changed. Stage 7: accounting additions, schema 0.3, §6; O-3 resolved except the label mapping. Stage 8: pairing flag `unanswered`, `LoggedMessage.quality_flags`, schema 0.4; O-3 fully resolved: the label mapping is a reference file read by `settings`. 2026-10-19: the sample loader's missing-key default is `absent`, Q-37; no contract changed. Demo milestone A, 2026-10-19: `Turn.producer` (A-64) and the other additions in §6, schema 0.5, [ADR-0023](../adr/0023-demo-backend-components.md); then `has_coding_intent`, schema 0.6, A-71).
Index: [architecture README](README.md). Code: `src/metis_auto/contracts/`. **Field tables:** [contracts_reference.md](contracts_reference.md), generated from the code (a test fails if it is stale). Decisions: [ADR-0017](../adr/0017-contract-modelling-with-pydantic.md) (pydantic), [ADR-0015 amendment 1](../adr/0015-keyed-content-fingerprints.md#amendment-1-2026-10-17-stage-4-the-algorithm) (fingerprint algorithm).

This document answers: **what data crosses each boundary, who produces and consumes it, how sensitive each part is, and how it changes over time?** It fixes the provisional vocabulary of [overview §5](overview.md#5-provisional-contract-vocabulary).

Field-level detail (type, required or optional, privacy class, description) is in the generated reference, so it can't drift from the code. This document holds what the code can't say: purpose, producers, consumers, versioning, and the reasoning.

---

## 1. Scope

**In scope:** every data structure passed between components on the request path, the replay path, and the evaluation path, plus the persisted records (events, cache entries, run manifests, evaluation results).

**Not in scope here:**
- **Port method signatures** (`ModelClient.invoke`, `CacheStore.get`, …): defined in Stage 5 in `src/metis_auto/ports/` ([module_reference.md](module_reference.md)). The contracts here are their arguments and return values.
- **`Settings`**: defined in Stage 6 in `src/metis_auto/settings/model.py`, not here: it is configuration read by wiring, not data passed between components ([ADR-0019](../adr/0019-configuration-format-layers-and-secrets.md) point 6).
- **How accounting uses these contracts** (tokenizers, inclusion rules, pricing, caveats, the premium estimate, the savings decomposition): [token_accounting.md](token_accounting.md) (Stage 7).
- **Wire formats** of providers and of the future gateway (FR-API-03). Adapters translate them into these contracts.
- **Persistent database schema** (NG-02).

---

## 2. Conventions

### 2.1 One base class (ADR-0017)

Every contract subclasses `ContractModel`, a pydantic v2 model that is:
- **frozen**: contracts are values. Sequences are tuples. `dict` fields are shallowly mutable by Python's rules; never mutate them.
- **`extra="forbid"`**: a misspelt or unknown field is an error, not silently dropped.
- **minimally validated**: shape, formats, and internal consistency only (§2.9).

### 2.2 Privacy classes

Every field declares one class with `field(privacy, description)`. The class is metadata on the field; it costs nothing at run time.

| Class | Meaning | May leave the content boundary? | Examples |
|---|---|---|---|
| `content` | Raw text or anything that can reproduce it | **no**: memory on the request path, the cache store, gitignored data only ([lifecycle §4](request_lifecycle.md#4-data-flow-and-privacy-boundary)) | messages, instructions, history, retrieved text, answers, attachment locators, embedding vectors (A-32) |
| `fingerprint` | Keyed fingerprint of content ([ADR-0015](../adr/0015-keyed-content-fingerprints.md)) | yes | component fingerprints, cache keys, instruction group |
| `reference` | Opaque identifier | yes | request, attempt, run, case, entry IDs; session and user refs; opaque strata |
| `derived` | Value computed from content | yes | sizes, counts, token counts, language, flags, scores |
| `operational` | Non-content metadata | yes | model IDs, versions, times, durations, money, reason codes |
| `inherit` | Generic containers only: takes the class of the enclosing field | — | `Component.value` |

**Enforced by tests** (`tests/unit/contracts/test_contracts_privacy.py`):
1. every field of every contract has a class;
2. `Event` and every payload type, `RunManifest`, `EvaluationResult`, `ResponseMetadata`, `RoutingDecision`, `CacheLookupResult`, `CompositionRecord`, `AttemptState`, and `RequestFeatures` contain **no `content` field at any depth**. The check walks the declared types, resolving `inherit`;
3. the serialised synthetic examples of those records contain no synthetic content marker (a value-level check that complements the type-level one);
4. self-tests show the checker catches a content field hidden in a nested model, and an unclassified field.

`contracts/privacy.py` provides the walker; the event recorder (CMP-03, `application/events/recorder.py`) runs the same check at start-up.

**Free text can't hide in derived fields.** Feature maps (`RequestFeatures.extra`, `RequestMeasurements.model_features`) accept numbers, booleans, and lower-case codes only (`FeatureValue`). Error details are provider *codes*, never messages (providers.md §1).

### 2.3 Tri-state components (P-6)

`Component[T]` holds an optional request component as `present` (with a value), `absent`, or `unknown` (with an optional reason code such as `not_in_log` or `not_supplied`). The model checks that a value exists exactly when the state is present.

**Every optional component of `Request` defaults to `unknown`** (A-36, decided 2026-10-18, Q-24), the conservative state: unknown never matches a cache key (ADR-0011) and never counts as "no context". Producers must state `absent` explicitly. The future gateway adapter maps fields omitted from the incoming wire request to `absent`, because it sees the whole request; inside Metis, a forgotten field stays `unknown` and can never cause a false cache hit.

**Empty means absent** (O-4, decided 2026-10-18). An empty or whitespace-only string, an empty list, or an empty mapping (e.g. `structured_input` = `{}`) is recorded as `absent`, never as present-with-empty-value:
- `Component` rejects a present value that is an empty or whitespace-only string, an empty sequence, or an empty mapping;
- `RetrievedContext.items` needs at least one item, since present retrieved context with no items is the same case one level down;
- producers apply the rule: the Stage 5 request builder and the Stage 9 sample loader.

**The message is required, and may be empty only for an attachment-only message** (decided 2026-10-18). `Request.message` is not a tri-state component. An empty or whitespace-only message is valid only when `attachments` is `present`; if attachments are `absent` or `unknown`, the `Request` validator rejects it. This is an online-phase rule: the sample has no empty user messages (465: 451 text-only and 14 text plus attachments, counted 2026-10-18).

The rule is about empty values, not missing ones. A field the log doesn't record, or records as null, is `unknown` (§4), unless the data owner says otherwise.

### 2.4 Identifiers and correlation (A-05)

- Metis **mints its own IDs** (`Identifier`: 1–128 characters from `[A-Za-z0-9_.:-]`): `run_id`, `request_id` (minted by the pipeline at stage 0, **not** part of the caller's `Request`), `attempt_id`, `event_id`, `case_id`, cache `entry_id`. This resolves A-05: the sample's lack of IDs is not carried into the online design.
- **Caller references** are opaque: `session_ref`, `user_ref`, `caller_request_ref` (echoed back in `ResponseMetadata`). In replay, `session_ref` is a keyed fingerprint of the dataset's session ID, never the raw ID.
- **Model IDs, policy names, reason codes** use `Name`: lower-case codes.

### 2.5 Fingerprints

`Fingerprint` = `fp1:` + 64 hex characters: HMAC-SHA-256 with domain separation by purpose, canonical JSON for structured payloads, and no implicit normalisation ([ADR-0015 amendment 1](../adr/0015-keyed-content-fingerprints.md#amendment-1-2026-10-17-stage-4-the-algorithm)). The key ID (`kid1:` + 16 hex) is recorded in `Versions.fingerprint_key_id` and `RequestMeasurements.fingerprint_key_id`, so fingerprints from different keys are never compared. Tests use a fixed synthetic key, and test vectors computed independently with OpenSSL pin the algorithm.

### 2.6 Time

Two distinct types that never mix (FR-REQ-05, A-06):
- `UtcDatetime`: times Metis records itself. It **must** be timezone-aware UTC.
- `LoggedTimestamp`: times copied from a dataset. It **must** be naive (timezone unknown). It exists only on replay contracts and on `Event.logged_timestamp`, which the validator forbids on `live` events.

Durations are milliseconds from the monotonic clock. Every latency figure names its span and its source (§3.6).

### 2.7 Money, cost, and "not computed"

`Money` is a `Decimal` amount plus an ISO 4217 currency, serialised as a decimal string, never a float. `Cost` is either `computed`, with an amount, a price-table version, price references, and the worst token fidelity used, or `not_computed` with a reason (`price_unknown`, `model_unmapped`, `baseline_unset`, …). Zero is never a stand-in for unknown (FR-ACCT-02, ADR-0002). `Cost.basis` says what the figure describes: actual, pre-call estimate, avoided (cache hit), or baseline estimate.

### 2.8 Versioning

| Thing | Version carried in | Rule |
|---|---|---|
| The contract schema as a whole | `SCHEMA_VERSION` (now `0.6`; `0.1` → `0.2` in Stage 5, `0.2` → `0.3` in Stage 7, `0.3` → `0.4` in Stage 8, `0.4` → `0.5` in the Demo milestone, and `0.5` → `0.6` for the coding intent, for the additions in §6) on persisted contracts: `Event`, `CacheEntry`, `RunManifest`, `EvaluationResult`; plus `Versions.contracts` on every event | **While 0.x**, any change bumps the minor version, and data written under another 0.x minor is not guaranteed readable. That is acceptable because runs are self-contained and offline cache state is reset per run. **From 1.0** (proposed after the Stage 10 review, or when the first persisted data must outlive a code change): adding an optional field or an enum value is a minor bump; removing, renaming, retyping, or changing the meaning of a field is a major bump. Readers accept older minors of their own major. There is no forward compatibility: `extra="forbid"` rejects fields from a newer writer. |
| Policies, feature set, key schema, catalogue, price table, embedder, judge | `Versions` (on events, entries, manifests) and `PolicyRef` | Owned by each component, independent of the schema version. A key-schema or embedder change makes old cache entries unreachable by construction (ADR-0011). |
| Event types | the `EventPayload` union | Adding a type is a minor bump. Removing one is a major bump. |
| Fingerprint algorithm | the `fp1` / `kid1` prefixes | A change replaces all three prefixes together (ADR-0015 amendment 1). |

### 2.9 What validation does, and does not, do

**Does:** formats (IDs, fingerprints, codes, currency, UTC vs naive time), required fields, and internal consistency. For example: a computed cost has a price version; a hit names its entry; a semantic hit records similarity and threshold; a routing target is eligible; an `ok` response has an answer; hit rate is never reported without hit correctness; a live run has a spending cap; a verified capability or a known price has a source and check date.

**Does not:** apply any policy, such as eligibility, TTLs, thresholds, or scope selection. Those are `domain` decisions with their own configuration. A contract may hold a state that serving would reject (a cache key with an unknown component, a measurement-only key variant), because experiments need to represent it.

---

## 3. Contract catalogue

Producers and consumers use the component IDs from [overview §3](overview.md#3-component-catalogue). "Persisted" means written outside memory, and where.

### 3.1 Request and measurement

| Contract (module) | Purpose | Producer | Consumers | Persisted | Privacy | Status | Traces |
|---|---|---|---|---|---|---|---|
| `Request` (`request`) with `Turn`, `RetrievedContext`, `RetrievedItem`, `AttachmentRef`, `TrafficSource`, `Component[T]` | The current message plus optional tri-state components, caller refs, requested model, deadline. **Generic**: no dataset field or role names. | caller; replay-case builder (CMP-18) | CMP-01, then CMP-02, 04, 06, 07 | no | content (message and components); refs; `traffic_source` derived | decided; `traffic_source` **reserved** (§5) | FR-REQ-01…05, P-6, P-8, FR-OBS-04 (document refs and scores) |
| `RequestMeasurements` (`measurement`) with `ComponentMeasurement`, `MeasurementRecord`, `Embedding`, `EmbedderRef` | Fingerprints, sizes, cheap token estimates, an optional embedding, measured model-based features, and the overhead of each measurement | CMP-02 | CMP-04, CMP-06; records go into `features_extracted` | no | derived and fingerprints; the embedding vector is content | provisional | P-1, FR-FEAT-02, FR-ROUTE-04, FR-SCACHE-05 |
| `TargetTokenCounts` (`measurement`) | Per-component and per-item token counts with the **target's** tokenizer | CMP-02 | CMP-07; CMP-09 (pre-call estimate) | no | derived | provisional | FR-CTX-01, FR-ACCT-06 |
| `TokenCount`, `TokenUsage` (`tokens`) | Counts, each with its fidelity and method; usage of one call or an estimate. Inclusion rules: `input` includes cached input, cache writes, and template overhead; `output` includes reasoning ([token_accounting.md §3](token_accounting.md#3-what-is-billed-and-what-is-modelled)) | CMP-02; `ModelClient` (reported) | CMP-09, CMP-07, events | in events | derived | decided | FR-ACCT-01, H-7 |
| `RequestFeatures` (`features`) | Derived features with the feature-set version; experimental ones in `extra` | CMP-04 | CMP-05, CMP-06, CMP-23 (strata), `features_extracted` | in events | derived, fingerprint (instruction group) | shape decided; feature set provisional | FR-FEAT-01…05 |

### 3.2 Routing and reference data

| Contract | Purpose | Producer | Consumers | Persisted | Privacy | Status | Traces |
|---|---|---|---|---|---|---|---|
| `ModelCatalogue`, `CatalogueEntry`, `Capability`, `Limit`, `Sourced` (`reference_data`) | Models with tier, equivalence group, limits, and capabilities. A capability or limit counts only with evidence (source and check date). | CMP-19 from `config/reference/` (Stage 6) | CMP-05, CMP-07, CMP-08, CMP-09 | config files (versioned) | operational | provisional (limits: TODO-10; tokenizer table and the reasoning capability: Stage 7) | FR-ROUTE-05, FR-FAIL-03, FR-CTX-05, MP§3.8 |
| `PriceTable`, `PriceEntry` (`reference_data`) | Price per token type (input, output, cached input, cache write with a TTL variant), unit, currency, effective date, evidence; optional context tier chosen by the call's input tokens (non-overlapping; an uncertain bound can be marked). A missing amount means unknown, so costs come out "not computed". | CMP-19 | CMP-09 | config files | operational | decided (Stage 7, ADR-0020) | FR-ACCT-02, ADR-0002 |
| `RoutingDecision` (`routing`) with `Exclusion` | Target, group, tier, eligible models, exclusions with reasons, escalation chain, policy version, reason code, features read, re-route constraint, flags | CMP-05 | CMP-01, CMP-06 (group in the key), CMP-08, `routing_decided` | in events | operational | decided | FR-ROUTE-01…06 |

### 3.3 Caching

| Contract | Purpose | Producer | Consumers | Persisted | Privacy | Status | Traces |
|---|---|---|---|---|---|---|---|
| `CacheKey`, `KeyComponent`, `CacheScope` (`caching`) | Key schema version, variant, `serving_allowed`, per-component state and fingerprint with its treatment (normalisation or window), target group, scope, key and partition-key fingerprints | CMP-06; experiments (measurement variants) | `CacheStore`, `VectorIndex`; fingerprints into events | inside `CacheEntry` | fingerprints, refs | decided (structure); variants provisional | ADR-0011, ADR-0007, FR-XCACHE-02/03/05 |
| `CacheEntry` (`caching`) | A stored answer with its key, producing model and tier, creation time, status, source request, optional embedding, versions | CMP-01 (after a positive `CacheStoreDecision`) | `CacheStore` → CMP-06 | **cache store only** | **content** (answer, embedding) | decided | FR-XCACHE-04/08/09 |
| `CacheKeyDraft` (`caching`) | A composed key **before** fingerprinting: the same fields as `CacheKey` minus `key` and `partition_key`. The cache policy decides the composition but holds no fingerprint key (ADR-0015), so CMP-02 seals the draft into a `CacheKey`. `key_material()` / `partition_material()` define what is fingerprinted. | CMP-06 | CMP-02 (seal) | no | operational, fingerprints | decided (Stage 5) | ADR-0011, ADR-0015 |
| `IndexMatch` (`caching`) | One vector-index result: entry and similarity, with the embedder | `VectorIndex` | CMP-06 | no | derived | decided | FR-SCACHE-02/03 |
| `CacheLookupResult` (`caching`) | One tier's outcome: hit, miss, or ineligible with a reason; invalid reason; variant; scope; similarity and threshold; checks not evaluated (time sensitivity, TODO-07) | CMP-06 | CMP-01, `cache_lookup` | in events | operational, fingerprint | decided | FR-XCACHE-06, FR-SCACHE-04 |
| `CacheStoreDecision` (`caching`) | Store or skip with a reason | CMP-06 | CMP-01; `cache_stored` / `cache_store_skipped` | in events | operational | decided | FR-XCACHE-04 |

### 3.4 Context and model calls

| Contract | Purpose | Producer | Consumers | Persisted | Privacy | Status | Traces |
|---|---|---|---|---|---|---|---|
| `ContextPlan` (`context`) with `InputPart` | Ordered input parts with generic roles, for one target | CMP-07 | CMP-01 → `ModelInvocation` | no | **content** | decided | FR-CTX-01…04 |
| `CompositionRecord`, `ComponentComposition` (`context`) | Per component: state, action, fingerprint, tokens, items; totals; window; overflow outcome; composition fingerprint (a replay-lookup key) | CMP-07 | `context_built`; recorded-response lookup (ADR-0014) | in events | derived, fingerprint | decided | FR-CTX-01, FR-OBS-04 |
| `ModelInvocation` (`model_io`) | One call: IDs, kind, model, parts, attachments, output limit, timeout, replay-lookup keys | CMP-01 | `ModelClient` | no (recorded responses are keyed by it) | **content** | decided | FR-API-02, ADR-0014 |
| `ModelResult` = `ModelResponse` \| `ModelError` \| `ModelNoAnswer` (`model_io`) | Response (text, finish reason, usage, latency, provider version, source); normalised error (class, retryable, provider code); or **no answer** from a replay or proxy source (lowers coverage; never retried) | `ModelClient` adapters | CMP-01, CMP-08 (via `AttemptRecord`), recording decorator | `data/recorded/` (gitignored) | response text is **content** | decided | providers.md §1/§3, ADR-0014 |

### 3.5 Attempts, accounting, response

| Contract | Purpose | Producer | Consumers | Persisted | Privacy | Status | Traces |
|---|---|---|---|---|---|---|---|
| `AttemptState`, `AttemptRecord` (`attempts`) | All the attempt policy may read: decision, finished attempts (content-free records with outcome, usage, cost, verdicts), deadline and budget left, re-route flag | CMP-01 | CMP-08; records go into `attempt_finished` | in events | operational, derived | decided | ADR-0013, FR-CASC-04, FR-FAIL-04 |
| `AttemptAction` (`attempts`) | Invoke (target and kind, optional backoff), return (which attempt; whether flagged), or fail (`FailureReason`) | CMP-08 | CMP-01 | no | operational | decided | ADR-0013 |
| `DetectorVerdict` (`attempts`) | Detector, version, evaluated or not, value, threshold, fired | CMP-08 detectors | CMP-01, `escalation_triggered` | in events | derived | decided (shape); detectors open | FR-CASC-02/05 |
| `Money`, `Cost` (with `price_tier`, `caveats`: `CostCaveat`), `CostEstimate`, `Savings` (`accounting`) | §2.7 | CMP-09 | CMP-01, CMP-17, events, CMP-23 | in events | operational | decided | FR-ACCT-02…06 |
| `AccountedUsage` (`accounting`) | Tokens and cost of one call, actual or estimated; a baseline estimate names its baseline (brief §5) | CMP-09 (`application.accounting`) | scripts, Demo UI, CMP-23 | no | operational, derived | decided (Stage 7) | FR-ACCT-01/02/05 |
| `SavingsDecomposition`, `TermValue`, `DecompositionTerm` (`accounting`) | The brief §6 terms in a fixed order, plus the `extra_cost` remainder; the validator checks they sum exactly | CMP-09 | Demo UI, CMP-23 | no | operational | decided (Stage 7) | FR-ACCT-04/05, brief §6 |
| `ChatTemplate` (`reference_data`) | Per-role framing tokens of a tokenizer family, with fidelity and evidence | CMP-19 from `config/reference/tokenizers.toml` | CMP-02, CMP-09 | config files | operational | provisional (A-55, A-56) | FR-ACCT-01 |
| `SpanTiming` (`response`) with `SPAN_CATEGORY` | Duration of a named span with its source (`measured_local`, `provider_reported`, `recorded`, `simulated`). The span-to-category table says what counts as overhead, model, or end-to-end latency. | CMP-01, CMP-03 | events, `ResponseMetadata`, CMP-23 | in events | operational | decided | ADR-0006 §4, observability §2 |
| `FinalResponse`, `ResponseMetadata` (`response`) | Status, answer (content), and content-free metadata: served by, model, cache tier and entry, attempts, usage, total, overhead and avoided cost, savings per baseline, spans, counts, flags, failure, versions | CMP-01 | caller; metadata goes into `response_returned` | metadata in events | answer is **content** | decided | FR-API-01, FR-ACCT-03…05, ADR-0010 §6 |

### 3.6 Events

| Contract | Purpose | Producer | Consumers | Persisted | Privacy | Status | Traces |
|---|---|---|---|---|---|---|---|
| `Event` (`events`) | Envelope: IDs, type, run mode, UTC time, logged time (replay only), span and duration, `Versions`, plus a payload discriminated by `event_type`. The validator checks that the type matches the payload, that `request_id` is present except on run-level events, that live events carry no replay fields, and that span and duration come together. | CMP-03 | `EventSink`, CMP-23, future dashboard | `runs/` (JSON Lines), sinks | **no content** (tested) | decided | ADR-0012, FR-OBS-01…05 |
| Payloads: `RequestReceived`, `FeaturesExtracted`, `RoutingDecided`, `CacheLookedUp` (`cache_lookup`), `CacheStored`, `CacheStoreSkipped`, `ContextBuilt`, `AttemptStarted`, `AttemptFinished`, `RetryScheduled`, `FailoverTriggered`, `EscalationTriggered`, `BudgetBlocked`, `ResponseReturned`, `EvaluationScored`, `RunStarted`, `RunFinished` | One per event type in [observability §3](observability.md#3-event-envelope-and-types). Each reuses the content-free contracts above. | CMP-03 | as above | as above | no content | decided (types); fields provisional | as observability §3 |

Every dashboard figure in [observability §4](observability.md#4-what-the-deferred-dashboard-would-read-fr-obs-05) maps to fields that now exist: avoided cost and savings (`ResponseMetadata`), costs by attempt kind (`AttemptRecord`), spans (`SpanTiming`), routing mix (`RoutingDecision`), hit and false-hit rates (`CacheLookupResult` with `EvaluationScored`), escalation and failover counts, and budget (`BudgetBlocked`).

### 3.7 Replay and evaluation

| Contract | Purpose | Producer | Consumers | Persisted | Privacy | Status | Traces |
|---|---|---|---|---|---|---|---|
| `Session`, `LoggedMessage` (`replay`) | A logged conversation in log order. Every per-message metadata field is tri-state; a loader sets only what its dataset records. | CMP-18 loaders | replay-case builder (CMP-18), CMP-25 | no (read from data files) | **content**; labels operational | decided | FR-DATA-02/06, FR-REQ-04/05 |
| `ReplayCase`, `Reference`, `DataQualityFlag` (`replay`) | One replayable request as seen at its turn (no look-ahead), with 0…n paired logged answers, pairing method and flag, naive time, opaque stratum, loader warnings | replay-case builder (CMP-18) | CMP-21 (request → pipeline), CMP-22 and CMP-23 (references) | no | **content** | decided | FR-REQ-03, FR-REQ-06, FR-EVAL-08 |
| `JudgeScore` (`evaluation`) | One judge's score for one answer, with judge version, rubric, state, and cost | `Judge` port (CMP-15) | CMP-23; CMP-02 when used as a runtime detector | via `EvaluationScored` | derived | provisional | FR-EVAL-05, ADR-0006 |
| `MetricValue`, `StratumResult`, `EvaluationResult`, `ExclusionCount`, `Interval`, `StratumKey` (`evaluation`) | Metrics as separate named values (agreement, judge score, and non-inferiority never merged), each with a state (`measured` / `unmeasured` / `not_computed`), n, interval, and qualifiers. Hit rate requires hit correctness in the same stratum. Results start with the overall stratum. Every run reports `as_logged`. Coverage is `cases_covered / cases_total`. | CMP-23 | CMP-24, reports | `runs/`; curated summaries to `reports/` | no content | decided | ADR-0006, ADR-0014, FR-EVAL-03/06/08/09 |
| `RunManifest`, `CodeVersion` (`evaluation`) | Run identity, code, data hash, seed, versions and key ID, counterfactual source, prompt-composition assumption, history mode, ordering rule, admitted pairing flags, live flag and cap, hardware | CMP-24 | reproducibility, reports | `runs/` | no content | decided | FR-EVAL-07, QA-REPRO, ADR-0003 |
| `Versions`, `PolicyRef` (`_base`) | Versions in force; which policy and version | every producer | events, entries, manifests | with them | operational | decided | FR-OBS-02 |

---

## 4. Tolerating the sample without baking it in (FR-DATA-06, ADR-0008)

The rule: **a sample quirk may shape a replay contract's optional or tri-state fields, never the online `Request`.** Each quirk is handled in the sample loader (CMP-18, Stage 9) and leaves at most a flag.

| Sample reality (provisional signal, ADR-0008) | How the contracts tolerate it | Handled in | Online design unaffected because |
|---|---|---|---|
| No request or message IDs | `ReplayCase.case_id` is minted; `LoggedMessage.message_ref` is optional; `PairingMethod` says how pairs were formed | loader, case builder | `request_id` is minted by the pipeline; `Request` has no dataset IDs (A-05) |
| Heuristic pairing: answers with no preceding user message, several answers per user message, consecutive user messages | `PairingFlag` (`clean`, `multiple_answers`, `skipped_consecutive_user`, and since Stage 8 `unanswered`: a user message the log never answered); `references` holds 0…n items; `no_preceding_user` is never a case, only an `ExclusionCount` (validator) | case builder (Stage 8: `data_access/replay_cases/builder.py`) | flags live only on `ReplayCase`, the replay-only field of `RequestReceived`, and the manifest |
| Null model, provider, or instructions on some answers; a missing retrieval field | tri-state `Component` with `unknown` and a reason; unknown is never treated as absent (FR-REQ-04). In the sample the three nulls occur together on 27 of 442 answers, in 2 sessions, which looks like a logging gap: the loader maps them to `unknown` (reason `not_in_log`), **never** to `absent` (Q-25). A key **missing** from a message (no `rag`, `input`, or `attachments` key) is `absent` by default, because the sample export lists these keys only when present (owner decision Q-37, 2026-10-19; A-61); the loader option `missing_key = "unknown"` (reason `key_missing`) is the conservative alternative, recorded in the run's config hash and still reported. This does not touch nulls. Cache experiments therefore also report the measurement-only "unknown as wildcard" key variant, so the opportunity in those requests stays visible. | loader; Stage 8 cache experiments | online callers state components explicitly; unknown is just the safe default |
| Instructions, retrieved context, and structured-input config logged on the *answer* side | `LoggedMessage` carries every metadata field per message; the case builder takes them from the paired answer into a generic `Request` | case builder | `Request` has no notion of "answer-side" fields |
| Role names (`user` / `bot`) | generic `Role` (`user`, `assistant`); `bot` is rejected (test) | loader | provider roles are mapped by adapters |
| Opaque category labels | `stratum` is an opaque `Identifier`; the loader maps each label to an opaque ID; never interpreted (A-02) | loader | strata are an evaluation concept; `Request` has none |
| Attachments as a content-type field plus a content string (URL or payload; not inspected) | `AttachmentRef`: modality (loader maps the dataset's type to `image`), MIME type if known, `locator` (content: holds that string), optional fingerprint | loader | attachments are references; content is never inspected (NG-07) |
| Naive timestamps; session creation vs message times inconsistent | `LoggedTimestamp` (must be naive), kept apart from `UtcDatetime`; `Session.logged_created_at` is separate from message times; replay-only `Event.logged_timestamp` | loader | Metis times are aware UTC; live events can't carry logged times (validator) |
| Retrieved context that may be truncated at an export ceiling (A-14) | `DataQualityFlag(component=retrieved, flag=possibly_truncated)`; policies never read flags | loader | no length constant appears anywhere in the contracts |
| Answer-side structured-input config of unknown meaning (A-16) | opaque `structured_input` dict, tri-state, documented as an uncertain proxy | loader | it is an optional, opaque `Request` component |
| Model labels that are not models (`default`, `workflow`) | `model_label` is a free `Component[str]`; mapping labels to catalogue models is a reference file (Stage 7); unmapped → `NoAnswerReason.label_unmapped` or `Cost` `model_unmapped` | label mapping (config) | routing uses catalogue `model_id`s only |
| Summary fields (session length, turn counts) | not modelled: derivable from `messages` | loader ignores them | — |

The synthetic fixtures follow the same rule: generic, multilingual with Persian, multi-turn, with optional components, and every string marked `[SYNTHETIC]` (FR-DATA-03).

---

## 5. Reserved: `Request.traffic_source` (Q-21, ADR-0016)

- **Shape:** `Component[TrafficSource]`, defaulting to `unknown`. `TrafficSource.kind` is an open code enumeration; the initial values are `embedded_bot` and `direct_user` (`KNOWN_TRAFFIC_SOURCES`), and new values are configuration. `TrafficSource.provenance` is `declared` (caller or gateway) or `inferred` (heuristic).
- **Privacy class:** derived. Never content.
- **Flows to:** `RequestFeatures.traffic_source_*` (so it can become an evaluation stratum, ADR-0016 Part 2 point 4) and `RequestReceived.traffic_source` (events).
- **Does not flow to:** the cache policy or `CacheScope`. **It has no serving effect** while ADR-0016 is proposed: the serving scope stays `session` (ADR-0007). Inferred values must never choose a scope (ADR-0016 Part 2 point 3); that rule belongs to the cache policy if the proposal is ever accepted.
- **Not added:** curated-cache entry fields (origin, build ID, answer provenance). They would be an additive minor bump if ADR-0016 moves to decided.

---

## 6. Changes from the Stage 3 vocabulary

Names kept: all of [overview §5](overview.md#5-provisional-contract-vocabulary). `Settings` is defined in `settings` (Stage 6, ADR-0019), not in `contracts`. Changes:

| Stage 3 | Stage 4 | Why |
|---|---|---|
| `ModelResult` (response or error) | `ModelResult` = `ModelResponse` \| `ModelError` \| **`ModelNoAnswer`** | Replay and proxy sources can have no answer for a target. That is a coverage gap, not an error, and must not trigger retries or failover (ADR-0014). |
| "token counts for target" | **`TargetTokenCounts`** | Named contract for the context stage's input. |
| "CacheEntry + similarity" | `CacheEntry` + **`IndexMatch`** | The vector index returns entry and similarity together. |
| "store decision" | **`CacheStoreDecision`** | Named contract. |
| "stage outcomes" (to the recorder) | **`EventPayload`** | The typed payload union. |
| pairing flag `multiple_bots` | **`multiple_answers`** | `bot` is the sample's role name; contracts are generic (ADR-0008). |
| — | **`JudgeScore`** | The judge arrow in the evaluation flow needed a contract. |
| — | `SpanTiming`, `Versions`, `PolicyRef`, `AttemptRecord`, `CompositionRecord`, `Component` | Previously described in prose; now named. |
| `CacheKey` from the cache policy | **`CacheKeyDraft`** → sealed into `CacheKey` by CMP-02 (Stage 5) | Domain can't fingerprint: the key is a secret held by the measurement service (ADR-0015). |
| — | **`RequestFeatures.known_input_tokens`** (Stage 5) | The routing context-fit check needs a whole-request estimate; a lower bound when components are unknown. |
| — | **Demo milestone A, amendment 2 (schema 0.6):** `RequestFeatures.has_coding_intent` (`bool \| None`), `TurnFeatures.has_coding_intent` (`bool`, default `False`) | Coding intent without code present (A-71): a rule-based routing feature and a sticky "very different" signal. |
| — | **Demo milestone A (schema 0.5, [ADR-0023](../adr/0023-demo-backend-components.md)):** `Turn.producer` (`Component[Name]`: a model ID or `cache`; absent for user turns; unknown by default; not part of the history fingerprint) and `CACHE_PRODUCER`; `RequestFeatures.length_bucket`, `.is_greeting`, `.history_turns` (new `TurnFeatures`); `RoutingDecision.anchor_model_id`; `ContextAction.COMPRESSED`; event `context_compressed` (`ContextCompressed`, `CompressedComponent`: sizes and compressor tokens only); `SpanName.CONTEXT_COMPRESS` (overhead); `IneligibleReason.NOT_FIRST_TURN` (demo seed) | Sticky routing reads who answered each earlier turn from the request (stateless, P-8; A-64); the detectors' features; the experimental compressor's record and time. |
| — | **Stage 8 (schema 0.4):** `PairingFlag.UNANSWERED`; `LoggedMessage.quality_flags` (loader warnings per message, copied to the case); `DataQualityFlag` defined before `LoggedMessage` | The sample has 15 trailing user messages with no answer, which no flag described; a loader finds truncation per message, before cases exist. |
| — | **Stage 7 (schema 0.3):** `TokenUsage.cache_write`, `.cache_write_ttl`, `.template_overhead`; `Cost.price_tier`, `.caveats`; `PriceEntry` tier fields and `cache_ttl`; `TokenType.CACHE_WRITE`; new `ChatTemplate`, `AccountedUsage`, `SavingsDecomposition`, `TermValue`, `DecompositionTerm`, `CostCaveat` | Cached input, cache writes, context tiers, framing overhead, labelled estimates, and the savings decomposition ([ADR-0020](../adr/0020-token-and-cost-accounting.md)). |

The renames are applied to the diagrams (§7).

---

## 7. Every arrow is labelled with a contract (exit criterion)

All 12 Mermaid blocks in `docs/architecture/` were re-parsed with Mermaid 11.4.1 after the label changes (2026-10-17, see [progress](../project/progress.md)).

| Diagram | Status | Notes |
|---|---|---|
| [High-level architecture](overview.md#2-high-level-architecture) | every arrow labelled | Labels added in Stage 4. The `implemented by` arrows are structural (port → adapter), not data. |
| [Component interaction](overview.md#4-component-interaction) | every arrow labelled with contracts | Renames from §6 applied. |
| [Request lifecycle](request_lifecycle.md#2-request-lifecycle-sequence) | every message is a contract, an event type, or a call whose arguments are contracts | Renames applied. |
| [Data flow](request_lifecycle.md#4-data-flow-and-privacy-boundary) | labelled with contracts, **except two non-contract flows**: `normalised text` (content written to gitignored `data/derived/` by experiments) and `log records (no content)` (operator logs, which are not a measurement source, observability §6) | Both are governed by the privacy rule, not by a contract. |
| [Offline evaluation](evaluation.md#2-offline-evaluation-flow) | labelled with contracts | `RequestPipeline (candidate / premium)` is **object injection** from `wiring`, not data. The experiment-config input is a Stage 8 file format. |
| [Future deployment](deployment_and_data.md#3-future-deployment-and-container-view) | labelled with contracts | The client wire format is external by design (FR-API-03, Q-15). |
| [Configuration flow](configuration.md#2-configuration-flow) | every arrow labelled (Stage 6): TOML layers, `Settings`, `ReferenceData`, `Secrets`, `LoadedSettings`, `PipelineConfig`, `Versions` | `Settings` and its secret holder live in `settings` (ADR-0019). |
| [Routing](routing.md#2-routing-decision-flow), [caching](caching.md#3-caching-decision-flow), [context](context_construction.md#3-context-construction-flow), [attempts](attempts.md#2-escalation-and-failover-flow) decision flows | edges are branch conditions; entry and exit nodes name contracts (`RoutingDecision`, `CacheLookupResult`, `TargetTokenCounts` → `ContextPlan`, `AttemptAction`) | Decision flowcharts show control flow, not data hand-offs. |
| [Package dependencies](repository_structure.md#31-allowed-imports-inside-srcmetis_auto-decided) | arrows are imports | Not a data diagram. |

---

## 8. Open items

| ID | Item | Resolved in |
|---|---|---|
| O-1 | ~~`Settings` contract (and its secret holder)~~ **Done in Stage 6:** `settings/model.py` (`Settings`, `Secrets`, `LoadedSettings`), [ADR-0019](../adr/0019-configuration-format-layers-and-secrets.md). | Stage 6 |
| O-2 | ~~Port method signatures~~ **Done in Stage 5:** `src/metis_auto/ports/`. | Stage 5 |
| O-3 | ~~Final price schema~~ **Done in Stage 7** ([ADR-0020](../adr/0020-token-and-cost-accounting.md)). ~~Label mapping~~ **Done in Stage 8:** `config/reference/label-mapping-sample-v1.toml`, read into `settings.LabelMapping` (fidelity `exact_id` / `alias`, or an unmapped reason), used by `evaluation.baselines.as_logged` and the `logged_match` replay client. Catalogue limits: TODO-10. | Stage 7, Stage 8 |
| O-4 | ~~Empty values: `present` or `absent`?~~ **Decided 2026-10-18:** empty means `absent`. Validator added (§2.3). Producers apply it. | Stage 5 request builder; Stage 9 sample loader |
| O-5 | Core feature set beyond the provisional fields | Stage 8 experiments |
| O-6 | Judge *input* contract (rubric, reference handling) beyond `Request` + `ModelResponse` | Stage 8 judge plan |
| O-7 | ~~Whether hot-path contracts need `model_construct`~~ **Not needed (Stage 5):** walking-skeleton overhead p95 ≈ 0.1 ms vs the 100 ms budget (indicative, A-38, progress.md). Revisit with realistic request sizes. | Stage 5 |
| O-8 | Curated-cache entry fields | only if ADR-0016 is accepted |
| O-9 | ~~Lock the pydantic version~~ **Done (Stage 5):** pydantic 2.14.1 in `requirements.lock`; all contract tests pass under it. | Stage 5 |
