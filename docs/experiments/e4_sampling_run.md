# E4: the shared sampling run (offline harness, fakes only)

Status: **provisional** (Stage E4, 2026-10-30). Code: `src/metis_auto/evaluation/sampling/`. Spec: [evaluation framework §5, §0.2, §0.7](evaluation_framework.md); rules: ADR-0003 (offline by default), ADR-0014 (counterfactual sources), ADR-0018 (live budget). **No sampling run has been made. No live call, no key, no budget decision.** Every value below is unset by default and is the owner's to supply in an experiment file; none of the numbers in the spec's §5 is configured anywhere.

## 1. What exists

| Piece | Behavior |
|---|---|
| Sampler (`plan_sample`) | Cells from `dimensions`; a per-cell floor and per-language quotas first, then the remaining budget proportionally (exact fractions, deterministic ties); rare cells pooled within the first dimension; selection by seeded hash. Floors and quotas are **never trimmed or topped up**: over the total → `over_budget_by`; a quota the population cannot meet → `unmet` with the achieved n. |
| Allocation vs weighting | Allocation is how many units are drawn per cell (may oversample minorities). Weights are stored apart: each unit carries `k/N` and `N/k` of its cell. Per-stratum comparisons use the sample as drawn; population totals (`population_total`) use the weights. `slice_counts` prints population, sample and weighted shares per slice. |
| Run plan (`plan_calls`) | Models × effort labels × selected units, the repeat subset repeated, in a seeded shuffled order. |
| Estimates (`estimate_run`) | `lower_bound_usd` (input only), `assumed_usd` (only with a documented output assumption; simulated), `ceiling_usd` (every call at `max_output_tokens`). Each says why it is missing. |
| Live guard (`check_live`, `execute`) | The run refuses to start, before any call, without a model list, `hard_cap_usd`, `max_output_tokens`, `order_seed`, known input sizes, and, for a `live` client, a `LiveApproval` (who, which run, USD cap; sample conversations need `sample_conversations_approved`). The effective cap is the lower of the two caps. `execute` has **no default** for `uses_sample_conversations`: the caller must state `True` or `False`, and anything else (including `None`) raises `TypeError` before any call. |
| Cap during a run | Before each call: charged so far + that call's cost at `max_output_tokens` must fit the cap. A call without reported usage is charged at that worst case. |
| Stop rules | Failure share and truncation share per model, and cost overrun, apply only when configured; each reports `unset`, `inactive_*` (and why) or `active`. |
| Records | Content-free `CallRecord`s: tokens (input, output, reasoning, cached, cache write), finish reason, truncated, latency (provider or measured), model version, retry count 0, cost from reported usage. Answer text lives only in the recorded store (the live-only recording decorator the caller wraps; the replay loader indexes only records made live, so a store of fake answers can never be replayed as recorded or read as measured). |
| Tables | `usage_records` (E2 `UsageRecord`s for the cost-model fit), `outcome_table` (E1; incomplete until quality is supplied), `comparison_table` (Persian first; quality, cost, latency, ttft, n, interval as separate columns; no combined score). |
| Provenance | `measured` only for live or recorded answers; fakes give `simulated`. Quality is `not_evaluated` until scores exist and carries whether they are validated. |

## 2. Config fields and units

```toml
[allocation]
dimensions     = ["language", ...]     # strata dimensions forming the cells
total          = <units to draw>       # a budget decision, not a precision claim
seed           = "<string>"
floor_per_cell = <units>               # optional
pool_below_n   = <population>          # optional: pool cells smaller than this
quotas         = { en = <units>, mixed = <units> }   # optional, per language value

[run]
models = ["<model_id>", ...]
efforts = { "<model_id>" = ["<effort label>", ...] }  # null label = provider default
repeat_units = <n>   repeat_count = <k>               # both or neither
hard_cap_usd = <USD>         max_output_tokens = <tokens>      order_seed = "<string>"
output_tokens_assumption = { "<model_id>" = <billed output tokens per call> }
assumption_note = "<why; required with the assumption>"
max_failure_share = <0..1>   max_truncation_share = <0..1>   stop_rule_min_calls = <n>
overrun_factor = <ratio>     overrun_check_at_progress = <fraction in (0, 1]>

LiveApproval: approved_by, run_id, cap_usd, sample_conversations_approved   # supplied at run time
```

An unset allocation value gives `not_evaluated` with a reason (`dimensions_unset`, `total_unset`, `seed_unset`, `quota_needs_language_dimension`). An unset run value refuses the run (`models_unset`, `order_seed_unset`, `hard_cap_unset`, `max_output_tokens_unset`) or switches an optional rule off with a stated status.

## 3. What this does not do

- It never builds a live client, reads `.env`, or calls a provider. Wiring a live client and approving a run are separate, owner-led steps.
- **Time to first token** and the **effort setting** are not in the `ModelClient` port. TTFT is recorded as not reported; effort is carried as a label and applied by the caller's `client_for(model, effort)` factory. Supporting them in the live adapter (streaming, model options) is future work and was not changed.
- Quality scores come from E5. Until then the comparison and the outcome table show quality as not evaluated.
- Nothing has been fitted on real data: the tests use a fake client that reports constant usage, so they check mechanics, not estimates.
- `scripts/sampling_plan.py` prints the per-slice plan before any run. On the 100-session sample the minority slices are small (English 23, mixed 19 units), so quotas beyond those sizes are `unmet`, not met.
