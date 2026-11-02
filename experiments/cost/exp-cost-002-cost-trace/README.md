# EXP-COST-002: trace the unexplained ~12% of recorded cost (sprint task F-2)

- **Question:** the EDA splits recorded cost into input 36.0%, output 14.3%, cached 0.4% and per-call fees 37.6% (claims `cost.split.*`). That leaves about 12% unexplained. What is it? Traces: FR-ACCT-01, H-7, QA-REPRO; plan task F-2.
- **Evidence class:** *observed* for every named `costBreakdown` key; *metadata-derived* for the usage/fixed split of items without a breakdown and for the model labels.
- **Method:** `check.trace_message` reads one AI message's billing JSON. It uses `analysis.billing.parse_billing` for the state and splits each item's `totalCost` into the blocks below, in exact `Decimal`. `check.reconcile` aggregates and checks that the blocks sum to the total. Malformed, missing and incomplete billing stays unknown, never zero. Signed values are kept. Income fields are never cost.

| Block | Source |
|---|---|
| `fees`, `input`, `output`, `cached`, `cache_write` | `costBreakdown.per_call`, `.input_tokens`, `.output_tokens`, `.cached_input_tokens`, `.cache_write_tokens` |
| `breakdown_other` | any other `costBreakdown` key (none found) |
| `breakdown_gap` | total minus breakdown, where a breakdown exists |
| `unbroken_usage`, `unbroken_fixed` | `usageCost` and `fixedCost` of items logged **without** a `costBreakdown` |
| `unresolved` | items without a breakdown and without a numeric usage/fixed split |

## Result (2026-11-02, full data, recorded units)

All 349,079 AI messages were traced: 244,995 with items, 103,764 with an empty list (workflow), 320 null. The blocks sum exactly to the recorded total of **506.744** (difference 0 in `Decimal`).

| Block | Share of recorded cost | Group |
|---|---|---|
| fees (per call) | 37.64% | fees |
| input | 35.97% | input |
| output | 14.29% | output |
| cached input | 0.40% | cached |
| **unbroken usage** | **9.49%** | other |
| **unbroken fixed** | **2.08%** | other |
| cache writes | 0.14% | other |
| breakdown gap | ≈ 0 (−1.2e-15 units, float rounding in the log) | other |
| other keys, unresolved | 0 | other |
| **other, total** | **11.71%** (59.316 units) | |

- **What the ~12% is:** almost all of it (58.62 units) is **March 2026** billing items logged without any `costBreakdown`: 44,806 items with no key and 1,119 with an empty one. 40,084 of them carry token usage. After March, items without a breakdown add less than 0.001 units in total (1,119 items, recorded cost rounds to 0.000). So the remainder is not a separate kind of cost. It is March cost whose input/output/fee split was not logged (*metadata-derived*: dated by the request's answer time, naive timestamps, Q-06).
- **Explanations ruled out:** web search calls, audio tokens, grounding queries and billable seconds are zero on every item. Cache writes are broken down (0.14%). No unknown `costBreakdown` key exists.
- **By model label** (share of the remainder): `gemini-2.5-flash` 23.2%, `claude-4-opus` 21.5%, `gemini-2.5-flash-lite` 9.8%, `gpt-5.1` 8.9%, `gpt-4o-mini` 7.6%, others smaller (`reports/cost/exp-cost-002/summary.json`). This says which models ran in March, not that those models bill differently.
- **Tune period** (March–July, interim split): the other group is 16.3% of tune cost, because all of March falls in tune. Any block share computed over the tune period must say so.

## Consequences

- No final saving may be stated as a share of a total that hides the 11.7% (all periods) or 16.3% (tune). A fee or input saving measured from `costBreakdown` covers only the broken-down part. For March, the fee and token blocks are unknown, not zero.
- R-B1 takes its fee block from `costBreakdown.per_call`. March RAG lookups mostly have no per-call item, so they are unattributed and never skipped (conservative).
- `analysis/levers.py` has two blocks (`fees`, `token_cost`). Its `with_blocks` proxy puts the March remainder into `token_cost`. The waterfall cannot show an "other" block yet (open question Q-B8 for A and C).

## Run

```sh
.venv/bin/python -m pytest tests/unit/experiments/test_cost_trace.py -q
.venv/bin/python scripts/run_pipeline_b_day2.py f2    # needs data/full_data/raw/ locally
```

It reads every period's billing, because it reconciles the EDA's all-period split. It fits nothing, and no lever decision uses its report-period rows.
