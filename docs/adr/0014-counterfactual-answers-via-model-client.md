# ADR-0014: Counterfactual answers come through the `ModelClient` port, and every run declares its source

- Status: **decided**. Which source each Stage 8 experiment uses is decided in its plan.
- Date: 2026-10-14
- Relates to: FR-EVAL-01, FR-EVAL-04, FR-REQ-06, ADR-0002, ADR-0003, context §8
- Detail: [evaluation.md §4](../architecture/evaluation.md#4-counterfactual-sources-and-their-limits)

## Context
The data only contains the answer from the model that was actually used. Evaluating any other routing, cache, or context choice needs answers that the data doesn't have: from new calls, recorded responses, mocks, or proxy metrics (context §8). The design must make the source visible in results, and must not need a separate simulation path.

## Decision
1. Answers for replayed requests come through the same `ModelClient` port the online pipeline uses. The source is chosen by **which adapter wiring injects**: `fake`, `logged_match`, `recorded`, `live` (with a recording decorator), or `proxy` (no answers).
2. Every run declares its source in the manifest and in every result.
3. Every run reports **coverage**: the fraction of cases for which the source produced an answer. Quality metrics cover only answered cases, and the selection bias is stated.
4. The **as-logged baseline** is computed directly from replay cases; it needs no pipeline run. The **premium baseline** is a `fixed_model` pipeline run with the same source rules.
5. Replay uses the **logged history**. The resulting divergence from what a candidate would really have seen is stated in every manifest.

## Alternatives considered
- **A separate simulator** that estimates outcomes without the pipeline. It is quick to build, but it measures a different code path from the one that would ship. Rejected (P-2).
- **Always call live models.** This gives the best evidence, but there is no budget, keys, or privacy review yet (ADR-0003). It stays one option among the sources.
- **Simulate multi-turn divergence** by feeding the candidate's own answers into later turns. This needs live or recorded answers for every turn, and it changes the user's side of the conversation, which can't be simulated faithfully. Deferred. The limitation is documented instead.

## Consequences
- The replay client needs a lookup keyed by case fingerprint × model × composition fingerprint (Stage 4/8).
- Results must carry a `counterfactual_source` and a coverage field (Stage 4 `EvaluationResult`).
- The first runs (Stage 8) use `fake` and `logged_match`. Quality claims wait for `recorded` or `live`.
