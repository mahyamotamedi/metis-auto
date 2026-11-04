# Which models does Metis serve? Probe of 2026-11-04

Content-free. Written 2026-11-04 for ADR-0053 amendment 5 (judge change) and the arm list. Raw results of two script runs: `metis_model_availability_2026-11-04-b.json` and `-c.json` (the first run's file was lost to a Windows encoding error in the script, since fixed; its three answers are taken from the recording `data/recorded/live-wrapper-check-20261104T102505Z-5d33b5.jsonl`, git-ignored).

## Method

The Metis wrapper pages document **no model-list endpoint** (`metis_wrapper_api.md`), so no list call exists. One tiny SYNTHETIC message per model (the live wrapper check's message, `[SYNTHETIC] ... reply with the word OK`), output limit 4096 requested (answers were 1 to 268 tokens), through `scripts/model_availability_probe.py`, the spend guard and the ledger. The pricing page (`metis_pricing_2026-10-18.csv`) is a list of billed names, **not** proof of callability (it still lists `gpt-4.1-nano`).

## Result

| Model ID sent | Outcome | Provider-reported model | Usage (in / out / reasoning) |
|---|---|---|---|
| `deepseek-v4.1-flash` | **answers** | `deepseek-flash` | 65 / 34 / 31 |
| `deepseek-v4-flash` | answers | `deepseek-flash` | 65 / 35 / 32 |
| `gpt-5-nano` | answers | `gpt-5-nano-2025-08-07` | 43 / 268 / 256 |
| `gpt-4o-mini` | answers | `gpt-4o-mini-2024-07-18` | 44 / 1 / 0 |
| `gpt-4.1-nano` | **HTTP 404 `model_not_found`** (again) | n/a | n/a |
| `mimo-v2.5` | **HTTP 400** (again) | n/a | n/a |

## DeepSeek V4.1

- `deepseek-v4.1-flash` **is accepted under its own ID** (a row of the pricing page with the same three prices as `deepseek-v4-flash` and `deepseek-flash`).
- The wrapper reports the same model name, `deepseek-flash`, for it and for `deepseek-v4-flash`, with the same input count (65) and the same reasoning behaviour. **As far as the wrapper shows, they are the same served model** (V4.1-Flash-1017, `catalogue-metis-test.toml` note). The names being aliases is an inference from the reported name, not a statement by Metis.
- Consequence for the judge: the judge `deepseek-v4.1-flash` and the arm `deepseek-v4-flash` are one model. Both are DeepSeek family; the self-preference handling in ADR-0053 amendment 5 treats them as one.
- `deepseek-v4-pro` (stronger) is a separate, higher-priced model on the pricing page. It was not probed and is not used.

## Cost and ledger

Six answered or failed calls in three script runs; the charges are in `data/spend/ledger.jsonl` (append-only, untouched): **0.003271 USD** in total (the two failed calls were charged their pre-call estimates, 0.00181 and 0.00127 USD, because the guard cannot price a call with no usage; the provider billed nothing for a 404/400).

## Stale results (not re-run)

Results whose candidates or targets named a model that is not callable (`gpt-4.1-nano`, `mimo-v2.5`):

- `reports/levers/rb3.knn-router.k-5.report.{as_logged,best_single_cheap,premium_gpt_5_5,todays_models}.json` (primary variant).
- `reports/levers/rb3.knn-router.with_reasoning_models.k-5.report.{as_logged,best_single_cheap,premium_gpt_5_5,todays_models}.json`.
- `reports/routing/exp-route-011/report.json` (primary candidates include `gpt-4.1-nano`; with-reasoning variant also `mimo-v2.5`).
- `reports/routing/routing-base/tune_eligibility.json` (candidates and per-candidate rows).

The `tune` files of the same router (k-5/15/50) do not name either model. Results produced after 2026-11-03 under `sprint.toml [routing] candidates` (`gpt-5-nano`, `gpt-4o-mini`, `deepseek-v4-flash`) are not stale. Data tables that merely list logged models (EDA, `reports/cost/exp-cost-002`) are not stale: logs name what customers used. The kNN router (ADR-0048) must be re-run on callable candidates before its numbers count; that is the router owner's decision.
