# ADR-0005: Current-phase scope — offline foundation, in-process API, Action 3 deferred

- Status: **decided** (Q-17 answered 2026-10-14). The external wire format is **provisional** (Q-15).
- Date: 2026-10-14
- Relates to: [requirements.md](../project/requirements.md) §5 (non-goals), A-11, ADR-0003

## Context
The brief describes:
- a highly available gateway with routing, semantic caching, cascade, and failover (Actions 1–2);
- an optional pricing engine and user-facing dashboard (Action 3).

This engagement has no production access, no provider keys, no budget, and only a 100-session sample. The full dataset arrives later. The master prompt asks for a foundation (architecture, contracts, skeletons, experiment scaffolding, a few real utilities), not the full application. A scope line is needed so later stages don't drift into building a server or UI that no current experiment needs.

## Decision
1. **The current phase is an offline foundation.** Its first consumer is the offline replay harness (A-11). The online gateway is a later consumer of the *same* policies (FR-ROUTE-07).
2. **The entry point is an in-process Python API** (FR-API-01). A network gateway (HTTP, auth, multi-tenancy) is out of scope (NG-03). When it comes, it is a **separate external-API adapter layer** over internal contracts. Its provisional default wire format is OpenAI-compatible chat-completions style. Compatibility with production Metis clients is unknown (Q-15, open for the Metis team).
3. **Brief Action 3 is deferred:**
   - The pricing engine (FR-FIN-01) and the dashboard UI (FR-FIN-02) are not built.
   - Their **data enablers are in scope**: the event model and the derivable aggregates (FR-OBS-05), plus cost accounting (FR-ACCT).
   - The event design must capture everything a dashboard would need (tokens, cost, savings, latency, routing decisions), so a dashboard can be added **without redesign**.
4. Mechanisms are in scope **as design plus pluggable interfaces**. Implementation in this engagement is limited to:
   - the walking skeleton with fakes (Stage 5);
   - token and cost accounting (Stage 7);
   - the experiment runner and exact-cache baseline (Stage 8).

   Semantic cache, context reduction, cascade, and learned routing are designed and planned as experiments, not implemented.
5. The full non-goal list lives in requirements.md §5, and is changed only by a new decision record.

## Alternatives considered
- **Build an HTTP gateway now.** Rejected. There is no live provider, no client, and no requirement that an in-process API can't meet. It would also force an API-compatibility choice early (Q-15).
- **Include Action 3 now.** Rejected. The pricing engine needs verified prices and real volumes. A UI adds no evidence and would be built on estimated numbers.
- **Drop Action 3 entirely.** Rejected. Its data needs shape the event model now, and leaving them out would make it expensive to add later.

## Consequences
- Stage 2 gives the gateway and dashboard at most a placeholder home; they get no code.
- Stage 3 still documents the future deployment and container view, as an extension point.
- The event schema (Stage 4) must be rich enough for the deferred dashboard.
- Adding Action 3 later needs a new decision record. It should not need an event-model redesign; if it does, that is a defect in FR-OBS-05.
