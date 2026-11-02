# EXP-ROUTE-011: kNN router, nearest-profile policy (sprint task R-B3)

- **Hypothesis:** H-1 (part of the traffic can run on a cheaper model). Here the evidence for "can run" is only that requests with the nearest profiles already run on that model. Traces: FR-ROUTE-03 (comparable, swappable strategies), FR-ROUTE-05 (an unknown limit excludes a model), QA-REPRO; plan R-B3 and "Routing without quality labels"; Review Focus 2 (split) and 3 (cached-token convention); [ADR-0036](../../../docs/adr/0036-replay-scope-split-and-baselines.md) (scope, split, baselines, units), [ADR-0032](../../../docs/adr/0032-lever-result-and-manifest-format.md) (result format).
- **Evidence class:** *simulation*. **Cost simulation; quality not proven** (in every result's `assumptions`). No quality label exists: the routing decision rule (acceptable rate within 10 points of the incumbent) **cannot be passed** by this version.
- **Eligibility: interim.** `analysis/routing_base.py` (R-0, Parham) is on no branch (checked 2026-11-02). The hard constraints come from `eligibility_interim.py`, injected as `eligible_models`. Every result says "interim eligibility, not the shared routing base" and stays out of any final comparison until the switch-over (`docs/experiments/pipeline_b_interim_contracts_day3.md`, Day 3).
- **ID:** `exp-route-011`. `docs/experiments/routing_plan.md` reserves `exp-route-001` to `-008` and `-010` (and `config/defaults.toml` cites `exp-route-002` for rule-based routing), so this sprint version takes the next free ID after the plan's highest; `-009` is left to the plan.
- **Status:** code and tests done; full-data run on the tune split after the Day 3 commit (results below). The report period is not read.

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

## Repricing and units (ADR-0036)

- **Routed cost** (`run.routed_baselines`): a copy of the rows with each row's `bot_provider_model` set to the routed model and the input already effective (cached tokens added back for the **logged** model, the five-model convention), priced by `baselines_full.baseline_costs` and read as `todays_models`. Only public functions of `baselines_full` are used. Token counts are assumed model-independent, logged output length unchanged, the lookup fee unchanged.
- `candidate_costs` re-implements the same public pricing rule per row, only to **order** candidates and for intervals and slices; its sums are tested equal to `baseline_costs`. Switch-over: `baselines_full.repriced_row_costs` (on `main` since #22, 82e4c72; this branch has not merged `main`) can replace it.
- **Rows:** every baseline of a result is over the rows the router can price (incumbent priced, tokens known). The rest keep their model and are counted in the `routing` slice.
- **Savings:** `premium_gpt_5_5`, `todays_models`, `best_single_cheap`: baseline cost minus routed cost (price-file units, `token_cost` only, no `fees`). Against a baseline other than `todays_models` this includes the baseline's own difference from today's models; **the router's own effect is the `todays_models` result**. `best_single_cheap` can be negative: one cheap model everywhere ignores every constraint. `as_logged` (recorded units): **not computed**, `saving` empty, never 0.
- Unknown or unpriced is never 0.

## Files

| File | What |
|---|---|
| `version.py` | `KnnRouter` (`StepVersion`-shaped, `apply` and `apply_many` for a `k` grid from one search), `profile_matrix`, `Scaler`, `nearest`, `candidate_costs`, `effective_tokens` |
| `eligibility_interim.py` | INTERIM `interim_eligible_models` (candidate, enabled, not retiring, priced, known context window and output limit that fit, no attachment, no configured functions) |
| `run.py` | `component_folds`, `nested_cv`, `least_aggressive`, `routed_baselines`, `lever_results_json` (one `LeverResult` per `k` per baseline) |

Runner: `scripts/run_pipeline_b_day3.py rb3`. Results: `reports/levers/rb3.knn-router.k-<k>.tune.<baseline>.json`, summary `reports/routing/exp-route-011/summary.json`. Tests: `tests/unit/experiments/test_knn_router.py`, `test_knn_router_run.py` (synthetic). Overhead: **not measured** (L-1 script, see below); the fields stay `None`, never 0.

## Results, tune split (full data, `code_commit` 5a68fb6, 2026-11-02)

Rows: 230,762 `split_by_session == "tune"` rows inside the tune period, 209,331 of them LLM rows (naive timestamps, Q-06). **Interim eligibility; cost simulation; quality not proven.** Price-file units.

**Why most traffic is untouched:** 119,854 LLM rows (57.3%) run on a model with no price in the price file (`incumbent_unpriced`, never 0), 506 have unknown tokens and 1,226 belong to bots below `min_n` = 30. The router can price 88,971 rows; every baseline below is over those rows.

**Nested CV** (5 outer × 3 inner folds; outer fold sizes 62,360 / 52,806 / 30,940 / 32,122 / 31,103 LLM rows, uneven because families join sessions): every outer fold chose **k = 5** (inner moved share 1.7–4.5% at k = 5, 2.8–6.8% at 15, 4.9–10.3% at 50), as the criterion predicts. **Declared default: k = 5.**

| k | role | moved (of 209,331) | to `deepseek-v4-flash` / `gpt-4.1-nano` / `gpt-4o-mini` / `mimo-v2.5` | median support | saving vs `todays_models` (router's own effect) | out-of-fold moved, saving |
|---|---|---|---|---|---|---|
| 5 | **default** | 3,692 (1.76%) | 2,485 / 1,038 / 165 / 4 | 0.20 | 0.190 = **0.70% [0.54, 0.89]** | 3.00%, 0.201 |
| 15 | grid | 9,024 (4.31%) | 3,102 / 5,693 / 216 / 13 | 0.20 | 0.487 = 1.79% [1.52, 2.12] | 4.63%, 0.428 |
| 50 | grid | 14,959 (7.15%) | 3,268 / 11,278 / 359 / 54 | 0.04 | 0.967 = 3.55% [3.06, 4.04] | 7.50%, 0.851 |

Against the other baselines (k = 5; same rows): `premium_gpt_5_5` 97.36% [97.28, 97.42], almost all of it the premium model's own price, not the router; `best_single_cheap` **−131%** [−139, −125]: one cheap model everywhere would cost less than today's models even after routing (it ignores every constraint and quality). `as_logged`: not computed. Intervals are session-clustered (500 resamples).

**Concentration:** the largest bot (`bot-01`, 80,526 rows) runs on an unpriced model and is untouched; of the next bots, `bot-04` and `bot-05` move 21% and 28% of their requests (saving 2.3% and 1.1% of their today's-model cost), `bot-02` (32,295 rows) moves 0.9%. Per-bot table (top 20 by size, ranks only): `reports/routing/exp-route-011/summary.json`.

**Reading:** the larger `k` moves more requests because a single neighbour on a cheap model is enough (median support falls to 0.04 at k = 50: two of 50 neighbours). The saving ranking `compare` prints (k = 50 first) is the ranking the criterion refuses to use. Overhead: not measured. `scripts/measure_lever_overhead.py` reached `main` (#23) after this run; it builds only R-A1/R-A2 versions ("no known version" for `rb3.*`, dry run, nothing read) and samples report-period rows, which this session does not read. `summary.json`'s "script missing" was true when the run started. Patch for Pipeline A: Q-B24 in the Day 3 interim-contracts doc.
