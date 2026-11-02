# Pipeline B only: dry-run `combine` of R-B1 + R-B2 + R-B3 (sprint task I-1, B's part)

- **What:** a handoff for the team, **not** the final integration. It runs the real `analysis/levers.combine` with Pipeline B's three versions and with each alone, on the tune split. It picks no winner; the team picks winners per step with the decision rules (plan, "Decision rules"). Traces: plan I-1, Review Focus 1 (no double counting), QA-REPRO, [ADR-0031](../../../docs/adr/0031-full-data-lever-replay.md), [ADR-0036](../../../docs/adr/0036-replay-scope-split-and-baselines.md) (units).
- **Evidence class:** *simulation* (R-B1 measured potential, R-B2 hypothetical reconstruction, R-B3 cost simulation, quality not proven, interim eligibility).
- **Versions:** R-B1 `retrieval_result_cache.ttl_1d` (the TTL chosen on Day 2); R-B2 the conservative default (nothing visible, saves 0) and one stated scenario (chunks of the previous turn visible, pointer 8 tokens, no ledger); R-B3 the declared default `k` from `reports/routing/exp-route-011/summary.json`.
- **Rows:** every tune-period row goes through `combine` (R-B1 cache history); results are counted on `split_by_session == "tune"` rows.

## Units: what may be combined (`run.unit_cells`)

| Baseline | Combined steps | Not computed, and why |
|---|---|---|
| `as_logged` (recorded) | cache + context | routing: the routed cost is in price-file units |
| `premium_gpt_5_5`, `todays_models`, `best_single_cheap` (price-file) | context + routing | cache: R-B1 saves recorded per-call fees, and these baselines have no fee block |

A combined saving over all three steps is therefore **not computed in any single unit**.

Repriced saving against a baseline = baseline cost minus the pipeline's own cost (today's pricing of the model each row ends on, with the tokens it ends with), on one row set for every run: the rows routing can price. Those savings share the term (baseline − today's models), so they are not additive across runs. The sum rule is checked on the increment over today's models.

## Routing after context (design question for the `combine` owner, Pipeline A)

`combine` passes R-B3 the frame R-B2 returned. R-B2 lowers `block_token_cost` (recorded units) and adds `ctx_tokens_saved` / `input_tokens_after`, but leaves `a_bill_inputTokens` as logged. A routing version that reprices from `a_bill_inputTokens` therefore prices the **pre-context** tokens, and the context saving vanishes from the combined repriced figure. This dry run reports both:

- `combined.*`: `PostContextRouting` wraps R-B3 so it sees the input lowered by R-B2's net tokens saved, with R-B2's cached-token floor (`after_tokens`). This is the dry run's **stated assumption**.
- `combined_today.*`: `combine` as it is.

## Checks

- **Sum rule:** combined ≤ compatible standalone sum; equality is allowed when the steps touch different rows or cost blocks (R-B1 lowers only fees, R-B2 only token cost). Never forced strict.
- **Overlaps:** requests touched by two or three steps (`run.overlaps`).
- **R-B1 rows keep `served_from_cache` false** (`run.retrieval_rows_not_served`): a retrieval reuse is not an answer-cache hit, so context and routing still apply to it.

## Files

`run.py` (helpers), runner `scripts/run_pipeline_b_day3.py i1` (after `rb3`), summary `reports/pipelines/b-only-dry-run/summary.json`. Not a `LeverResult`: `LeverResult.step` is one of cache/context/routing, and a combined pipeline has none. Tests: `tests/unit/experiments/test_b_only_dry_run.py` (synthetic).

## Results, tune split (full data, `code_commit` 5a68fb6, 2026-11-02)

Rows through `combine`: every tune-period row (R-B1 cache history). Counted: `split_by_session == "tune"` rows (230,762; 209,331 LLM). R-B3 at its declared default k = 5, interim eligibility. Naive timestamps (Q-06). Handoff only: no winner.

**Recorded units, `as_logged`** (baseline 327.779 over LLM rows with a known cost; routing not computed in these units):

| Run | Fees saved | Token cost saved | Total | Share |
|---|---|---|---|---|
| R-B1 alone (1-day TTL) | 3.580 | 0 | 3.580 | 1.09% |
| R-B2 alone, conservative default | 0 | 0 | 0 | 0% |
| R-B2 alone, stated scenario (k ≤ 1, pointer 8) | 0 | 7.657 | 7.657 | 2.34% |
| combined, conservative default | 3.580 | 0 | 3.580 | 1.09% |
| combined, stated scenario | 3.580 | 7.657 | **11.237** | 3.43% |

Sum rule: combined = R-B1 + R-B2 exactly in both scenarios (**equal, allowed**): R-B1 lowers only fees and R-B2 only token cost, and a retrieval reuse keeps `served_from_cache` false, so R-B2 still applies to it (checked on every run).

**Price-file units** (88,971 rows routing can price, the same rows for every run; saving = baseline minus the pipeline's own cost; R-B1 not computed in these units):

| Run | vs `todays_models` | vs `premium_gpt_5_5` | vs `best_single_cheap` |
|---|---|---|---|
| R-B3 alone | 0.190 | 996.339 | −15.337 |
| R-B2 alone, stated scenario | 0.700 | 996.849 | −14.827 |
| combined (`PostContextRouting`), stated scenario | **0.888** | 997.037 | −14.639 |
| combined as `combine` is today, stated scenario | 0.190 | 996.339 | −15.337 |

Sum rule on the increment over today's models: conservative default 0.190 = 0 + 0.190 (equal); stated scenario **0.888 < 0.890** = 0.700 + 0.190 (holds; the 43 requests touched by both are routed on fewer tokens, so routing saves a little less on them). With `combine` as it is, the context saving disappears from the repriced figure (0.190 = routing alone): Q-B20.

**Overlaps** (stated scenario, scored LLM rows): cache 1,555, context 15,013, routing 3,692; cache & context 1,414, cache & routing 9, context & routing 43, all three 9. The conservative default touches no request through context.

The combined `as_logged` saving and the combined repriced saving are in different units and are **not** added. A saving over all three steps in one unit is not computed.
