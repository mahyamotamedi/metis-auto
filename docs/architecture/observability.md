# Observability: Events, Correlation, Metrics (Stage 3)

Status: event-stream approach **decided** ([ADR-0012](../adr/0012-event-stream-as-measurement-record.md)); event types and envelope **fixed in Stage 4** as contracts ([contracts.md §3.6](contracts.md#36-events)); individual fields provisional; the Stage 5 recorder (`application/events/recorder.py`) emits them. Last updated 2026-10-18.
Index: [architecture README](README.md). Components: CMP-03 (event recorder), CMP-14 (sinks), CMP-23 (aggregates). Requirements: FR-OBS-01…06, QA-PRIV.

---

## 1. Principle

Events are the **single measurement record**. Tokens, cost, savings, latency, cache outcomes, routing mix, escalation, and failover are all computed *from events*, by the same aggregation code in evaluation and, later, in the dashboard. Nothing on the request path keeps its own counters that could disagree with the events.

---

## 2. Correlation and spans

| ID | Scope | Minted by | Notes |
|---|---|---|---|
| `run_id` | one experiment run, or one process lifetime online | runner / gateway | In every event. |
| `request_id` | one request | pipeline (IdSource) | FR-REQ-02. |
| `session_ref` | the conversation | caller | An opaque ID or keyed fingerprint, never a raw identifier from the data. |
| `user_ref` | optional, privacy-safe | caller | Needed for `user` scope (ADR-0007). Absent in the sample. |
| `case_id` | one replay case | replay harness | Links an event to its reference without carrying content. |
| `attempt_id` | one attempt (model call, retry, failover, escalation) or one measurement call (router, embedder, judge) | pipeline | Links to `request_id`, and to the previous attempt via `parent_attempt_id`. |
| `event_id` | one event | recorder | Unique and ordered within a run. |

**Spans.** Each event that closes a span carries the span name and a duration measured with the monotonic clock. The request span has these children: `measure`, `features`, `route`, `cache_lookup.exact`, `cache_lookup.semantic` (with `embed`), `context`, `attempt[n]` (with `model_call`; time to first token later, FR-API-04), `cache_store`, `respond`.
- **Overhead** (QA-LAT a) = `measure` + `features` + `route` + `cache_lookup.*` + `context` + router, judge, and verifier measurement calls.
- **Model latency** (QA-LAT b) = `model_call` spans. Live or recorded only.
- **End to end** (QA-LAT c) = the request span.

Durations recorded during replay with fake clients measure Metis's own code only. The run manifest records the hardware (A-22).

---

## 3. Event envelope and types

**Envelope** (on every event). Fixed in Stage 4 as `Event` with one typed payload per type below ([contracts.md §3.6](contracts.md#36-events); fields in [contracts_reference.md](contracts_reference.md#contractsevents)). The Stage 3 list was: `event_id`, `event_type`, `schema_version`, `run_id`, `run_mode` (`replayed` / `simulated` / `live`), `request_id`, `session_ref`, `case_id`, `attempt_id`, `parent_attempt_id`, `timestamp` (UTC, aware), `logged_timestamp` (replay only; naive, timezone unknown), `span`, `duration_ms`, `versions` (config hash, policy name and version per policy, feature set, catalogue, price table, key schema, embedder, judge), `payload`.

**Payloads carry no raw content** (FR-OBS-02). Allowed: IDs, keyed fingerprints, sizes, counts, enumerations, scores, money, durations, versions. Stage 4 tests assert that no event field, at any depth, has the `content` privacy class, and that serialised synthetic events contain no synthetic content ([contracts.md §2.2](contracts.md#22-privacy-classes)).

| Event type | Payload highlights | Requirements |
|---|---|---|
| `request_received` | component presence (present/absent/unknown), sizes, pairing flag (replay) | FR-REQ-01, 03, 04 |
| `features_extracted` | feature values, feature-set version, measurement costs | FR-FEAT-01…04 |
| `routing_decided` | target, group, tier, candidates, exclusions + reasons, policy and version, reason code, chain | FR-ROUTE-02, 04 |
| `cache_lookup` | tier, eligibility + reason, key variant, scope, hit/miss, entry ID, similarity, threshold, embedder | FR-XCACHE-06, FR-SCACHE-04 |
| `cache_stored` / `cache_store_skipped` | entry ID, scope, reason if skipped | FR-XCACHE-04 |
| `context_built` | composition record, overflow outcome | FR-CTX-01, 04 |
| `attempt_started` | kind, target, provider, attempt number | FR-REQ-02 |
| `attempt_finished` | outcome, error class, finish reason, `TokenUsage` (with fidelity), `Cost` (with price version), model latency, provider-reported model version if returned | FR-ACCT-01, 02, FR-FAIL-04 |
| `retry_scheduled` / `failover_triggered` | from and to, error class, backoff | FR-FAIL-01, 02 |
| `escalation_triggered` | from and to tier, every `DetectorVerdict` | FR-CASC-05 |
| `budget_blocked` | estimate, cap remaining | ADR-0003 |
| `response_returned` | served by (cache / model / error), final model, totals: tokens, cost, overhead, avoided cost, savings per baseline, status | FR-ACCT-03…05 |
| `evaluation_scored` | case ID, metric values (agreement, judge score with judge version), states such as "unmeasured" | FR-EVAL-03, 05 |
| `run_started` / `run_finished` | manifest reference, counts, exclusions | FR-EVAL-07, 08 |

---

## 4. What the deferred dashboard would read (FR-OBS-05)

Every dashboard figure in the brief is derivable from the events above. This table is the test of "no redesign needed" (Q-17).

| Dashboard figure | Derived from |
|---|---|
| Tokens saved by caching | `cache_lookup` hits joined with `response_returned` avoided-cost estimates (token counts and method) |
| Cost saved by routing | `response_returned` cost vs. baseline costs (both baselines) |
| Total cost and cost per request, by component | `attempt_finished` costs + measurement costs, grouped by attempt kind |
| Latency distribution | span durations: overhead, model, end-to-end |
| Routing mix and reasons | `routing_decided` |
| Hit rate and false-hit rate | `cache_lookup` + `evaluation_scored` (hit correctness) |
| Escalation and failover rates | `escalation_triggered`, `failover_triggered`, `retry_scheduled` per request |
| Budget usage | `attempt_finished` live costs, `budget_blocked` |

"Real-time" display is an online-phase concern. It needs a streaming sink, not a different event model (FR-OBS-06).

---

## 5. Coverage of the EDA's "requirements for the full dataset" (FR-OBS-04)

| Field the EDA asked for | Produced by |
|---|---|
| Request-linked exact input, output, and billed tokens | `attempt_finished.TokenUsage` (provider-reported when live; fidelity labelled) |
| Normalised model, version, provider | `attempt_started` target and provider; `attempt_finished` provider-reported version |
| Request and provider cost | `attempt_finished.Cost`, `response_returned` totals |
| Lifecycle latency including time to first token | spans; time to first token when streaming arrives (FR-API-04) |
| Retries and failures | `retry_scheduled`, `failover_triggered`, `attempt_finished` error class |
| Selected model and routing decision and reason | `routing_decided` |
| Cache eligibility, lookup, hit, invalidation, outcome | `cache_lookup`, `cache_stored`; invalidation events when FR-XCACHE-09 operations exist |
| Retrieval document IDs and scores; actual prompt composition | `context_built` composition record (fingerprints, sizes). Document IDs and scores only if the caller supplies them: `RetrievedItem.document_ref` and `.score` (Stage 4). |
| Quality and evaluation labels | `evaluation_scored` |
| Privacy-safe customer or workload grouping | `user_ref`, opaque category as a stratum |
| Timezone and clock semantics; stable correlation IDs | aware UTC `timestamp`; §2 IDs |

---

## 6. Sinks and logs

- `EventSink` port. Adapters now: in-memory (tests) and JSON Lines per run under `runs/` (gitignored). Later: database, or an exporter to a tracing or metrics backend (for example OpenTelemetry). That would be one more adapter.
- **Emission is synchronous and in-process** today. A sink failure fails an offline run, because a run with missing events is not a valid measurement. The online phase will need a non-blocking sink that counts dropped events instead; that is noted for the gateway.
- **Operator logs** (Python `logging`) are for diagnostics. They follow the same no-content rule, and they are not a measurement source.
