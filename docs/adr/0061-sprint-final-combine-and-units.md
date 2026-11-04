# ADR-0061: The final combined run adds each step's marginal effect in its own units, prices routing on post-context tokens in a wrapper, and keeps `combine` unchanged

- Status: **provisional** (sprint tasks I-1 and I-2, 2026-11-03/04). The wrapper-versus-`combine` question was put to the owner as a Stage 4 decision; the default taken here is the wrapper.
- Date: 2026-11-03
- Relates to: [ADR-0031](0031-full-data-lever-replay.md) (`combine`, simulations), [ADR-0032](0032-lever-result-and-manifest-format.md) (result format), [ADR-0036](0036-replay-scope-split-and-baselines.md) (recorded versus repriced units), [ADR-0037](0037-retrieval-result-cache-accounting.md) (retrieval cache saves fees only), [ADR-0046](0046-small-classifier-routing.md) point 6 (incumbent per baseline), [ADR-0050](0050-results-dashboard-display-rules.md) (no combined number across steps); plan I-1, I-2, Review Focus 1; QA-REPRO, QA-PRIV.
- Code: `experiments/pipelines/sprint-final/run.py`, `experiments/pipelines/sprint-final.toml`, `scripts/run_sprint_final.py`, `src/metis_auto/analysis/lever_enrich.py`.

## Context
Three pipelines (A, B, C), Parham's routing-only run and the provisional winners must be compared on one population. `levers.combine` applies one cache, one context and one routing version in that order, but (1) recorded cost (`as_logged`, with a fee block) and price-file cost (three baselines, token cost only) must never be added (ADR-0036), (2) a retrieval cache saves recorded fees, which price-file baselines do not price (ADR-0037 item 7), and (3) `combine` hands routing the frame context returned, whose logged input tokens are unchanged, so routing prices the pre-context tokens and the combined saving is overstated by the rows both steps touch (B's dry run: Q-B20). A combined pipeline also has no single `step`, so it is not a `LeverResult`.

## Decision
1. **One population:** the report split (73,063 requests), read once with settings frozen on the tune split; the run refuses any other scored count. The history rows (tune and report period) are the cache history.
2. **Marginal parts in sequence.** Each step's combined part is its own effect in the order cache, context, routing, in one baseline's units, so the parts add up to the combined total. The standalone part is the step alone on the same frame. The sum rule is combined ≤ the compatible standalone sum; equality is allowed when steps touch different rows or blocks. A violation stops the run.
3. **Units.** A step with no figure in a baseline's units is "not computed", never 0 (a retrieval cache or the session memo: `as_logged` only). Recorded and price-file figures are never added; the summary says so.
4. **Routing after context is a wrapper in the experiment folder** (`PostContextRouting`): routing sees the logged input lowered by the context version's net saved tokens, and its part is priced on that frame. `levers.combine` (Pipeline A's file) is **not changed**; if the owner moves the fix into `combine`, the wrapper is deleted and the numbers do not change.
5. **Answer-cache rows get nothing further:** `combine` skips context and routing on rows served from an answer cache; the run checks it. A retrieval reuse is not an answer-cache hit and keeps `served_from_cache` false (checked).
6. **Output:** `reports/pipelines/sprint-final/summary.json`, aggregates only, with the winners labelled "provisional: cost only, pending quality".
7. **Missing slices and intervals** of single results are filled by `analysis/lever_enrich.py` from the same before/after frames a version's own result is built from, only in the units of that result; a family it cannot compute is stated in `assumptions`, never left silently out.

## Consequences
- The combined figures are simulations on logged requests; quality is not measured. Combined repriced figures cover context and routing only for retrieval-cache pipelines.
- A `ChainedContext` is not needed for the provisional winners (one context winner); two context versions in one pipeline would need it.
- Guarding tests: `tests/unit/experiments/test_sprint_final_engine.py` (`test_unit_cells_follow_the_cache_kind`, `test_parts_are_not_added_across_units`, `test_sum_rule_equal_strict_and_violation`, `test_post_context_routing_sees_the_lowered_input`, `test_rows_served_from_an_answer_cache_get_no_context_or_routing`, `test_the_run_needs_exactly_the_expected_population`, `test_run_pipeline_reports_alone_combined_and_the_sum_rule`), `tests/unit/analysis/test_lever_enrich.py`.
