# EXP-ROUTE-011: kNN router, nearest-profile policy (sprint task R-B3)

- **Hypothesis:** H-1 (part of the traffic can run on a cheaper model). Here the evidence for "can run" is only that requests with the nearest profiles already run on that model. Traces: FR-ROUTE-03 (comparable, swappable strategies), FR-ROUTE-05 (an unknown limit excludes a model), QA-REPRO; plan R-B3 and "Routing without quality labels"; Review Focus 2 (split) and 3 (cached-token convention); [ADR-0048](../../../docs/adr/0048-knn-router-nearest-profile-routing.md) (this version's decisions), [ADR-0036](../../../docs/adr/0036-replay-scope-split-and-baselines.md) (scope, split, baselines, units), [ADR-0032](../../../docs/adr/0032-lever-result-and-manifest-format.md) (result format).
- **Evidence class:** *simulation*. **Cost simulation; quality not proven** (in every result's `assumptions`). No quality label exists: the routing decision rule (acceptable rate within 10 points of the incumbent) **cannot be passed** by this version.
- **Eligibility:** the shared routing base (R-0, `analysis.routing_base.eligible_models`, ADR-0045), injected as `eligible_models` with `sprint.toml [routing]` as rules; `candidates_jev` is dropped and the constructor's candidates are used, as R-A3. The interim `eligibility_interim.py` is deleted (2026-11-03).
- **ID:** `exp-route-011`. `docs/experiments/routing_plan.md` reserves `exp-route-001` to `-008` and `-010` (and `config/defaults.toml` cites `exp-route-002` for rule-based routing), so this sprint version takes the next free ID after the plan's highest; `-009` is left to the plan.
- **Status (2026-11-03):** re-run on the logged-model prices (ADR-0041) with per-baseline accounting (ADR-0046 points 4 to 6, owner decision for Pipeline B); `k` = 5 frozen on the tune split; one report-split run (owner approval). Results below; `code_commit` 9f05b25.

## Frozen version (2026-11-03, written before the report-split run)

Chosen on the tune split by the predeclared least-aggressive criterion in session/family-grouped nested CV (5 outer x 3 inner folds, primary candidate set): **every outer fold chose `k` = 5**, so **`k` = 5 is frozen** (`reports/routing/exp-route-011/summary.json`, `frozen_k`). Nothing is changed after seeing report numbers.

- Candidates: primary `gpt-4.1-nano`, `gpt-4o-mini` (the `[routing] candidates` without those the catalogue marks `hidden_reasoning_billed_as_output`: `deepseek-v4-flash`, `gpt-5-nano`, `mimo-v2.5`; ADR-0046 point 4); secondary `with_reasoning_models` keeps all five ("lower bound on candidate cost, hidden reasoning not counted").
- Eligibility: `analysis.routing_base.eligible_models` (ADR-0045), rules `sprint.toml [routing]`. Accounting: each baseline's model is the incumbent, "cheaper" in that baseline's units, `as_logged` at implied recorded rates (ADR-0046 points 5 and 6, owner decision for Pipeline B 2026-11-03).
- **Report run** (owner approval 2026-11-03, once, like R-A3 and R-C3): `python scripts/run_pipeline_b_day3.py rb3-report --k 5`, fitted on tune rows (split and period), applied to the report split. Results `reports/levers/rb3.knn-router[.with_reasoning_models].k-5.report.<baseline>.json`, summary `reports/routing/exp-route-011/report.json`.

## Decision (declared before running)

For one request (`version.py`, `KnnRouter.apply`):

1. **Out of scope, keep the incumbent:** unknown tokens (`unknown_tokens`); the logged model has no price (`incumbent_unpriced`, so "cheaper" cannot be checked); the request's bot has fewer than `min_n` fitting rows (`insufficient_bot`; `sprint.toml [sufficiency] min_n`, through `ReplayContext.min_n`; a bot with no fitting row is a cold start).
2. Take the `k` nearest **fitting** profiles. A row in the request's own session or duplicate family (`(bot_id, u_h_norm)`, as in `replay_scope`) is never a neighbour. Fewer than `k` left: `too_few_neighbours`, keep the incumbent.
3. Collect the logged models of the `k` neighbours. Keep those in `sprint.toml [routing] candidates` (plus `candidates_jev`, empty today) that `eligible_models(row, catalogue, prices, rules)` allows. None: `no_eligible_candidate`.
4. Choose the cheapest of them on this request's tokens (`candidate_costs`, the `baselines_full` pricing rule). Move only if **strictly** cheaper than the incumbent (`moved`); otherwise `no_cheaper_candidate`. Never upward.
5. **Neighbours may come from any bot** (`CROSS_BOT = True`, tested): within one bot every request ran the bot's one model, so same-bot neighbours can only return the incumbent.

`route_support` is the share of the `k` neighbours that ran the chosen model.

**Consequence of rule 3 (data fact, tune split LLM rows):** the candidates were logged on `gpt-4o-mini` 62,821, `deepseek-v4-flash` 23,915, `gpt-4.1-nano` 558, `mimo-v2.5` 9 and `gpt-5-nano` 3 rows. A nearest-profile policy can only choose a model its neighbours ran, so the two cheapest candidates are almost never reachable (`mimo-v2.5`: 4 moves at k = 5; `gpt-5-nano`: none).

## Profile features (known before the model is chosen)

Checked against `docs/full_eda/data_dictionary.md` and `analysis/requests_table.py`. Numbers are `log1p` of the logged value.

| Feature | Column | Why |
|---|---|---|
| prior messages, prior characters | `n_prior_msgs`, `prior_chars` | logged history before the answer (reduced form, A-17) |
| retrieved chunks, chunk characters | `a_rag_n_chunks`, `a_rag_chunk_chars` | retrieval runs before generation and does not depend on the model; logged on the AI message (whether it is the final supplied context is unresolved); missing chars on a row without chunks = 0 |
| attachments | `u_att_n` | user side |
| user message length | `u_n_chars` | user side |
| user language | `u_lang` one-hot (`fa`, `fa_en_mixed`, `short_uncertain`, `arabic_script_other`, `en`, `structured`, `other`, missing) | user side |

**Excluded:** `a_tool_n_calls` (tool calls the *answer* made), `a_is_json` (the answer is JSON), `a_finish_reason`, output tokens, answer text, billed cost (all answer-derived); future traffic; bot configuration columns (`bot_updated_at`, `bot_n_functions`, …), which are one snapshot, not the state at request time. `bot_n_functions` is used only by the interim **eligibility**, and only in the conservative direction (a bot with functions gets no candidate, because no tool capability is verified).

## Fitting

- **Rows:** `split_by_session == "tune"` inside the tune period, LLM rows (ADR-0036). The same rows are queried; rule 2 keeps a request's own session and family out of its neighbours.
- **Scaling** (`Scaler.fit`, training rows only): missing numbers take the training median; then mean 0 and standard deviation 1 per column (a constant column keeps scale 1). Distance: Euclidean on the scaled profile, float32 (speed on ~200k rows; near-ties within float32 rounding are ordered by that rounding, deterministically).
- **Ties:** lower training position first (training rows sorted by index). Tested on duplicate profiles in either order.
- **Grid:** `k` in {5, 15, 50}, all reported.
- **Criterion (declared, `run.CRITERION`):** *least aggressive*: the `k` with the lowest share of requests moved in the inner folds (ties: smaller `k`). Saving is never the criterion: without quality labels it would always pick the most aggressive point. Because the candidate set of a smaller `k` is a subset of a larger one's, the moved share cannot fall as `k` grows, so this criterion is expected to pick the smallest grid point; the nested CV checks it on the data.
- **Nested CV** (`run.nested_cv`): 5 outer × 3 inner folds inside the tune split. A fold is a set of components: sessions joined by a shared duplicate family never span two folds, so no fold shares a session or a family with another (tested). Each fit, scaling included, uses only the rows outside the fold it scores. The default `k` is the one most outer folds choose; outer-fold decisions are reported as out-of-fold figures beside the results.
- **Labels:** `label_source` is `None`. Any other source is refused ("supervised use blocked"): no benchmark labels with provenance exist on any branch (P-2/P-3, checked 2026-11-02), golden-v2 labels are provisional rule labels, and the logged or cheapest model is never used as a label.

## Repricing and units (ADR-0036, ADR-0046 points 4 to 6)

- **Per-baseline incumbent** (`version.baseline_frames`, R-A3's method; owner decision for Pipeline B, 2026-11-03, Q-B21): `apply` is the `todays_models` decision and records each request's target (the cheapest eligible candidate its neighbours ran). In each baseline the incumbent is that baseline's model (logged model for `todays_models` and `as_logged`, the premium model, the best single cheap model); a request moves only if the target is another model and strictly cheaper in that baseline's units. So each saving is the router's own effect and is >= 0 row by row. `todays_models` moves exactly the rows `apply` moves (tested, and equal in every result file).
- **`as_logged`:** recorded token cost against the target at its implied recorded rates (`reports/full_eda/tables/implied_unit_rates.csv`, the ADR-0038 pattern); a needed rate that is missing makes the request's saving unknown (out of both sides, `n_saving_unknown`), never 0; fees never change. Its manifest's price version is `full-eda-implied-unit-rates`, as R-A3's and R-C3's.
- **Repriced baselines:** price-file units, `token_cost` only, no `fees` key; every slice is in the result's own units.
- **Candidates:** the primary result leaves out the candidates the catalogue marks `hidden_reasoning_billed_as_output` (ADR-0046 point 4); `with_reasoning_models` keeps them, labelled "lower bound on candidate cost, hidden reasoning not counted".
- **Rows:** every LLM row of the scored split whose baseline cost is known; rows the router does not touch save exactly 0. Unknown or unpriced is never 0. `candidate_costs` (`baselines_full.model_row_costs`) orders candidates.

## Files

| File | What |
|---|---|
| `version.py` | `KnnRouter` (`StepVersion`-shaped, `apply` and `apply_many` for a `k` grid from one search), `profile_matrix`, `Scaler`, `nearest`, `candidate_costs`, `effective_tokens` |
| `run.py` (per baseline) | `baseline_saving`, `lever_results_json` (one result per baseline from `version.baseline_frames`; primary and `with_reasoning_models` IDs; tune or report split) |
| `run.py` | `component_folds`, `nested_cv`, `least_aggressive`, `routed_baselines`, `lever_results_json` (one `LeverResult` per `k` per baseline) |

Runner: `scripts/run_pipeline_b_day3.py rb3` (tune) and `rb3-report --k 5` (report, once). Results: `reports/levers/rb3.knn-router[.with_reasoning_models].k-<k>.<split>.<baseline>.json`, summaries `reports/routing/exp-route-011/summary.json` and `report.json`. Tests: `tests/unit/experiments/test_knn_router.py`, `test_knn_router_run.py`, `test_knn_router_baselines.py` (synthetic). Overhead: `scripts/measure_pipeline_b_overhead.py` (ADR-XXXX (pipeline-b-lever-overhead)): k = 5 p50 375 ms, p95 422 ms on one-row frames (tune sample, n 987), **above the 100 ms p95 target** (Q-14); most of it is training-side indexes rebuilt per call in `apply` (follow-up: build them at fit time).

## Results (full data, `code_commit` 9f05b25, logged-model prices, 2026-11-03)

**Cost simulation; quality not proven.** Each baseline in its own units. Tune: 230,762 `split_by_session == "tune"` rows inside the tune period, 209,331 LLM. Report: the report split, 73,063 rows, 20,750 LLM (the same scope as R-A3's report results). Intervals are session-clustered.

Priced coverage: with the logged-model prices (ADR-0041) only **186 tune LLM rows (0.1%)** keep an unpriced incumbent (was 119,854, 57.3%), 506 have unknown tokens and 2,043 belong to bots below `min_n`. Report: 37 unpriced (0.2%), 6 unknown tokens.

**Nested CV** (primary candidates): every outer fold chose **k = 5** (inner moved share 4.2–7.4% at k = 5, 6.7–11.4% at 15, 10.7–17.0% at 50). Out-of-fold at k = 5: 5.67% moved, `todays_models` saving 16.7%.

Primary candidates (`gpt-4.1-nano`, `gpt-4o-mini`), tune split:

| k | role | moved (of 209,331) | to `gpt-4.1-nano` / `gpt-4o-mini` | `todays_models` | `as_logged` | `premium_gpt_5_5` | `best_single_cheap` |
|---|---|---|---|---|---|---|---|
| 5 | **frozen** | 9,513 (4.54%) | 1,198 / 8,315 | **16.74% [14.13, 19.74]** | 12.05% [10.16, 14.45] | 45.91% [41.60, 49.98] | 0.00% |
| 15 | grid | 18,321 (8.75%) | 6,381 / 11,940 | 27.01% [22.23, 32.88] | 19.27% [15.87, 23.03] | 61.25% [57.45, 65.01] | 0.00% |
| 50 | grid | 27,720 (13.24%) | 13,003 / 14,717 | 36.05% [27.98, 43.52] | 25.97% [20.82, 32.02] | 69.61% [67.06, 72.30] | 0.00% |

**Report split, k = 5 (one run):**

| result | `todays_models` | `as_logged` | `premium_gpt_5_5` | `best_single_cheap` | moved (of 20,750) |
|---|---|---|---|---|---|
| primary | **2.25% [1.90, 2.74]** | 2.46% [2.18, 2.86] (14 unknown) | 3.34% [2.86, 3.88] | 0.00% | 2,920 (14.07%) |
| `with_reasoning_models` | 2.40% [2.00, 2.97] | 2.70% [2.34, 3.21] (14 unknown) | 3.51% [3.03, 4.06] | 0.00% | 3,039 (14.65%) |

Tune `with_reasoning_models` at k = 5: `todays_models` 17.48% [14.91, 20.49], 12,870 moved (4,446 to `deepseek-v4-flash`, 25 to `mimo-v2.5`).

**Reading:** `best_single_cheap` saves 0: its model (`gpt-5-nano`, the cheapest callable) is cheaper than every candidate, so no request moves there (the old −131% was the gap between baselines, not the router). `premium_gpt_5_5` moves more rows than `todays_models` because the premium model is dearer than many logged models. The tune saving is large and the report saving small: on tune, a few expensive logged models dominate the moved rows; on the report split 2,131 of 20,750 LLM rows belong to bots below `min_n` in the tune fit and 14,011 have no eligible candidate. The largest bot (`bot-01`, 80,526 tune rows) is priced now but moves nothing. Compared on the report split with R-A3 per-bot reassignment (`todays_models` 6.28% [5.03, 7.49]), R-B3 is lower outside the interval: it does **not** pass the plan's "beat per-bot reassignment outside the CI" rule. No winner is picked here (I-1/I-2).

## Superseded results (2026-11-02, `code_commit` 5a68fb6)

Interim eligibility, the `s75-g55` price file (57.3% of tune LLM rows unpriced) and the old "baseline minus routed cost" definition: k = 5 moved 3,692 (1.76%), `todays_models` 0.70% [0.54, 0.89]; `premium_gpt_5_5` 97.36% and `best_single_cheap` −131% (both mostly the gap between baselines); `as_logged` not computed. Replaced by the results above.
