# Contract Field Reference (generated)

**Do not edit by hand.** Generated from `src/metis_auto/contracts/` by
`tests/architecture/contracts_docgen.py`; a test fails when it is stale.
Design, producers, consumers, and versioning: [contracts.md](contracts.md).

Columns: **Req.** = required (no default). **Privacy** = the field's class
([contracts.md §2.2](contracts.md#22-privacy-classes)); `inherit` takes the
class of the enclosing field. Types are shown as written in the source.

## `contracts._base`

Shared building blocks for every contract (docs/architecture/contracts.md §2).

### `Component`

An optional request component that is present, absent, or unknown.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `state` | `ComponentState` | yes | derived | Present, absent, or unknown. |
| `value` | `T \| None` |  | inherit | The component; set only when present. |
| `unknown_reason` | `Name \| None` |  | derived | Why the state is unknown (code). |

### `PolicyRef`

Which policy (or strategy, backend) produced something, and its version.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `name` | `Name` | yes | operational | Configured policy name. |
| `version` | `Version` | yes | operational | Policy version string. |

### `Versions`

Versions in force for an event, entry, or run (FR-OBS-02, FR-EVAL-07).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `contracts` | `Version` |  | operational | Contract schema version. |
| `config_hash` | `str \| None` |  | operational | Hash of the non-secret settings. |
| `fingerprint_key_id` | `str \| None` |  | operational | ID of the fingerprint key (ADR-0015). |
| `policies` | `dict[Name, Version]` |  | operational | Policy name → version. |
| `feature_set` | `Version \| None` |  | operational | Feature set. |
| `catalogue` | `Version \| None` |  | operational | Model catalogue. |
| `price_table` | `Version \| None` |  | operational | Price table. |
| `key_schema` | `Version \| None` |  | operational | Cache key schema. |
| `embedder` | `Version \| None` |  | operational | Embedder ID@version. |
| `judge` | `Version \| None` |  | operational | Judge ID@version. |

**Enumerations**

- **`Privacy`**: `content`, `fingerprint`, `reference`, `derived`, `operational`, `inherit`. Privacy class of a field (contracts.md §2.2, QA-PRIV, ADR-0015).
- **`ComponentState`**: `present`, `absent`, `unknown`. P-6: unknown is not absent.

## `contracts.request`

The incoming request and its components (FR-REQ-01…05, P-6, P-8).

### `Turn`

One earlier message in the conversation history.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `role` | `Role` | yes | derived | Who wrote the message. |
| `text` | `str` | yes | content | Message text. |
| `producer` | `Component[Name]` |  | operational | Assistant turns: the model ID or 'cache' that produced it. |

### `RetrievedItem`

One retrieved-context string, with optional retrieval metadata (FR-OBS-04: document IDs and scores only if the caller supplies them).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `text` | `str` | yes | content | Retrieved text. |
| `document_ref` | `Identifier \| None` |  | reference | Opaque document ID from the caller. |
| `score` | `float \| None` |  | derived | Retrieval score. |

### `RetrievedContext`

Retrieved context (RAG) in the order the caller supplied it.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `items` | `tuple[RetrievedItem, ...]` | yes | content | Ordered items; at least one (no items = absent, O-4). |
| `query` | `Component[str]` |  | content | Retrieval query, if known. |

### `AttachmentRef`

A reference to an attachment. Content is never inspected (NG-07).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `modality` | `Modality` | yes | derived | Kind of attachment. |
| `media_type` | `str \| None` |  | derived | MIME type, if known. |
| `locator` | `str \| None` |  | content | URI or inline payload; may reveal content, so it stays in memory. |
| `size_bytes` | `NonNegInt \| None` |  | derived | Size, if known. |
| `fingerprint` | `Fingerprint \| None` |  | fingerprint | Keyed fingerprint of the content, if computed. |

### `TrafficSource`

Where the request comes from. **Reserved** (Q-21, ADR-0016, proposed): recorded and stratified, but it does not affect serving.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `kind` | `TrafficSourceKind` | yes | derived | e.g. embedded_bot, direct_user. |
| `provenance` | `Provenance` | yes | operational | Declared or inferred. |

### `Request`

What Metis answers: the current message plus optional components.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `message` | `str` | yes | content | The current user message; empty only if attachments are present. |
| `history` | `Component[tuple[Turn, ...]]` |  | content | Earlier turns, oldest first, supplied by the caller (P-8). |
| `instructions` | `Component[str]` |  | content | System-level text; not proven to be the provider system prompt (A-03). |
| `retrieved` | `Component[RetrievedContext]` |  | content | Retrieved context (RAG). |
| `attachments` | `Component[tuple[AttachmentRef, ...]]` |  | content | Attachment references. |
| `structured_input` | `Component[dict[str, JsonValue]]` |  | content | Structured-input configuration, opaque to Metis (C-03). |
| `traffic_source` | `Component[TrafficSource]` |  | derived | Reserved (Q-21). Recorded and stratified only; no serving effect. |
| `session_ref` | `Identifier \| None` |  | reference | Opaque conversation reference. |
| `user_ref` | `Identifier \| None` |  | reference | Privacy-safe user reference (ADR-0007). |
| `caller_request_ref` | `Identifier \| None` |  | reference | The caller's own correlation ID, echoed back. |
| `requested_model` | `Name \| None` |  | operational | Model the caller asked for (FR-ROUTE-06, open). |
| `deadline_ms` | `PosInt \| None` |  | operational | Time budget for the whole request. |

**Enumerations**

- **`Role`**: `user`, `assistant`. Generic conversation roles. Datasets' own names (e.g. ``bot``) are mapped by their loader.
- **`Modality`**: `image`, `audio`, `document`, `other`
- **`Provenance`**: `declared`, `inferred`

## `contracts.tokens`

Token counts, each labelled with how it was obtained (FR-ACCT-01, H-7).

### `TokenCount`

One token count and its provenance.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `tokens` | `NonNegInt` | yes | derived | Number of tokens. |
| `fidelity` | `Fidelity` | yes | operational | How the count was obtained. |
| `method` | `Version` | yes | operational | Tokenizer or approximation ID@version, or the provider usage field. |

### `TokenUsage`

Token usage of one model call, or an estimate of it.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `model_id` | `Name` | yes | operational | Catalogue model the counts are for. |
| `input` | `TokenCount` | yes | derived | Input tokens (all billed input). |
| `output` | `TokenCount \| None` |  | derived | Output tokens, including reasoning. |
| `total` | `TokenCount \| None` |  | derived | Total, as reported or summed by accounting. |
| `cached_input` | `TokenCount \| None` |  | derived | Part of input billed as cached (provider cache hit), if reported. |
| `reasoning` | `TokenCount \| None` |  | derived | Part of output that is hidden reasoning, if reported. |
| `cache_write` | `TokenCount \| None` |  | derived | Part of input billed as a provider cache write, if reported. |
| `cache_write_ttl` | `Name \| None` |  | operational | Cache-write variant when the price depends on it, e.g. ttl-5m. |
| `template_overhead` | `TokenCount \| None` |  | derived | Part of a counted input added by the chat template (message framing). |

**Enumerations**

- **`Fidelity`**: `provider_reported`, `exact_local`, `counting_api`, `approximation`. How a token count was obtained, best first (GLOSSARY: Fidelity).

## `contracts.accounting`

Money, cost, pre-call estimates, baseline estimates, and savings (FR-ACCT-02…06, ADR-0002, ADR-0020).

### `Money`

An amount in one currency. Decimal, never float.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `amount` | `Decimal` | yes | operational | Amount; may be negative for savings. |
| `currency` | `Currency` | yes | operational | ISO 4217 code. |

### `Cost`

A cost figure with its provenance (ADR-0006 point 3).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `status` | `CostStatus` | yes | operational | Computed or not computed. |
| `basis` | `CostBasis` | yes | operational | What the figure describes. |
| `amount` | `Money \| None` |  | operational | Set iff computed. |
| `reason` | `NotComputedReason \| None` |  | operational | Set iff not computed. |
| `price_table_version` | `Version \| None` |  | operational | Price table used; required when computed. |
| `price_refs` | `tuple[Name, ...]` |  | operational | Price entries used. |
| `token_fidelity` | `Fidelity \| None` |  | operational | Worst fidelity among the counts used. |
| `price_tier` | `Name \| None` |  | operational | Context tier used, when prices are tiered. |
| `caveats` | `tuple[CostCaveat, ...]` |  | operational | Known ways the figure may differ from the bill. |

### `CostEstimate`

Pre-call estimate the spend guard compares with the cap (CMP-17).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `model_id` | `Name` | yes | operational | Target model. |
| `input_tokens` | `TokenCount` | yes | derived | Counted input for the plan. |
| `assumed_output_tokens` | `NonNegInt` | yes | operational | Configured maximum output tokens assumed. |
| `cost` | `Cost` | yes | operational | Estimated cost (basis pre_call_estimate). |

### `Savings`

Baseline cost minus actual cost, for one baseline (FR-ACCT-05).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `baseline` | `Name` | yes | operational | Baseline ID, e.g. as_logged, premium. |
| `status` | `CostStatus` | yes | operational | Computed only if both costs are. |
| `amount` | `Money \| None` |  | operational | Set iff computed. |
| `baseline_cost` | `Cost` | yes | operational | The baseline's cost. |
| `actual_cost` | `Cost` | yes | operational | The candidate's cost. |

### `AccountedUsage`

Tokens and cost of one call, actual or estimated: what the accounting service reports for "this request and answer on this model" (MP Stage 7). A baseline estimate names its baseline (brief §5).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `model_id` | `Name` | yes | operational | Catalogue model. |
| `usage` | `TokenUsage` | yes | derived | Input, output, total, with fidelity. |
| `cost` | `Cost` | yes | operational | Cost with provenance and caveats. |
| `baseline` | `Name \| None` |  | operational | Baseline ID when this is a baseline estimate. |

### `TermValue`

One term: an amount, or not computed with a reason.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `term` | `DecompositionTerm` | yes | operational | Which term. |
| `status` | `CostStatus` | yes | operational | Computed or not. |
| `amount` | `Money \| None` |  | operational | Set iff computed. |
| `reason` | `NotComputedReason \| None` |  | operational | Set iff not computed. |

### `SavingsDecomposition`

Where the money went, per message or per session (brief §6, ADR-0020).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `scope` | `Name` | yes | operational | message or session. |
| `messages` | `NonNegInt` | yes | operational | Messages summed (1 or more). |
| `cache_hits` | `NonNegInt` | yes | operational | Messages served from cache. |
| `terms` | `tuple[TermValue, ...]` | yes | operational | One per DecompositionTerm, in DECOMPOSITION_ORDER. |
| `baseline_caveats` | `tuple[CostCaveat, ...]` |  | operational | Caveats of the premium estimate. |
| `price_table_version` | `Version \| None` |  | operational | Price table used. |

**Enumerations**

- **`CostStatus`**: `computed`, `not_computed`
- **`NotComputedReason`**: `price_unknown`, `model_unmapped`, `usage_unknown`, `baseline_unset`, `currency_mismatch`, `component_not_computed`
- **`CostBasis`**: `actual`, `pre_call_estimate`, `avoided_estimate`, `baseline_estimate`. What the cost describes.
- **`CostCaveat`**: `reasoning_not_counted`, `answer_length_assumed`, `template_overhead_approximated`, `context_tier_boundary_uncertain`, `cached_input_not_reported`. Why a computed cost may differ from the bill (token_accounting.md §5). Shown with the figure; never silently dropped.
- **`DecompositionTerm`**: `premium_baseline`, `routing_saving`, `compression_saving`, `cache_saving`, `provider_cache_saving`, `extra_cost`, `actually_paid`. Terms of the savings decomposition, in their fixed order (brief §6).

## `contracts.measurement`

What the measurement service (CMP-02) hands to domain policies (P-1).

### `ComponentMeasurement`

Content-free description of one request component.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `component` | `ComponentName` | yes | operational | Which component. |
| `state` | `ComponentState` | yes | derived | Present, absent, or unknown. |
| `fingerprint` | `Fingerprint \| None` |  | fingerprint | Keyed fingerprint; only when present. |
| `chars` | `NonNegInt \| None` |  | derived | Character length. |
| `items` | `NonNegInt \| None` |  | derived | Turns, retrieved items, or attachments. |
| `token_estimate` | `TokenCount \| None` |  | derived | Cheap estimate (target-independent). |

### `MeasurementRecord`

Overhead of one measurement (time, and cost if it called a model).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `measurement` | `Name` | yes | operational | e.g. fingerprint, embed, intent. |
| `backend` | `Version` | yes | operational | Backend ID@version. |
| `duration_ms` | `NonNegFloat` | yes | operational | Monotonic-clock duration. |
| `cost` | `Cost \| None` |  | operational | Cost if the measurement called a model. |
| `attempt_id` | `Identifier \| None` |  | reference | Attempt ID when it was a model call. |

### `EmbedderRef`

Which embedder produced a vector. Vectors from different embedders are never compared (caching.md §2).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `embedder_id` | `Name` | yes | operational | Embedder ID. |
| `version` | `Version` | yes | operational | Embedder version. |
| `dimensions` | `PosInt` | yes | operational | Vector length. |

### `Embedding`

A vector. Treated as content: it never leaves the cache store (A-32).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `embedder` | `EmbedderRef` | yes | operational | Producer. |
| `vector` | `tuple[float, ...]` | yes | content | The vector. |

### `RequestMeasurements`

All measurements taken before features (lifecycle stage 1).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `components` | `tuple[ComponentMeasurement, ...]` | yes | derived | One entry per component. |
| `fingerprint_key_id` | `str` | yes | operational | ID of the key the fingerprints used (ADR-0015). |
| `embedding` | `Embedding \| None` |  | content | Message embedding, if a consumer needs one. |
| `model_features` | `dict[Name, FeatureValue]` |  | derived | Measured model-based features, e.g. semantic intent (FR-FEAT-02). |
| `records` | `tuple[MeasurementRecord, ...]` |  | operational | Overhead of each measurement. |

### `ComponentTokens`

Token counts of one component for one target model.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `component` | `ComponentName` | yes | operational | Which component. |
| `total` | `TokenCount` | yes | derived | Whole component. |
| `per_item` | `tuple[TokenCount, ...]` |  | derived | Per turn, retrieved item, etc., in order. |

### `TargetTokenCounts`

Counts with the target's tokenizer, for the context stage (stage 5).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `model_id` | `Name` | yes | operational | Target model. |
| `components` | `tuple[ComponentTokens, ...]` | yes | derived | Present components only. |

**Enumerations**

- **`ComponentName`**: `message`, `history`, `instructions`, `retrieved`, `attachments`, `structured_input`. Request components, as named in keys, records, and events.

## `contracts.features`

Derived request features (CMP-04 output; FR-FEAT-01…05).

### `TurnFeatures`

Cheap features of one earlier user turn and who answered it (Demo milestone: sticky routing reads them, routing_plan §5). Content-free.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `language` | `Language` | yes | derived | Language of the user turn. |
| `has_code` | `bool` | yes | derived | Code detected in the user turn. |
| `has_coding_intent` | `bool` |  | derived | The turn asks for code or programming help, with no code in it. |
| `length_bucket` | `NonNegInt` | yes | derived | Length bucket of the turn. |
| `is_greeting` | `bool` | yes | derived | Greeting or small talk. |
| `producer_state` | `ComponentState` | yes | derived | State of the answering turn's producer. |
| `producer` | `Name \| None` |  | operational | Model ID or 'cache' that answered; None if absent, unknown, or no answer. |

### `RequestFeatures`

Features of one request. None means unknown (the component's state was unknown), not zero.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `feature_set_version` | `Version` | yes | operational | Feature-set version. |
| `language` | `Language` | yes | derived | Language of the current message. |
| `message_chars` | `NonNegInt` | yes | derived | Message length. |
| `message_tokens` | `TokenCount \| None` |  | derived | Message token estimate, with its method. |
| `known_input_tokens` | `TokenCount \| None` |  | derived | Cheap estimate over present components; unknown ones add nothing, so it is a lower bound. Used for the routing context-fit check. |
| `has_code` | `bool \| None` |  | derived | Code detected. |
| `has_coding_intent` | `bool \| None` |  | derived | Asks for code or programming help, with no code present (configured keywords, request cues, and templates). |
| `length_bucket` | `NonNegInt \| None` |  | derived | Message length bucket (configured character bounds). |
| `is_greeting` | `bool \| None` |  | derived | Greeting or small talk (configured phrase list). |
| `attachment_count` | `NonNegInt \| None` |  | derived | Attachments; None if unknown. |
| `attachment_modalities` | `tuple[Modality, ...]` |  | derived | Distinct modalities present. |
| `turn_depth` | `NonNegInt \| None` |  | derived | User turns before this one; None if history unknown. |
| `history_chars` | `NonNegInt \| None` |  | derived | History size. |
| `instructions_state` | `ComponentState` | yes | derived | Instructions state. |
| `instructions_chars` | `NonNegInt \| None` |  | derived | Instructions size. |
| `instructions_group` | `Fingerprint \| None` |  | fingerprint | Fingerprint of normalised instructions. |
| `retrieved_state` | `ComponentState` | yes | derived | Retrieved-context state. |
| `retrieved_items` | `NonNegInt \| None` |  | derived | Retrieved items. |
| `retrieved_chars` | `NonNegInt \| None` |  | derived | Retrieved size. |
| `structured_input_state` | `ComponentState` | yes | derived | Structured-input state (uncertain proxy, A-16). |
| `traffic_source_state` | `ComponentState` | yes | derived | Traffic-source state (reserved, Q-21). |
| `traffic_source_kind` | `Name \| None` |  | derived | Traffic-source kind, if present. |
| `traffic_source_provenance` | `Provenance \| None` |  | operational | Declared or inferred. |
| `history_turns` | `tuple[TurnFeatures, ...]` |  | derived | Earlier user turns, oldest first, with their producers (sticky routing). |
| `extra` | `dict[Name, FeatureValue]` |  | derived | Experimental or measured features (e.g. semantic intent). |

**Enumerations**

- **`Language`**: `fa`, `en`, `mixed`, `other`, `undetermined`. Output of the tested language detector (FR-FEAT-03).

## `contracts.reference_data`

Versioned reference data: model catalogue, price table, chat templates.

### `Sourced`

Where a fact came from and when it was checked.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `source` | `str` | yes | operational | URL or document reference. |
| `checked_on` | `date` | yes | operational | Date the source was read. |

### `Capability`

A declared capability. Unverified means unsupported (FR-ROUTE-05).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `name` | `Name` | yes | operational | e.g. image_input, provider_prompt_caching. |
| `verified` | `bool` | yes | operational | True only with a source. |
| `evidence` | `Sourced \| None` |  | operational | Required when verified. |

### `Limit`

A numeric model limit. ``value`` None means unknown.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `value` | `PosInt \| None` |  | operational | Limit in tokens. |
| `evidence` | `Sourced \| None` |  | operational | Source. |

### `CatalogueEntry`

One model Metis may route to.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `model_id` | `Name` | yes | operational | Internal, stable ID. |
| `provider` | `Name` | yes | operational | Provider family. |
| `provider_model_name` | `str` | yes | operational | Name in the provider's API. |
| `tier` | `NonNegInt` | yes | operational | Ordinal capability tier. |
| `equivalence_group` | `Name` | yes | operational | Failover group (FR-FAIL-03). |
| `context_window` | `Limit` | yes | operational | Context window. |
| `max_output_tokens` | `Limit` | yes | operational | Output limit. |
| `capabilities` | `tuple[Capability, ...]` |  | operational | Declared capabilities. |
| `tokenizer_ref` | `Name \| None` |  | operational | Tokenizer backend for this model. |
| `price_ref` | `Name \| None` |  | operational | Price-table key; None = price unknown. |
| `enabled` | `bool` | yes | operational | Disabled models are ineligible. |

### `ModelCatalogue`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `version` | `Version` | yes | operational | Catalogue version ID. |
| `entries` | `tuple[CatalogueEntry, ...]` | yes | operational | Models, in order. |

### `PriceEntry`

Price of one token type for one model, optionally for one context tier.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `price_ref` | `Name` | yes | operational | Key used by catalogue entries. |
| `token_type` | `TokenType` | yes | operational | Which tokens. |
| `amount` | `Decimal \| None` |  | operational | Price per ``per_tokens`` tokens. |
| `per_tokens` | `PosInt` | yes | operational | Unit, e.g. 1000000. |
| `currency` | `Currency` | yes | operational | ISO 4217. |
| `effective_from` | `date \| None` |  | operational | First day the price applies. |
| `evidence` | `Sourced \| None` |  | operational | Required when amount is set. |
| `tier` | `Name \| None` |  | operational | Context tier name, e.g. standard, long. |
| `min_input_tokens` | `NonNegInt \| None` |  | operational | Tier applies from this many input tokens. |
| `max_input_tokens` | `PosInt \| None` |  | operational | Tier applies up to this many input tokens. |
| `max_input_tokens_uncertain_up_to` | `PosInt \| None` |  | operational | The source's bound may really be this high (e.g. 270K read as 1,024s); inputs between the two bounds get a cost caveat. |
| `cache_ttl` | `Name \| None` |  | operational | Cache-write variant, e.g. ttl-5m; cache_write prices only. |

### `PriceTable`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `version` | `Version` | yes | operational | Price-table version ID. |
| `entries` | `tuple[PriceEntry, ...]` | yes | operational | Prices. |

### `ChatTemplate`

Message-framing tokens a provider adds around the content (the chat template), for counting input that the provider reports none for.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `tokenizer_ref` | `Name` | yes | operational | Tokenizer family it frames. |
| `version` | `Version` | yes | operational | Template version ID. |
| `sequence_start` | `NonNegInt` |  | operational | Tokens once per request (e.g. BOS). |
| `reply_priming` | `NonNegInt` |  | operational | Tokens that open the model's reply. |
| `role_prefix` | `dict[Name, NonNegInt]` |  | operational | Tokens before each part, by role. |
| `role_suffix` | `dict[Name, NonNegInt]` |  | operational | Tokens after each part, by role. |
| `fidelity` | `Fidelity` | yes | operational | How faithful the template is. |
| `evidence` | `Sourced` | yes | operational | Where the framing comes from. |

**Enumerations**

- **`TokenType`**: `input`, `output`, `cached_input`, `cache_write`, `reasoning`

## `contracts.routing`

The routing decision (CMP-05 output; FR-ROUTE-01…06, routing.md).

### `Exclusion`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `model_id` | `Name` | yes | operational | Excluded model. |
| `reason` | `ExclusionReason` | yes | operational | Why. |

### `RoutingDecision`

The chosen target and why (FR-ROUTE-02). Content-free.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `target_model_id` | `Name \| None` | yes | operational | Chosen model; None if nothing was eligible. |
| `equivalence_group` | `Name \| None` | yes | operational | Target's failover group; a cache-key component. |
| `tier` | `NonNegInt \| None` | yes | operational | Target's tier. |
| `eligible` | `tuple[Name, ...]` | yes | operational | Eligible models. |
| `exclusions` | `tuple[Exclusion, ...]` |  | operational | Excluded models and reasons. |
| `chain` | `tuple[Name, ...]` |  | operational | Escalation targets after the target, in order (ADR-0013). |
| `policy` | `PolicyRef` | yes | operational | Policy name and version. |
| `reason_code` | `Name` | yes | operational | Machine-readable reason, e.g. a rule ID. |
| `features_used` | `tuple[Name, ...]` |  | operational | Names of the features the policy read. |
| `min_context_window` | `PosInt \| None` |  | operational | Constraint applied on a re-route. |
| `flags` | `tuple[RoutingFlag, ...]` |  | operational | Flags. |
| `anchor_model_id` | `Name \| None` |  | operational | Sticky routing: the session's anchor model before this request, if any. |

**Enumerations**

- **`ExclusionReason`**: `modality_unsupported`, `capability_unverified`, `context_too_small`, `context_limit_unknown`, `below_min_window`, `disabled`, `unavailable`. Why the shared eligibility filter removed a model (routing.md §1.3).
- **`RoutingFlag`**: `unknown_price_selected`, `rerouted`, `requested_model_ignored`, `requested_model_honoured`

## `contracts.caching`

Cache key, entry, lookup result, and store decision (CMP-06, CMP-11).

### `CacheScope`

Who may reuse an entry. ``ref`` is the session or user reference.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `kind` | `ScopeKind` | yes | operational | Sharing scope. |
| `ref` | `Identifier \| None` |  | reference | Session or user ref; None for global. |

### `KeyComponent`

One content component of a key: its state and, if present, fingerprint.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `component` | `ComponentName` | yes | operational | Which component. |
| `state` | `ComponentState` | yes | derived | Present, absent, or unknown. |
| `fingerprint` | `Fingerprint \| None` |  | fingerprint | Set iff present. |
| `treatment` | `Name` | yes | operational | e.g. nfkc_casefold_ws, last_4_turns, full. |

### `CacheKeyDraft`

A composed key before fingerprinting (Stage 5).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `key_schema_version` | `Version` | yes | operational | Bumps invalidate entries. |
| `variant` | `Name` | yes | operational | Key variant, e.g. full, request_only. |
| `serving_allowed` | `bool` | yes | operational | False for measurement-only variants (P-5). |
| `components` | `tuple[KeyComponent, ...]` | yes | derived | Content components, in key order. |
| `target_group` | `Name \| None` | yes | operational | Target equivalence group; None if excluded by variant. |
| `scope` | `CacheScope` | yes | reference | Sharing scope. |

### `CacheKey`

A composed key (caching.md §1). Built by the cache policy for the serving variant, and by experiments for measurement variants.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `key_schema_version` | `Version` | yes | operational | Bumps invalidate entries. |
| `variant` | `Name` | yes | operational | Key variant, e.g. full, request_only. |
| `serving_allowed` | `bool` | yes | operational | False for measurement-only variants (P-5). |
| `components` | `tuple[KeyComponent, ...]` | yes | derived | Content components, in key order. |
| `target_group` | `Name \| None` | yes | operational | Target equivalence group; None if excluded by variant. |
| `scope` | `CacheScope` | yes | reference | Sharing scope. |
| `key` | `Fingerprint` | yes | fingerprint | Fingerprint of the whole key. |
| `partition_key` | `Fingerprint` | yes | fingerprint | Fingerprint of everything except the message. |

### `CacheEntry`

A stored answer. Holds content; lives only in the cache store.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `schema_version` | `Version` |  | operational | Contract version. |
| `entry_id` | `Identifier` | yes | reference | Entry ID. |
| `key` | `CacheKey` | yes | fingerprint | Key it was stored under. |
| `answer` | `str` | yes | content | The stored answer. |
| `producing_model_id` | `Name` | yes | operational | Model that answered. |
| `producing_tier` | `NonNegInt` | yes | operational | Its tier. |
| `created_at` | `UtcDatetime` | yes | operational | When stored. |
| `status` | `EntryStatus` | yes | operational | Usable only when complete. |
| `source_request_id` | `Identifier` | yes | reference | Request that produced it. |
| `embedding` | `Embedding \| None` |  | content | Message embedding, if the semantic tier is on. |
| `versions` | `Versions` | yes | operational | Versions at store time. |

### `IndexMatch`

One vector-index result (``VectorIndex.query``).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `entry_id` | `Identifier` | yes | reference | Matched entry. |
| `similarity` | `float` | yes | derived | Similarity under the index's function. |
| `embedder` | `EmbedderRef` | yes | operational | Embedder of both vectors. |

### `CacheLookupResult`

Outcome of one tier's lookup (FR-XCACHE-06). One per tier tried.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `tier` | `CacheTier` | yes | operational | Exact or semantic. |
| `outcome` | `LookupOutcome` | yes | operational | Hit, miss, or ineligible. |
| `ineligible_reason` | `IneligibleReason \| None` |  | operational | Set iff ineligible. |
| `invalid_reason` | `InvalidReason \| None` |  | operational | Set when an entry was found but rejected. |
| `key_variant` | `Name \| None` |  | operational | Variant used. |
| `key` | `Fingerprint \| None` |  | fingerprint | Key looked up. |
| `scope` | `ScopeKind \| None` |  | operational | Scope kind. |
| `entry_id` | `Identifier \| None` |  | reference | Matched entry; set on a hit. |
| `similarity` | `float \| None` |  | derived | Best similarity (semantic tier). |
| `threshold` | `float \| None` |  | operational | Threshold in force (semantic tier). |
| `embedder` | `EmbedderRef \| None` |  | operational | Embedder (semantic tier). |
| `candidates_considered` | `NonNegInt \| None` |  | derived | Index results examined (semantic tier). |
| `key_schema_version` | `Version \| None` |  | operational | Key schema version looked up (Stage E6). Not populated by any production code yet: always None until the cache lookup fills it. |
| `entry_age_ms` | `NonNegFloat \| None` |  | operational | Age of the matched entry on a hit (Stage E6). Not populated by any production code yet: always None until the cache lookup fills it. |
| `not_evaluated` | `tuple[Name, ...]` |  | operational | Configured checks that are no-ops, e.g. time_sensitivity (TODO-07). |

### `CacheStoreDecision`

Whether the final answer may be stored (caching.md §2 store rules).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `store` | `bool` | yes | operational | Store or skip. |
| `skip_reason` | `StoreSkipReason \| None` |  | operational | Set iff skipped. |

**Enumerations**

- **`ScopeKind`**: `session`, `user`, `global`
- **`EntryStatus`**: `complete`, `invalidated`
- **`CacheTier`**: `exact`, `semantic`
- **`LookupOutcome`**: `hit`, `miss`, `ineligible`
- **`IneligibleReason`**: `attachments`, `unknown_component`, `time_sensitive`, `scope_ref_missing`, `no_target`, `variant_not_serving`, `disabled`, `not_first_turn`
- **`InvalidReason`**: `expired`, `status`, `tier_too_low`, `below_threshold`, `verifier_failed`. Why a found entry was not usable (the lookup becomes a miss).
- **`StoreSkipReason`**: `not_eligible`, `served_from_cache`, `no_answer`, `error`, `truncated`, `content_filtered`, `unsatisfactory`, `disabled`

## `contracts.context`

The context plan for one target model (CMP-07; FR-CTX-01…04).

### `InputPart`

One ordered piece of model input.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `role` | `PartRole` | yes | derived | Generic role. |
| `text` | `str` | yes | content | The text. |
| `component` | `ComponentName` | yes | operational | Source component. |
| `item_index` | `NonNegInt \| None` |  | derived | Index within the component (turn, item). |

### `ComponentComposition`

What happened to one component (one row of the composition record).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `component` | `ComponentName` | yes | operational | Which component. |
| `state` | `ComponentState` | yes | derived | State in the request. |
| `action` | `ContextAction` | yes | operational | What the policy did. |
| `fingerprint` | `Fingerprint \| None` |  | fingerprint | Fingerprint of what was sent. |
| `tokens` | `TokenCount \| None` |  | derived | Tokens sent, with the target's tokenizer. |
| `items_total` | `NonNegInt \| None` |  | derived | Items before. |
| `items_kept` | `NonNegInt \| None` |  | derived | Items after. |

### `CompositionRecord`

Content-free record of one model input (FR-CTX-01).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `model_id` | `Name` | yes | operational | Target model. |
| `strategy` | `PolicyRef` | yes | operational | Context policy and version. |
| `components` | `tuple[ComponentComposition, ...]` | yes | derived | One row per component. |
| `input_tokens` | `TokenCount \| None` |  | derived | Total input tokens. |
| `reserved_output_tokens` | `NonNegInt \| None` |  | operational | Output tokens reserved. |
| `context_window` | `PosInt \| None` |  | operational | Target window; None if unknown. |
| `overflow` | `OverflowOutcome` | yes | operational | Overflow outcome. |
| `composition_fingerprint` | `Fingerprint \| None` |  | fingerprint | Fingerprint of the ordered parts; a replay-lookup key (ADR-0014). |

### `ContextPlan`

Ordered input parts for one target, plus their record.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `model_id` | `Name` | yes | operational | Target model. |
| `parts` | `tuple[InputPart, ...]` | yes | content | Ordered input. |
| `record` | `CompositionRecord` | yes | derived | Composition record. |

**Enumerations**

- **`PartRole`**: `instructions`, `user`, `assistant`, `retrieved`. Generic roles of input parts. Adapters map them to provider formats.
- **`ContextAction`**: `kept`, `trimmed`, `summarised`, `compressed`, `dropped`, `not_applicable`
- **`OverflowOutcome`**: `fits`, `trimmed_to_fit`, `reroute_requested`, `rejected`

## `contracts.model_io`

``ModelClient`` input and output (CMP-10; providers.md §1, §3; ADR-0014).

### `ModelInvocation`

One call to a model. Built by the pipeline from a ``ContextPlan``.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `request_id` | `Identifier` | yes | reference | Request. |
| `attempt_id` | `Identifier` | yes | reference | This attempt. |
| `attempt_kind` | `AttemptKind` | yes | operational | Why. |
| `model_id` | `Name` | yes | operational | Catalogue model. |
| `parts` | `tuple[InputPart, ...]` | yes | content | Ordered input. |
| `attachments` | `tuple[AttachmentRef, ...]` |  | content | Attachments to send. |
| `max_output_tokens` | `PosInt \| None` |  | operational | Generation limit. |
| `timeout_ms` | `PosInt \| None` |  | operational | Per-attempt timeout. |
| `case_id` | `Identifier \| None` |  | reference | Replay case, for replay-client lookup. |
| `composition_fingerprint` | `Fingerprint \| None` |  | fingerprint | Ordered-parts fingerprint (replay lookup). |
| `effort` | `Name \| None` |  | operational | Reasoning effort or thinking-budget label requested (None = the provider default). Stage E6: not yet applied by the live adapter. |

### `ModelResponse`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `outcome` | `Literal['response']` |  | operational | Discriminator. |
| `text` | `str` | yes | content | Answer text. |
| `finish_reason` | `FinishReason` | yes | operational | Normalised. |
| `usage` | `TokenUsage \| None` |  | derived | Provider-reported usage, if any. |
| `provider_latency_ms` | `NonNegFloat \| None` |  | operational | Latency as measured or recorded. |
| `provider_model_version` | `str \| None` |  | operational | Model version the provider reported. |
| `time_to_first_token_ms` | `NonNegFloat \| None` |  | operational | Time to the first streamed token, if the client measured it (Stage E6: no adapter measures it yet). |
| `source` | `AnswerSource` | yes | operational | Which client kind answered. |

### `ModelError`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `outcome` | `Literal['error']` |  | operational | Discriminator. |
| `error_class` | `ErrorClass` | yes | operational | Normalised class. |
| `retryable` | `bool` | yes | operational | Adapter's default for the class. |
| `provider_error_code` | `Name \| None` |  | operational | Provider code, never its message. |
| `provider_latency_ms` | `NonNegFloat \| None` |  | operational | Time until the error. |
| `source` | `AnswerSource` | yes | operational | Which client kind failed. |

### `ModelNoAnswer`

The counterfactual source has no answer for this target. Not an error: it lowers coverage (ADR-0014) and is never retried or failed over.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `outcome` | `Literal['no_answer']` |  | operational | Discriminator. |
| `reason` | `NoAnswerReason` | yes | operational | Why. |
| `source` | `AnswerSource` | yes | operational | Which client kind. |

**Enumerations**

- **`AttemptKind`**: `primary`, `retry`, `failover`, `escalation`. Why an attempt happened (ADR-0013).
- **`AnswerSource`**: `fake`, `logged`, `recorded`, `live`, `none`. Which kind of client produced a result (ADR-0014 counterfactual sources).
- **`FinishReason`**: `complete`, `length`, `content_filter`, `other`. Normalised by adapters (providers.md §1).
- **`ErrorClass`**: `timeout`, `rate_limited`, `unavailable`, `connection`, `context_overflow`, `content_filtered`, `invalid_request`, `auth`, `unknown`. Normalised error taxonomy (providers.md §3).
- **`NoAnswerReason`**: `not_recorded`, `target_not_logged_model`, `label_unmapped`, `proxy_source`

## `contracts.attempts`

Attempt state, actions, records, and detector verdicts (CMP-08; ADR-0013).

### `DetectorVerdict`

One detector's view of one answer (FR-CASC-05, attempts.md §4).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `detector` | `Name` | yes | operational | Detector ID. |
| `version` | `Version` | yes | operational | Detector version. |
| `state` | `VerdictState` | yes | operational | Evaluated or not. |
| `value` | `float \| None` |  | derived | Measured value. |
| `threshold` | `float \| None` |  | operational | Threshold. |
| `fired` | `bool` | yes | derived | Flags the answer as unsatisfactory. |

### `AttemptRecord`

Content-free summary of one finished attempt.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `attempt_id` | `Identifier` | yes | reference | Attempt. |
| `parent_attempt_id` | `Identifier \| None` |  | reference | Previous attempt in the chain. |
| `number` | `NonNegInt` | yes | operational | 0 for the primary attempt. |
| `kind` | `AttemptKind` | yes | operational | Why it happened. |
| `model_id` | `Name` | yes | operational | Model called. |
| `provider` | `Name` | yes | operational | Provider. |
| `outcome` | `AttemptOutcome` | yes | operational | What came back. |
| `source` | `AnswerSource \| None` |  | operational | Client kind; None if blocked before a call. |
| `error_class` | `ErrorClass \| None` |  | operational | Set iff outcome is error. |
| `finish_reason` | `FinishReason \| None` |  | operational | Set iff outcome is response. |
| `usage` | `TokenUsage \| None` |  | derived | Usage, best fidelity. |
| `cost` | `Cost \| None` |  | operational | Charged cost. |
| `duration_ms` | `NonNegFloat \| None` |  | operational | model_call span duration. |
| `effort` | `Name \| None` |  | operational | Effort label requested (Stage E6). Not populated by any production code yet: always None until a producer fills it. |
| `time_to_first_token_ms` | `NonNegFloat \| None` |  | operational | Time to first token (Stage E6). Not populated by any production code yet: always None until an adapter measures it. |
| `verdicts` | `tuple[DetectorVerdict, ...]` |  | derived | Detector verdicts on a response. |
| `unsatisfactory` | `bool \| None` |  | derived | Combined verdict; None if not a response. |

### `AttemptState`

Everything the attempt policy may read (attempts.md §1).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `request_id` | `Identifier` | yes | reference | Request. |
| `decision` | `RoutingDecision` | yes | operational | Routing decision. |
| `attempts` | `tuple[AttemptRecord, ...]` |  | operational | Finished attempts, oldest first. |
| `deadline_remaining_ms` | `float \| None` |  | operational | Time left; None if no deadline. |
| `budget_remaining` | `Money \| None` |  | operational | Spend cap left; None if no cap applies. |
| `rerouted` | `bool` |  | operational | A re-route already happened. |

### `AttemptAction`

The attempt policy's next step.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `action` | `ActionKind` | yes | operational | Invoke, return, or fail. |
| `reason` | `Name` | yes | operational | Machine-readable reason. |
| `target_model_id` | `Name \| None` |  | operational | Set iff invoke. |
| `kind` | `AttemptKind \| None` |  | operational | Set iff invoke. |
| `backoff_ms` | `NonNegFloat \| None` |  | operational | Wait before invoking (retries). |
| `return_attempt_id` | `Identifier \| None` |  | reference | Set iff return: which answer. |
| `unsatisfactory_returned` | `bool` |  | derived | Returning an answer a detector flagged. |
| `failure` | `FailureReason \| None` |  | operational | Set iff fail. |

**Enumerations**

- **`VerdictState`**: `evaluated`, `not_evaluated`
- **`AttemptOutcome`**: `response`, `error`, `no_answer`, `budget_blocked`
- **`ActionKind`**: `invoke`, `return`, `fail`
- **`FailureReason`**: `no_eligible_model`, `all_attempts_failed`, `deadline_exceeded`, `budget_exhausted`, `context_overflow`, `no_answer`, `content_filtered`. Why a request ends without an answer (lifecycle §1 terminal outcomes).

## `contracts.response`

Latency spans, response metadata, and the final response (CMP-01 output).

### `SpanTiming`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `span` | `SpanName` | yes | operational | Lifecycle span. |
| `duration_ms` | `NonNegFloat` | yes | operational | Duration. |
| `source` | `LatencySource` | yes | operational | Where the number came from. |
| `attempt_id` | `Identifier \| None` |  | reference | For attempt and call spans. |

### `ResponseMetadata`

Content-free account of how a request was answered (FR-API-01).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `request_id` | `Identifier` | yes | reference | Minted by the pipeline. |
| `caller_request_ref` | `Identifier \| None` |  | reference | Echo of the caller's ref. |
| `served_by` | `ServedBy` | yes | operational | Cache, model, or none. |
| `final_model_id` | `Name \| None` |  | operational | Model of the returned answer (cache: producing model). |
| `cache_tier` | `CacheTier \| None` |  | operational | On a hit. |
| `cache_entry_id` | `Identifier \| None` |  | reference | On a hit. |
| `attempt_ids` | `tuple[Identifier, ...]` |  | reference | All attempts, in order. |
| `answer_usage` | `TokenUsage \| None` |  | derived | Usage of the returned answer's attempt. |
| `total_cost` | `Cost` | yes | operational | All attempts plus overhead (FR-ACCT-03). |
| `overhead_cost` | `Cost` | yes | operational | Router, embedder, judge, verifier. |
| `avoided_cost` | `Cost \| None` |  | operational | On a cache hit (FR-ACCT-04). |
| `savings` | `tuple[Savings, ...]` |  | operational | One per configured baseline. |
| `spans` | `tuple[SpanTiming, ...]` |  | operational | Span timings. |
| `retries` | `NonNegInt` |  | operational | Retry attempts. |
| `failovers` | `NonNegInt` |  | operational | Failover attempts. |
| `escalations` | `NonNegInt` |  | operational | Escalation attempts. |
| `unsatisfactory_returned` | `bool` |  | derived | Returned an answer a detector flagged. |
| `failure` | `FailureReason \| None` |  | operational | Set iff status is error. |
| `versions` | `Versions` | yes | operational | Versions in force. |

### `FinalResponse`

What the pipeline returns. Expected failures are an error status, not an exception (ADR-0010 point 6).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `status` | `ResponseStatus` | yes | operational | OK or error. |
| `answer` | `str \| None` |  | content | Set iff OK. |
| `metadata` | `ResponseMetadata` | yes | operational | How it was answered. |

**Enumerations**

- **`SpanName`**: `request`, `measure`, `features`, `route`, `cache_lookup.exact`, `cache_lookup.semantic`, `embed`, `context`, `context.compress`, `attempt`, `model_call`, `measurement_call`, `cache_store`, `respond`
- **`LatencyCategory`**: `overhead`, `model`, `end_to_end`, `container`, `post_response`. ADR-0006 latency split.
- **`LatencySource`**: `measured_local`, `provider_reported`, `recorded`, `simulated`
- **`ResponseStatus`**: `ok`, `error`
- **`ServedBy`**: `cache`, `model`, `none`

## `contracts.events`

Events: the single measurement record (ADR-0012, observability.md §3).

### `RequestReceived`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['request_received']` |  | operational | Discriminator. |
| `components` | `tuple[ComponentMeasurement, ...]` | yes | derived | State, size, fingerprint per component. |
| `traffic_source` | `Component[TrafficSource]` |  | derived | Reserved (Q-21). |
| `pairing_flag` | `PairingFlag \| None` |  | operational | Replay only. |

### `FeaturesExtracted`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['features_extracted']` |  | operational | Discriminator. |
| `features` | `RequestFeatures` | yes | derived | Features. |
| `measurements` | `tuple[MeasurementRecord, ...]` |  | operational | Measurement overhead. |

### `RoutingDecided`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['routing_decided']` |  | operational | Discriminator. |
| `decision` | `RoutingDecision` | yes | operational | The decision. |

### `CacheLookedUp`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['cache_lookup']` |  | operational | Discriminator. |
| `result` | `CacheLookupResult` | yes | operational | One tier's outcome. |

### `CacheStored`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['cache_stored']` |  | operational | Discriminator. |
| `entry_id` | `Identifier` | yes | reference | New entry. |
| `key_variant` | `Name` | yes | operational | Variant. |
| `scope` | `ScopeKind` | yes | operational | Scope kind. |
| `semantic_indexed` | `bool` | yes | operational | Vector added to the index. |

### `CacheStoreSkipped`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['cache_store_skipped']` |  | operational | Discriminator. |
| `reason` | `StoreSkipReason` | yes | operational | Why. |

### `ContextBuilt`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['context_built']` |  | operational | Discriminator. |
| `record` | `CompositionRecord` | yes | derived | Composition record. |

### `CompressedComponent`

What a compressor did to one component (sizes only).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `component` | `ComponentName` | yes | operational | Which component. |
| `items_compressed` | `NonNegInt` | yes | derived | Items compressed. |
| `items_skipped` | `NonNegInt` | yes | derived | Items left as they were (below the minimum length). |
| `chars_before` | `NonNegInt` | yes | derived | Characters before. |
| `chars_after` | `NonNegInt` | yes | derived | Characters after. |
| `tokens_before` | `NonNegInt` | yes | derived | Compressor tokens before (not the target's tokens). |
| `tokens_after` | `NonNegInt` | yes | derived | Compressor tokens after. |

### `ContextCompressed`

A context compressor ran (Demo milestone, experimental; brief §9). Its time is overhead (span ``context.compress``); the target-token saving is the decomposition's compression term.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['context_compressed']` |  | operational | Discriminator. |
| `compressor` | `PolicyRef` | yes | operational | Compressor and version. |
| `rate` | `float` | yes | operational | Configured share of tokens kept. |
| `token_method` | `str` | yes | operational | How compressor tokens were counted. |
| `components` | `tuple[CompressedComponent, ...]` | yes | derived | Per compressed component. |

### `AttemptStarted`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['attempt_started']` |  | operational | Discriminator. |
| `kind` | `AttemptKind` | yes | operational | Why. |
| `number` | `NonNegInt` | yes | operational | 0 for primary. |
| `model_id` | `Name` | yes | operational | Target. |
| `provider` | `Name` | yes | operational | Provider. |

### `AttemptFinished`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['attempt_finished']` |  | operational | Discriminator. |
| `record` | `AttemptRecord` | yes | operational | Outcome, usage, cost, verdicts. |
| `provider_model_version` | `str \| None` |  | operational | As reported. |

### `RetryScheduled`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['retry_scheduled']` |  | operational | Discriminator. |
| `from_attempt_id` | `Identifier` | yes | reference | Failed attempt. |
| `model_id` | `Name` | yes | operational | Same model. |
| `error_class` | `ErrorClass` | yes | operational | Cause. |
| `backoff_ms` | `NonNegFloat` | yes | operational | Wait. |

### `FailoverTriggered`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['failover_triggered']` |  | operational | Discriminator. |
| `from_model_id` | `Name` | yes | operational | From. |
| `to_model_id` | `Name` | yes | operational | To. |
| `equivalence_group` | `Name` | yes | operational | Shared group. |
| `error_class` | `ErrorClass \| None` |  | operational | Cause. |

### `EscalationTriggered`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['escalation_triggered']` |  | operational | Discriminator. |
| `from_model_id` | `Name` | yes | operational | From. |
| `to_model_id` | `Name` | yes | operational | To. |
| `from_tier` | `NonNegInt` | yes | operational | From tier. |
| `to_tier` | `NonNegInt` | yes | operational | To tier. |
| `verdicts` | `tuple[DetectorVerdict, ...]` | yes | derived | Every verdict (FR-CASC-05). |

### `BudgetBlocked`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['budget_blocked']` |  | operational | Discriminator. |
| `estimate` | `CostEstimate` | yes | operational | Pre-call estimate. |
| `cap_remaining` | `Money \| None` |  | operational | Cap left. |

### `ResponseReturned`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['response_returned']` |  | operational | Discriminator. |
| `status` | `ResponseStatus` | yes | operational | OK or error. |
| `metadata` | `ResponseMetadata` | yes | operational | Totals and flags. |

### `EvaluationScored`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['evaluation_scored']` |  | operational | Discriminator. |
| `metrics` | `tuple[MetricValue, ...]` | yes | derived | Per-case metrics. |

### `RunStarted`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['run_started']` |  | operational | Discriminator. |
| `experiment_id` | `Name` | yes | operational | EXP ID. |
| `manifest_ref` | `str` | yes | operational | Run-relative path of the manifest. |

### `RunFinished`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `event_type` | `Literal['run_finished']` |  | operational | Discriminator. |
| `cases_total` | `NonNegInt` | yes | derived | Cases offered. |
| `cases_run` | `NonNegInt` | yes | derived | Cases replayed. |
| `exclusions` | `tuple[ExclusionCount, ...]` |  | derived | FR-EVAL-08. |
| `completed` | `bool` | yes | operational | False if the run stopped early. |

### `Event`

Envelope plus payload (FR-OBS-02). Written by the event recorder.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `schema_version` | `Version` |  | operational | Contract version. |
| `event_id` | `Identifier` | yes | reference | Unique and ordered within a run. |
| `event_type` | `Name` | yes | operational | Equals payload.event_type. |
| `run_id` | `Identifier` | yes | reference | Run or process lifetime. |
| `run_mode` | `RunMode` | yes | operational | Replayed, simulated, or live. |
| `request_id` | `Identifier \| None` |  | reference | None only for run-level events. |
| `session_ref` | `Identifier \| None` |  | reference | Session. |
| `case_id` | `Identifier \| None` |  | reference | Replay case. |
| `attempt_id` | `Identifier \| None` |  | reference | Attempt. |
| `parent_attempt_id` | `Identifier \| None` |  | reference | Previous attempt. |
| `timestamp` | `UtcDatetime` | yes | operational | When emitted (aware UTC). |
| `logged_timestamp` | `LoggedTimestamp \| None` |  | operational | Replay only: naive logged time (A-06). |
| `span` | `SpanName \| None` |  | operational | Span this event closes. |
| `duration_ms` | `NonNegFloat \| None` |  | operational | Span duration (monotonic clock). |
| `versions` | `Versions` | yes | operational | Versions in force. |
| `payload` | `EventPayload` | yes | derived | Typed, content-free payload. |

**Enumerations**

- **`RunMode`**: `replayed`, `simulated`, `live`. FR-OBS-03: one schema for replay and online.

## `contracts.replay`

Logged sessions and replay cases (CMP-18 output; FR-REQ-03…06, FR-DATA-06).

### `DataQualityFlag`

A loader's warning about a component, e.g. possibly truncated (A-14). Flags are codes documented by each loader; policies never read them.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `component` | `ComponentName` | yes | operational | Affected component. |
| `flag` | `Name` | yes | operational | e.g. possibly_truncated. |

### `LoggedMessage`

One logged message. Every metadata field is tri-state: a loader sets only what its dataset actually records.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `position` | `NonNegInt` | yes | operational | Index in the session's log order. |
| `role` | `Role` | yes | derived | Mapped by the loader to a generic role. |
| `text` | `str` | yes | content | Message text. |
| `message_ref` | `Identifier \| None` |  | reference | Opaque message ID, if the dataset has one. |
| `logged_timestamp` | `LoggedTimestamp \| None` |  | operational | Naive; timezone unknown (A-06). |
| `model_label` | `Component[str]` |  | operational | Logged model label; not a billing entity (A-07). |
| `provider_label` | `Component[str]` |  | operational | Logged provider label. |
| `instructions` | `Component[str]` |  | content | Logged instructions. |
| `retrieved` | `Component[RetrievedContext]` |  | content | Logged retrieved context. |
| `attachments` | `Component[tuple[AttachmentRef, ...]]` |  | content | Logged attachments. |
| `structured_input` | `Component[dict[str, JsonValue]]` |  | content | Logged structured-input configuration (uncertain proxy, A-16). |
| `quality_flags` | `tuple[DataQualityFlag, ...]` |  | operational | Loader warnings about this message, e.g. possibly truncated (A-14). |

### `Session`

A logged conversation, in log order.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `session_ref` | `Identifier` | yes | reference | Opaque or keyed reference, never the raw dataset ID. |
| `dataset` | `Name` | yes | operational | Dataset ID, e.g. sample_v1. |
| `stratum` | `Identifier \| None` |  | reference | Opaque category stratum; never interpreted (A-02). |
| `logged_created_at` | `LoggedTimestamp \| None` |  | operational | Naive session creation time, if logged. |
| `messages` | `tuple[LoggedMessage, ...]` | yes | content | Messages in log order. |

### `Reference`

A logged answer paired with a case. Visible to metrics only, never to the pipeline (FR-REQ-06).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `position` | `NonNegInt` | yes | operational | Position of the logged answer. |
| `text` | `str` | yes | content | Logged answer text. |
| `model_label` | `Component[str]` |  | operational | Label of the model that answered. |
| `provider_label` | `Component[str]` |  | operational | Provider label. |
| `logged_timestamp` | `LoggedTimestamp \| None` |  | operational | Naive timestamp. |

### `ReplayCase`

One replayable request as it would have been seen at its turn.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `case_id` | `Identifier` | yes | reference | Minted by the case builder. |
| `session_ref` | `Identifier` | yes | reference | Session. |
| `turn_index` | `NonNegInt` | yes | operational | User turn within the session. |
| `request` | `Request` | yes | content | Only what came before this turn. |
| `references` | `tuple[Reference, ...]` | yes | content | Paired logged answers; may be empty or several. |
| `pairing_method` | `PairingMethod` | yes | operational | How pairs were formed. |
| `pairing_flag` | `PairingFlag` | yes | operational | Pairing quality. |
| `logged_timestamp` | `LoggedTimestamp \| None` |  | operational | Naive time of the user message. |
| `stratum` | `Identifier \| None` |  | reference | Opaque stratum. |
| `quality_flags` | `tuple[DataQualityFlag, ...]` |  | operational | Loader warnings. |

**Enumerations**

- **`PairingMethod`**: `request_id`, `heuristic_array_order`
- **`PairingFlag`**: `clean`, `multiple_answers`, `no_preceding_user`, `skipped_consecutive_user`, `unanswered`. Pairing quality (FR-REQ-03). ``no_preceding_user`` never becomes a case: it is counted as an exclusion (FR-EVAL-08).

## `contracts.evaluation`

Evaluation results and run manifests (CMP-23, CMP-24; ADR-0006, ADR-0014).

### `Interval`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `low` | `float` | yes | derived | Lower bound. |
| `high` | `float` | yes | derived | Upper bound. |
| `level` | `float` | yes | operational | e.g. 0.95. |
| `method` | `Name` | yes | operational | e.g. bootstrap_percentile. |

### `MetricValue`

One metric, with its sample size and qualifiers.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `name` | `MetricName` | yes | operational | Metric. |
| `state` | `MetricState` | yes | operational | Measured or why not. |
| `value` | `float \| None` |  | derived | Set iff measured. |
| `unit` | `Name \| None` |  | operational | e.g. ratio, ms, usd. |
| `n` | `NonNegInt` | yes | derived | Cases the value is computed over. |
| `interval` | `Interval \| None` |  | derived | Uncertainty. |
| `reason` | `Name \| None` |  | operational | Why unmeasured or not computed. |
| `baseline` | `Name \| None` |  | operational | Baseline compared against, if any. |
| `key_variant` | `Name \| None` |  | operational | Cache key variant (cache metrics). |
| `scope` | `Name \| None` |  | operational | Cache scope measured (cache metrics). |
| `judge` | `Version \| None` |  | operational | Judge ID@version. |
| `token_fidelity` | `Fidelity \| None` |  | operational | Worst fidelity (cost metrics). |
| `price_table_version` | `Version \| None` |  | operational | Price table (cost metrics). |

### `JudgeScore`

One judge's score for one answer (``Judge`` port output, CMP-15).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `judge` | `Version` | yes | operational | Judge ID@version. |
| `rubric` | `Name` | yes | operational | Rubric ID. |
| `state` | `MetricState` | yes | operational | Measured or why not. |
| `score` | `float \| None` |  | derived | Set iff measured. |
| `reason` | `Name \| None` |  | operational | Why not measured. |
| `cost` | `Cost \| None` |  | operational | Cost of the judge call. |

### `StratumKey`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `dimension` | `Name` | yes | operational | e.g. category, language, turn_depth. |
| `value` | `Identifier` | yes | reference | Stratum value (opaque for category). |

### `StratumResult`

Metrics for one stratum. An empty ``stratum`` means overall.

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `stratum` | `tuple[StratumKey, ...]` | yes | reference | Stratum; () = overall. |
| `n_cases` | `NonNegInt` | yes | derived | Cases in the stratum. |
| `metrics` | `tuple[MetricValue, ...]` | yes | derived | Metrics. |

### `ExclusionCount`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `reason` | `Name` | yes | operational | e.g. a pairing flag, unknown_metadata. |
| `count` | `NonNegInt` | yes | derived | Records excluded or flagged. |

### `EvaluationResult`

Results of one run (FR-EVAL-03, 06, 08, 09).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `schema_version` | `Version` |  | operational | Contract version. |
| `run_id` | `Identifier` | yes | reference | Run. |
| `experiment_id` | `Name` | yes | operational | EXP ID (Stage 8). |
| `counterfactual_source` | `CounterfactualSource` | yes | operational | ADR-0014. |
| `cases_total` | `NonNegInt` | yes | derived | Cases offered. |
| `cases_covered` | `NonNegInt` | yes | derived | Cases the source answered; quality uses only these. |
| `baselines` | `tuple[Name, ...]` | yes | operational | Baselines reported. |
| `results` | `tuple[StratumResult, ...]` | yes | derived | Overall first. |
| `exclusions` | `tuple[ExclusionCount, ...]` |  | derived | Excluded or flagged records. |

### `CodeVersion`

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `commit` | `str \| None` |  | operational | Git commit, if known. |
| `dirty` | `bool \| None` |  | operational | Uncommitted changes. |

### `RunManifest`

Everything needed to reproduce and compare a run (FR-EVAL-07).

| Field | Type | Req. | Privacy | Description |
|---|---|---|---|---|
| `schema_version` | `Version` |  | operational | Contract version. |
| `run_id` | `Identifier` | yes | reference | Run. |
| `experiment_id` | `Name` | yes | operational | EXP ID. |
| `started_at` | `UtcDatetime` | yes | operational | Start time. |
| `code` | `CodeVersion` | yes | operational | Code version. |
| `dataset` | `Name` | yes | operational | Dataset ID. |
| `data_hash` | `str \| None` |  | operational | Hash of the dataset file(s). |
| `seed` | `int \| None` |  | operational | Seed. |
| `versions` | `Versions` | yes | operational | Config hash, key ID, versions. |
| `counterfactual_source` | `CounterfactualSource` | yes | operational | ADR-0014. |
| `prompt_composition_assumption` | `Name` | yes | operational | Assumed composition ID (context_construction.md §4). |
| `history_mode` | `Name` | yes | operational | e.g. logged_history (A-30, ADR-0014 point 5). |
| `ordering_rule` | `Name` | yes | operational | Case ordering (A-31). |
| `pairing_flags_included` | `tuple[PairingFlag, ...]` | yes | operational | Flags admitted to the run. |
| `live_calls` | `bool` | yes | operational | Whether live calls were enabled. |
| `spend_cap` | `Money \| None` |  | operational | Cap, if live. |
| `hardware` | `str \| None` |  | operational | Machine description (A-22). |

**Enumerations**

- **`CounterfactualSource`**: `fake`, `logged_match`, `recorded`, `live`, `proxy`. ADR-0014. Declared by every run.
- **`MetricName`**: `agreement`, `judge_score`, `non_inferiority`, `candidate_hit_rate`, `hit_rate`, `hit_correctness`, `false_hit_rate`, `cost_per_request`, `total_cost`, `savings`, `overhead_latency_p50`, `overhead_latency_p95`, `model_latency`, `end_to_end_latency`, `escalation_rate`, `failover_rate`, `retry_rate`, `router_overhead`, `coverage`. Known metrics. Quality is three separate metrics, never one score.
- **`MetricState`**: `measured`, `unmeasured`, `not_computed`
