# ADR-0010: Request pipeline shape — synchronous, in-process, fixed stage order, measure in application and decide in domain

- Status: **decided** (stage order and the measure/decide split). Synchronous execution and the stateless-conversation assumption are **provisional**.
- Date: 2026-10-14
- Relates to: FR-API-01, FR-ROUTE-07, FR-XCACHE-02, QA-LAT, QA-TEST, ADR-0005, ADR-0009
- Detail: [request_lifecycle.md](../architecture/request_lifecycle.md), [overview.md §1](../architecture/overview.md#1-architectural-principles)

## Context
Stage 3 has to fix how one request is processed, so that the replay harness now and a gateway later run the same code (FR-ROUTE-07). Three choices interact:
- the order of routing and the cache lookup, because the conservative cache key includes the target model's group (FR-XCACHE-02);
- where port calls (tokenizers, embedders, model-based features) may happen, given that `domain` must stay pure and replayable;
- synchronous or asynchronous execution.

## Decision
1. **Fixed stage order:** receive → measure → features → route → cache lookup → context build → attempt loop → store → respond. The only loops are one re-route on context overflow, and the attempt loop ([ADR-0013](0013-unified-attempt-model.md)).
2. **Routing before the cache lookup**, so the serving key can include the target's equivalence group.
3. **Measure in `application`, decide in `domain`** (principle P-1). Every port call is a measurement taken by the application layer and passed to domain as data. A model-based router or a runtime judge is a measurement followed by a pure decision.
4. **Synchronous, in-process** execution, with timeouts passed to adapters and a request deadline checked by the attempt policy (provisional).
5. **Stateless about conversations:** the caller supplies the history with each request (provisional, P-8).
6. **Expected failures return a `FinalResponse` with an error status**; exceptions mean programming or configuration errors.

## Alternatives considered
- **Cache lookup before routing.** This saves router overhead on hits, but then the key can't contain the target, so an answer from a cheap model could be served where a strong model would have been chosen. Rejected as the default. It stays a possible measured variant for keys that exclude the target. Revisit if an expensive router (e.g. LLM-based) becomes a candidate.
- **Domain policies calling ports directly** (e.g. a router holding an `Embedder`). This is more natural for some strategies, but it makes policies I/O-bound and non-deterministic, and hides their overhead from the measurement record. Rejected.
- **Async (`asyncio`) from the start.** An online gateway benefits from async I/O. But nothing current needs concurrency: replay can run sessions in separate processes, and a gateway can run synchronous handlers in a thread pool. Async would also affect every port and adapter before any gateway exists. Rejected for now. Because domain is pure (point 3), a later switch to async touches only `application`, the I/O ports, and `adapters`.
- **A configurable stage order** (a pipeline of plug-in stages). This is flexible, but it makes the overhead budget, event semantics, and correctness of the cache key depend on configuration. Rejected; the order is code, and the strategies inside each stage are configuration.
- **A stateful pipeline that stores conversation history.** This would duplicate the caller's state and add a store that no current requirement needs. Rejected for now.

## Consequences
- A routing decision is computed even for requests later served from cache. Its overhead is counted (FR-ROUTE-04).
- Proposal S3-2 (domain imports only `contracts`) follows from point 3; it awaits approval (Q-19).
- The Stage 5 skeleton has one orchestrator class with one method per stage, and domain functions that take and return contracts.
- If the gateway needs async or server-side history, this ADR is amended.
