# Architecture Index

Stage 3 architecture of Metis-Auto. Read [overview.md](overview.md) first: it has the principles, the component catalogue (`CMP-nn`), and the contract vocabulary that every other document uses. Last updated 2026-10-14.

Status legend: **decided** · **provisional** (working answer, may change with evidence) · **open** (needs a decision or data). Every document states its own status.

## Documents

| Document | Covers | Status |
|---|---|---|
| [overview.md](overview.md) | Principles P-1…P-8, high-level architecture, component catalogue, component interaction, contract vocabulary, fit with the repository structure | provisional |
| [request_lifecycle.md](request_lifecycle.md) | Stage order, lifecycle sequence, replay vs online, data flow and the privacy boundary | order decided |
| [routing.md](routing.md) | Features → eligibility → decision → model selection | structure decided |
| [caching.md](caching.md) | Exact and semantic cache: key composition, validity, invalidation, stores | structure decided |
| [context_construction.md](context_construction.md) | Building and reducing context; overflow | reference decided, strategies open |
| [attempts.md](attempts.md) | Retries, failover, escalation; unsatisfactory-response detection | model decided, detectors open |
| [evaluation.md](evaluation.md) | Offline replay, counterfactual sources, baselines, metrics, judges | structure decided |
| [configuration.md](configuration.md) | Defaults, reference data, runtime, experiment, overrides, secrets | layers decided |
| [observability.md](observability.md) | Correlation IDs, spans, event types, dashboard derivation, full-dataset field coverage | approach decided |
| [providers.md](providers.md) | `ModelClient` port, adapters, error taxonomy, catalogue fields, other external ports | port decided |
| [deployment_and_data.md](deployment_and_data.md) | Local-development assumptions, future deployment view, future database extension points | local decided, future provisional |
| [repository_structure.md](repository_structure.md) | Where files go, import rules, promotion (Stage 2) | decided |
| [contracts.md](contracts.md) | **Stage 4.** Internal contracts: conventions (privacy classes, tri-state components, IDs, fingerprints, time, money, versioning), catalogue with producers and consumers, sample tolerance, reserved `traffic_source`, arrow coverage | conventions decided, fields provisional |
| [module_reference.md](module_reference.md) | **Stage 5.** Every module: responsibility, callers, imports (checked by a test), data in and out, config, kind, status; swap points | matches the code (tested) |
| [contracts_reference.md](contracts_reference.md) | **Generated** field reference for every contract (type, required, privacy class, description) and every enumeration | generated; a test fails if stale |

## Diagrams and the question each answers

| Diagram | Question | In |
|---|---|---|
| High-level architecture | What are the main parts, which layer owns each, and where are the external boundaries? | [overview §2](overview.md#2-high-level-architecture) |
| Component interaction | During one request, which component calls which, and what contract crosses each call? | [overview §4](overview.md#4-component-interaction) |
| Request lifecycle (sequence) | In what order do components act for one request, and where do hit/miss and the attempt loop branch? | [request_lifecycle §2](request_lifecycle.md#2-request-lifecycle-sequence) |
| Data flow | Where does data come from and go, and which stores may hold raw content? | [request_lifecycle §4](request_lifecycle.md#4-data-flow-and-privacy-boundary) |
| Routing decision flow | How do features become a chosen model, and where can routing stop without one? | [routing §2](routing.md#2-routing-decision-flow) |
| Caching decision flow | Which checks run, in which order, before a cached answer is served, and when is a new answer stored? | [caching §3](caching.md#3-caching-decision-flow) |
| Context construction flow | How do request components become one target's input, and what happens on overflow? | [context_construction §3](context_construction.md#3-context-construction-flow) |
| Escalation and failover flow | After each model call, what decides between return, retry, failover, escalation, or giving up? | [attempts §2](attempts.md#2-escalation-and-failover-flow) |
| Offline evaluation flow | How does an experiment config become comparable results against both baselines? | [evaluation §2](evaluation.md#2-offline-evaluation-flow) |
| Configuration flow | How are config layers merged, how do secrets travel, and how does config become components? | [configuration §2](configuration.md#2-configuration-flow) |
| Future deployment / containers | In a future online deployment, what are the units, what state do they share, and what code do they reuse? | [deployment_and_data §3](deployment_and_data.md#3-future-deployment-and-container-view) |
| Package dependencies (Stage 2) | Which package may import which? | [repository_structure §3.1](repository_structure.md#31-allowed-imports-inside-srcmetis_auto-decided) |

Added beyond the master prompt's list: **context construction** (its overflow branches are easy to get wrong in prose) and **configuration** (precedence and the separate secrets path). No expected view was dropped.

Every data arrow is labelled with a Stage 4 contract name or a call whose arguments are contracts. The audit, with its two documented non-contract flows and the configuration diagram deferred to Stage 6, is in [contracts.md §7](contracts.md#7-every-arrow-is-labelled-with-a-contract-exit-criterion).

## Decision records from this stage

[ADR-0010](../adr/0010-request-pipeline-shape.md) pipeline shape · [ADR-0011](../adr/0011-cache-key-and-lookup-design.md) cache key and lookup · [ADR-0012](../adr/0012-event-stream-as-measurement-record.md) event stream · [ADR-0013](../adr/0013-unified-attempt-model.md) attempt model · [ADR-0014](../adr/0014-counterfactual-answers-via-model-client.md) counterfactual answers · [ADR-0015](../adr/0015-keyed-content-fingerprints.md) keyed fingerprints.

Stage 4: [ADR-0017](../adr/0017-contract-modelling-with-pydantic.md) contract modelling with pydantic; [ADR-0015 amendment 1](../adr/0015-keyed-content-fingerprints.md#amendment-1-2026-10-17-stage-4-the-algorithm) fingerprint algorithm.

## Checking diagrams

All Mermaid blocks in `docs/architecture/` were parsed with Mermaid 11.4.1 on 2026-10-14, and again on 2026-10-17 after the Stage 4 label changes (see [progress.md](../project/progress.md)). Re-run the check after editing a diagram.
