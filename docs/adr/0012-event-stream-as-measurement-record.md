# ADR-0012: The event stream is the single measurement record

- Status: **decided** (approach). The event type list and fields are **provisional** until Stage 4.
- Date: 2026-10-14
- Relates to: FR-OBS-01…06, FR-EVAL-03, FR-EVAL-07, ADR-0005 (dashboard deferred), Q-17
- Detail: [observability.md](../architecture/observability.md)

## Context
Every decision point must be measurable (MP§4). The deferred dashboard must be addable without redesign (Q-17). Offline evaluation and the online phase must share one event schema (FR-OBS-03). If counters, logs, and evaluation code each recorded their own numbers, they could disagree.

## Decision
1. Every pipeline stage emits structured, typed events with a shared envelope: correlation IDs (run, request, session, case, attempt), timestamps, span and duration, versions in force, and run mode.
2. **All metrics are derived from events**, by aggregation code in `evaluation`: tokens, cost, savings, latency, cache and routing outcomes, escalation, and failover. The request path keeps no separate counters.
3. Payloads carry no raw content, only IDs, keyed fingerprints, derived values, money, and durations. A Stage 4 test enforces privacy classes.
4. Sinks are behind the `EventSink` port: in-memory and JSON Lines now; a database or tracing exporter later.
5. Offline, a sink failure fails the run. The online phase will need a non-blocking sink with drop counting.

## Alternatives considered
- **Use OpenTelemetry tracing as the record.** Its spans fit well, but it adds a dependency and a collector before any online need exists, and its attribute model is generic rather than typed. Rejected as the record. It remains a future *exporter* adapter.
- **Metrics counters on the request path** (Prometheus style). They are cheap to read, but they cannot recompute a metric under a new definition, and they lose per-request detail that evaluation needs. Rejected.
- **Evaluation computes metrics directly from pipeline return values.** This is simpler for the first experiment, but online and offline would then compute metrics differently, and the dashboard would need a new source. Rejected.

## Consequences
- The event schema must be rich enough for the dashboard. Observability §4 maps each dashboard figure to events.
- Event volume grows with detail. JSON Lines is enough for sample and full-dataset replay; the online phase may need sampling, which is noted.
- Stage 4 makes events the most-tested contracts.
