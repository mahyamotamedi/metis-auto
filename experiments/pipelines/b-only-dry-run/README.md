# Pipeline B only: dry-run `combine` of R-B1 + R-B2 + R-B3 (sprint task I-1, B's part)

- **What:** a handoff for the team, **not** the final integration. It runs the real `analysis/levers.combine` with Pipeline B's three versions and with each alone, on the tune split. It picks no winner; the team picks winners per step with the decision rules (plan, "Decision rules"). Traces: plan I-1, Review Focus 1 (no double counting), QA-REPRO, [ADR-0031](../../../docs/adr/0031-full-data-lever-replay.md), [ADR-0036](../../../docs/adr/0036-replay-scope-split-and-baselines.md) (units).
- **Evidence class:** *simulation* (R-B1 measured potential, R-B2 hypothetical reconstruction, R-B3 cost simulation, quality not proven).
- **Versions:** R-B1 `retrieval_result_cache.ttl_1d` (frozen stated default); R-B2 the conservative default (`k` = 0, nothing visible, saves 0) and the stated scenario (`k` <= 1, pointer 8 tokens, no ledger); R-B3 `route.knn.k5` (frozen `k`, primary candidates, shared routing base ADR-0045, per-baseline accounting ADR-0046 points 4 to 6).
- **Rows:** every tune-period row goes through `combine` (R-B1 cache history); results are counted on `split_by_session == "tune"` rows.

## Units: what may be combined (`run.unit_cells`)

| Baseline | Combined steps | Not computed, and why |
|---|---|---|
| `as_logged` (recorded) | cache + context + routing | none: R-B3 prices its target at implied recorded rates (ADR-0046 point 5) |
| `premium_gpt_5_5`, `todays_models`, `best_single_cheap` (price-file) | context + routing | cache: R-B1 saves recorded per-call fees, and these baselines have no fee block |

Repriced saving (updated 2026-11-03): **each step's own effect at each baseline's prices**: R-B2 before minus after (logged tokens, then lowered by the net tokens saved), R-B3 with that baseline's model as the incumbent (ADR-0046 point 6; Q-B21 answered for Pipeline B). So per-baseline savings of the steps add, and the sum rule is checked per baseline. In `combined.*` routing is priced on the post-context tokens it saw. Rows: every scored LLM row whose cost is known (no longer only the rows routing can price).

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

## Results, tune split (full data, `code_commit` 9f05b25, 2026-11-03)

Rows through `combine`: every tune-period row (R-B1 cache history). Counted: `split_by_session == "tune"` rows (230,762; 209,331 LLM). Logged-model prices (ADR-0041). Naive timestamps (Q-06). Handoff only: no winner.

**Recorded units, `as_logged`** (baseline 327.779 over LLM rows with a known cost; routing at implied recorded rates, its unknown rows out of its own sum):

| Run | Cache + context (blocks) | Routing | Total | Share |
|---|---|---|---|---|
| R-B1 alone (1-day TTL) | 3.580 (fees) | — | 3.580 | 1.09% |
| R-B2 alone, stated scenario | 7.657 (token cost) | — | 7.657 | 2.34% |
| R-B3 alone | — | 39.236 | 39.236 | 11.97% |
| combined, conservative default | 3.580 | 39.236 | 42.816 | 13.06% |
| combined (`PostContextRouting`), stated scenario | 11.237 | 38.998 | **50.235** | 15.33% |
| combined as `combine` is today, stated scenario | 11.237 | 38.900 | 50.137 | 15.30% |

**Price-file units** (each step's own effect; R-B1 not computed in these units):

| Run | `todays_models` | `premium_gpt_5_5` | `best_single_cheap` |
|---|---|---|---|
| R-B3 alone | 37.734 | 2,050.815 | 0 |
| R-B2 alone, stated scenario | 8.137 | 143.834 | 1.438 |
| combined (`PostContextRouting`), stated scenario | **45.676** (8.137 + 37.539) | 2,179.440 | 1.438 |
| combined as `combine` is today, stated scenario | 45.871 (8.137 + 37.734) | 2,194.648 | 1.438 |

**Sum rule** (combined ≤ standalone sum, per baseline): equal for the conservative default in every baseline; holds strictly for the stated scenario (`as_logged` 50.235 < 50.473, `todays_models` 45.676 < 45.871, `premium_gpt_5_5` 2,179.440 < 2,194.648; `best_single_cheap` equal: routing saves 0 there). The gap is the 1,289 requests touched by both context and routing: routed on fewer tokens, routing saves less on them. `combine` as it is today counts both steps on the same tokens, so it overstates the combined saving by that overlap (Q-B20).

**Overlaps** (stated scenario, scored LLM rows): cache 1,555, context 15,013, routing 9,513; cache & context 1,414, cache & routing 224, context & routing 1,289, all three 193.

## Superseded results (2026-11-02, `code_commit` 5a68fb6)

Interim eligibility, the `s75-g55` price file and the old "baseline minus the pipeline's own cost" definition on the 88,971 rows routing could price: combined `as_logged` 11.237 (3.43%, routing not computed); combined `todays_models` 0.888. Replaced by the results above.
