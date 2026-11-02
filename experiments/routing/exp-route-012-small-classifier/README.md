# EXP-ROUTE-012: small classifier, threshold rule (sprint task R-C3)

- **Task:** final plan R-C3 (Pipeline C), "Routing without quality labels": C = a threshold classifier on the EDA's transparent rule features. **Traceability:** FR-ROUTE-01 (select a target per request not served from cache), FR-ROUTE-02 (record target, eligible candidates, policy name, reason), FR-ROUTE-03 (interchangeable policies; this is a rule-based and a classifier policy), FR-ROUTE-04 (router overhead: not measured yet, fields stay `None`), FR-ROUTE-05 (unverified capability = unsupported, through the routing base), FR-REQ-06 (only information available before generation), H-5 (cheap features route a meaningful share to cheaper models; quality loss unmeasurable here, EDA hypothesis table), X7 (routing benchmark, [experiment plan](../../../docs/full_eda/experiment_plan.md); this result is its no-label cost part), routing plan R1/R2 ([routing_plan.md](../../../docs/experiments/routing_plan.md)); Review Focus 3 (cached-token convention, through `routing_base`) and 5 (tenant concentration). The prompt also named **X7**: in the repo X7 is the context plan's overflow trim, not a routing ID, so it is not cited.
- **Hypothesis (H-5):** requests that are short, without retrieval, attachments or tools and with a small input can move to a cheaper eligible model; the rule finds how much of the `token_cost` block that would remove. **Not tested here: whether they keep quality.**
- **Evidence class:** *simulation*. **Cost simulation; quality not proven: no labels (P-1..P-3 not run).** `correctness_state` is `unmeasured`. The routing decision rule (acceptable rate within 10 points of the incumbent) **cannot be passed** by this version.
- **ID:** `exp-route-012`. `routing_plan.md` reserves `-001` to `-008` and `-010`; Pipeline B took `-011` (R-B3) and left `-009` to the plan. No other `exp-route-*` exists on `origin/main` or any remote branch (checked 2026-11-03).
- **Decision record:** ADR-0046, [draft](../../../docs/adr/0046-small-classifier-routing.md); routing base [ADR-0045](../../../docs/adr/0045-routing-base-eligibility-and-failover.md); pricing [ADR-0036](../../../docs/adr/0036-replay-scope-split-and-baselines.md), [ADR-0038](../../../docs/adr/0038-context-token-saving-conversion.md), [ADR-0041](../../../docs/adr/0041-replay-pricing-for-logged-models.md).

## Version (`version.py`, owner decisions 2026-11-03)

`SmallClassifier(mode, *, rules, candidates, cached_separately, ...)`, a `StepVersion` with step `"routing"`. Two modes in one version:

1. **`"rules"`** (the real-data run). A request is *simple* only if `u_n_chars <= max_u_chars`, `a_rag_n_queries == 0`, `u_att_n == 0` (unknown = not simple), `bot_n_functions == 0` and effective input `<= max_input_tokens` (cached tokens added back for the five models, `baselines_full.token_counts`). Unknown is never simple. No default threshold.
2. **`"logistic"`**: numpy logistic regression (L2, Newton steps; scikit-learn not used) on `FEATURES`, trained only from labels whose source is declared (`labels_source` `benchmark:<name>` for P-3 labels, `synthetic:<name>` in tests; `None` and anything else refuse to run). Never labels from logged answers, the logged model or cost. `nested_cv`: outer and inner folds grouped by session **and** duplicate family (`bot_id` + `u_h_norm`, as `replay_scope`); the inner folds choose the L2 strength by log loss; each outer fold is scored by a model fitted on its training part only; out-of-fold accuracy with a session-clustered bootstrap interval; fewer labelled rows than `min_n` = `insufficient`, no estimate. **Built and tested on synthetic labels only**; it has no real-data result.

**Features** (FR-REQ-06, both modes): user message length (`u_n_chars`) and language (`u_lang`, one-hot), `turn`, history size (`n_prior_msgs`, `prior_chars`), RAG presence (`a_rag_n_queries`: retrieval runs before the answer and does not depend on the model), attachments (`u_att_n`), configured functions (`bot_n_functions`), bot instruction size (`bot_ins_n_chars`), effective input tokens. `feature_matrix` refuses every other column. **Excluded** (answer-derived): `a_n_chars`, `a_is_json`, `a_finish_reason`, `a_tool_n_calls`, output tokens, cost. This is why the rule differs from the EDA's screen, which also tested `a_tool_n_calls == 0`, `a_input_n_items == 0` and "not JSON" on the answer (`scripts/full_eda_analyze.py`, claim `route.simple_rule_share`).

**Routing** (`apply`): eligibility and candidate cost come only from `analysis.routing_base` (`eligibility_frame`, `candidate_costs`; NaN = not eligible, never 0) with `rules = sprint.toml [routing]`. A simple request's target is the cheapest eligible candidate (ties: candidate order). It moves only if the target is another model and strictly cheaper than the incumbent (the logged model at list price); never upward; everything else stays on its incumbent; fees never change. Columns: `route_simple`, `route_target`, `route_target_cost`, `route_moved`, `routed_model`, `route_reason` (routing_base's first failing reason, `no_eligible_candidate`, `not_simple`, `incumbent_unpriced`, `no_cheaper_candidate`, `moved`), `route_n_eligible`.

**Reasoning models:** candidates whose catalogue row has the capability `hidden_reasoning_billed_as_output` have list-price costs that ignore their hidden reasoning (Q-44, A-66). **Primary** (`route.small_classifier.rules`): excluded; the version refuses them. **Secondary** (`route.small_classifier.rules.with_reasoning_models`): included, labelled "lower bound on candidate cost, hidden reasoning not counted". In `catalogue-metis-replay.toml` the capability is on **gpt-5-nano, deepseek-v4-flash and mimo-v2.5** (the owner's note named the first two; the rule follows the catalogue), so the primary candidates are **gpt-4.1-nano and gpt-4o-mini**.

## Pricing per baseline (owner decision 5; agent reading in ADR point 6)

In each baseline the incumbent is the baseline's model for the row, and a simple row moves only if its target is strictly cheaper in that baseline's units:

- `todays_models`: the logged model at list price (`baselines_full.repriced_row_costs`) vs the target at list price (`routing_base.candidate_costs`). These are exactly the rows the version moves: **the router's own effect**.
- `premium_gpt_5_5`, `best_single_cheap`: the premium or the best single cheap model at list price vs the target at list price.
- `as_logged` (recorded units): recorded `block_token_cost` vs the target's cost at its implied rates from `reports/full_eda/tables/implied_unit_rates.csv` (input, cached and output per 1M). A rate is needed only for a token part above 0; a needed rate that is missing makes the saving **unknown** (row out of both sides, `n_saving_unknown`), never 0. Rows not moved save exactly 0.

Tokens are assumed model-independent (tokenizers differ), logged output length unchanged. Repriced `baseline_cost` has no `fees` key (ADR-0036); `saving.fees` is 0 everywhere.

## Thresholds (frozen 2026-11-03, before any report-split run)

| Setting | Value | Source |
|---|---|---|
| `max_u_chars` | **200** | the EDA's documented rule feature (`scripts/full_eda_analyze.py`, claim `route.simple_rule_share`) |
| `max_input_tokens` | **16,000** | set by the agent on the **tune** split only: grid {500, 1,000, 2,000, 4,000, 8,000, 16,000, 32,000} (declared before running), criterion *least aggressive*: among settings whose `todays_models` saving share (primary) is within 1 point of the best, the one that moves the fewest requests |
| candidates | primary: gpt-4.1-nano, gpt-4o-mini; secondary: + gpt-5-nano, deepseek-v4-flash, mimo-v2.5 | `sprint.toml [routing]` and the catalogue capability |

Grid on the tune split (LLM rows, primary, `todays_models`): saving share 0.058 / 0.079 / 0.134 / 0.168 / 0.240 / **0.272** / 0.277, moved share 0.138 / 0.220 / 0.358 / 0.370 / 0.386 / **0.388** / 0.388. 16,000 is within 1 point of 32,000 and moves fewer. **Caveat:** the saving still rises at the top of the grid (long requests carry most cost), so the choice depends on the grid ceiling; the same criterion inside five session-grouped folds chose 32,000 / 16,000 / 8,000 / 16,000 / 8,000. `scripts/small_classifier_levers.py` `MAX_U_CHARS`, `MAX_INPUT_TOKENS` hold the same values.

## Results, tune split (free checks, 2026-11-03)

`reports/routing/exp-route-012/tune_checks.json`. 230,762 `split_by_session == "tune"` rows inside the tune period, 209,331 LLM rows (naive timestamps, Q-06). Cost simulation; quality not proven; recorded units for `as_logged`, price-file USD otherwise.

- **Simple:** 0.771 of LLM rows (0.699 of all rows). Not the EDA's 72.6% of billed requests (`route.simple_rule_share`): different rule (no answer-derived tests, a token cap, unknown = not simple) and denominator.
- **Moved (primary):** 81,122 LLM rows (0.388), all to **gpt-4.1-nano** (gpt-4o-mini is never the cheapest eligible). 80,110 simple rows stay because their incumbent is already cheaper at list price. Not moved by eligibility: attachments 2,676, unknown attachment count 1,262, functions 2,277, unknown tokens 506, only reasoning candidates eligible 11; incumbent unpriced 88.
- **Moved (secondary):** 160,360 (0.766): gpt-5-nano 137,911, mimo-v2.5 22,449.

| Baseline | primary saving (share) [95% session-clustered] | secondary (lower bound on candidate cost) |
|---|---|---|
| `todays_models` (router's own effect) | 61.25 of 225.44 USD = **0.272** [0.203, 0.343] | 69.09 = 0.306 [0.240, 0.375] |
| `as_logged` | 57.72 of 322.29 recorded = 0.179 [0.130, 0.234]; **25,816 rows unknown** (gpt-4.1-nano has no implied cached rate) | 57.21 of 327.78 = 0.175 [0.126, 0.229]; 0 unknown |
| `premium_gpt_5_5` | 1,685.14 of 4,466.99 USD = 0.377 [0.331, 0.427] | 0.380 |
| `best_single_cheap` (gpt-5-nano) | **0**: no primary candidate is cheaper than gpt-5-nano | 0.61 of 49.81 = 0.012 |

- `as_logged` moves 134,199 rows (primary), more than `todays_models`: at recorded rates gpt-4.1-nano is cheaper than many incumbents that are cheaper at list price. Its implied rates rest on **447 billed items** (gpt-5-nano 11, mimo-v2.5 10): thin.
- **Concentration (Review Focus 5):** top bot 0.378, top 5 bots 0.748, top tenant **0.764** of the `todays_models` saving; the largest tenant holds 0.456 of LLM requests, **above the 0.35 cap**: flagged (`tenant_rank:1.over_cap`). Traffic-weighted saving share (per-bot shares weighted by LLM requests) 0.128 vs 0.272 cost-weighted. Over 8,000 input tokens: 0.073.

## Comparison (same tune split; not the report split)

- **R-A3 (Pipeline A, per-bot reassignment):** not on `origin/main` (checked 2026-11-03); no comparison.
- **R-B3 (EXP-ROUTE-011, kNN, k = 5):** `todays_models` 0.70% [0.54, 0.89] over 88,971 priced rows. **Not directly comparable:** interim eligibility (unknown attachments = none), and the run predates the replay price table (ADR-0041), so 57% of its LLM rows were unpriced. A nearest-profile policy also cannot reach gpt-5-nano or mimo-v2.5 (almost no bot runs them).
- **EDA upper bound:** `route.sim_save.simple_rule` 0.142 of recorded cost for the EDA's rule group, `route.sim_save.all_billed_requests` 0.416 (target gemini-2.5-flash-lite at recorded rates, quality assumed). Different target, rule and denominator; an upper bound, not a like-for-like number.

## Assumptions

| Assumption | Kind |
|---|---|
| Tokens are model-independent; the logged output length holds on the target model | current, provisional |
| Hidden reasoning is not in list-price cost; the primary set avoids it, the secondary is a lower bound | current, decided (owner) |
| A short, retrieval-free, small request is answerable by the cheapest eligible model at equal quality | speculative (H-5; no labels) |
| Implied recorded-unit rates of thinly used models (gpt-4.1-nano 447 items) price `as_logged` well enough | current, provisional |
| `a_rag_n_queries` and the billed input are known before generation (retrieval and prompt assembly precede the call); multi-call input includes later calls | current, provisional |
| P-3 benchmark labels arrive with a declared source and train the logistic mode | future |

## Files

| File | What |
|---|---|
| `version.py` | `SmallClassifier`, `rule_simple`, `feature_matrix`, `fit_logistic`, `LogisticModel`, `component_folds`, `nested_cv`, `least_aggressive`, `candidate_sets`, `reasoning_models`, `implied_cost`, `baseline_frames`, `assumptions`, `lever_result` |
| [`scripts/small_classifier_levers.py`](../../../scripts/small_classifier_levers.py) | `--checks-only` (tune checks) and the writer (one `LeverResult` per version and baseline, `reports/levers/route.small_classifier.rules[.with_reasoning_models].<baseline>.json`) |

Tests: `tests/unit/experiments/test_exp_route_012_small_classifier.py` (synthetic). Overhead: not measured (L-1); `overhead_ms_*` stay `None`, never 0.
