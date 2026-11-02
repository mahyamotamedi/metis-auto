# EXP-CTX-002: cross-turn chunk policy (sprint task R-B2)

- **Hypothesis:** H-1 (context can be reduced). A retrieved chunk that was already supplied earlier in the same session, with the same content, does not need to be sent again *if the model still sees it*. A short pointer replaces it. Traces: FR-CTX-02, FR-CTX-03, QA-PRIV, QA-REPRO; plan task R-B2; Review Focus 4 (same ID, changed hash); scope, baselines and units: [ADR-0036](../../../docs/adr/0036-replay-scope-split-and-baselines.md).
- **Evidence class:** *hypothetical reconstruction*. **Tokens only, quality not measured.** Token savings alone cannot pass the context quality rule (loss − win within noise + 3 points, groups, JSON, language, refusals). That needs the paid ablation (cut-first d).
- **Status:** tune period run on full data on the shared S-3 code (2026-11-02): `replay_scope.scope` and `baselines_full.baseline_costs` (ADR-0036). The Day 2 interim stand-ins are retired. The report period is not read.

## Data scope (ADR-0036; owner decision 1, 2026-11-02)

R-B2 has **no fitted parameter**: visibility and pointer size are scenarios. Its scenarios therefore run on `period == "tune"` LLM rows (per row, from `a_timestamp`), with no fitting split; `split_by_session` is not applied. Settings (periods, seed, `min_n`, `[baselines]`) come from `config/evaluation/sprint.toml` in the script. The cached-token convention is `baselines_full.cached_reported_separately` (the EDA's rule; `summary.json` says whether it equals the EDA table).

## Baselines (ADR-0036, decisions 5 to 7)

One `LeverResult` per scenario **per baseline**, keyed by `baselines_full.BASELINE_KEYS`, written to `reports/levers/rb2.cross-turn.k-<w>.ptr-<p>.<pointer|ledger>.<baseline>.json`.

| Baseline | Units | Saving |
|---|---|---|
| `as_logged` | recorded | net tokens removed × the request's recorded ordinary input rate, inside `token_cost` (method below) |
| `premium_gpt_5_5`, `todays_models`, `best_single_cheap` | price-file | `baseline_costs(before) − baseline_costs(after)` per baseline, where "after" lowers each changed request's `a_bill_inputTokens` by its net tokens removed, never below the cached tokens for models that count them inside input (`run.after_tokens`). The cheapest single model must be the same before and after. |

Recorded and price-file units are never mixed; an unknown price stays unknown (`n_unknown` in the baseline).

## Rule (`version.py`)

`CrossTurnChunkPolicy(pointer_tokens, assume_visible, session_ledger, *, chunks, tokens_per_char)`:

- **Drop** only within the same session and scope (requesting user + bot), only for the same `(chunk_id, content_hash)`, and only when `assume_visible(k)` holds. `k` is the number of requests back to the chunk's last **full** supply (`k ≥ 1`). A dropped chunk is not counted as re-supplied, so `k` keeps growing until the chunk is sent again.
- **Keep:** first seen, same ID with a changed hash, unknown hash, not visible, net saving ≤ 0, unknown input rate.
- **Visibility default:** `lambda k: False` (drop nothing), because the history policy cannot be reconstructed from the log (EDA §2). `k ≤ 1`, `k ≤ 3` and "all earlier turns" are hypothetical scenarios, reported separately.
- **Added tokens:** `pointer_tokens` per dropped chunk. With `session_ledger`, one append-only block of `pointer_tokens` per distinct chunk supplied earlier in the session, sent on each turn that drops.
- **Tokens:** `n_chars × 0.3384` (EDA claim `recon.t0rag.coef_rag`, turn-0 RAG fit, R² 0.95, *hypothetical reconstruction*). No tokenizer is used.
- **Cost:** only `block_token_cost` is lowered. The price is net tokens × the request's recorded ordinary input rate (`costBreakdown.input_tokens` ÷ ordinary input tokens). Ordinary input follows the cached-token convention: for the 5 models whose `inputTokens` excludes cached tokens it is `inputTokens`, otherwise `inputTokens − cachedInputTokens`. Provider-cached input is not repriced. The cap is the ordinary input, so input never goes below zero. Fees and output are unchanged.
- **Skipped:** rows served by an answer cache, and workflow rows. Rows where R-B1 reused retrieval stay eligible.
- **S-6:** a repeat of the same `(chunk_id, hash)` inside one request is `within_message` and is never counted here. S-6 is not on any branch yet (2026-11-02).

## Results, tune period (March–July 2026 by `a_timestamp`, LLM rows, naive timestamps; regenerated 2026-11-02 on the shared scope, `code_commit` 91c5b35)

Data: 220,908 tune LLM requests; 29,111 with chunks; 461,387 chunk rows; no unknown chunk hash. The input rate is unknown for 41,847 requests (mostly March, logged without `costBreakdown`, see F-2), so their drops are not counted. The cached-token convention from `baselines_full.cached_reported_separately` equals the EDA table (5 models). Reference: 68.0% of these chunk rows repeat a chunk already supplied earlier in the session (EDA definition, within-message copies included).

Recorded columns are shares of recorded units (`as_logged`); repriced columns are the saving as a share of that baseline's `token_cost` in price-file units (before minus after). The two kinds are never added.

| Visible window | Pointer | Ledger | Requests changed | Saved / ordinary input tokens | Saved / token cost (recorded) | Saved / total cost (recorded) | Premium gpt-5.5 | Today's models* | Best single cheap |
|---|---|---|---|---|---|---|---|---|---|
| none (default) | 8 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| k ≤ 1 | 8 | no | 16,883 | 5.34% | 5.08% | 3.05% | 3.49% | 2.77% | 3.14% |
| k ≤ 1 | 8 | yes | 15,469 | 4.88% | 4.67% | 2.81% | 3.19% | 2.15% | 2.87% |
| k ≤ 3 | 8 | no | 17,465 | 7.23% | 6.86% | 4.13% | 4.72% | 3.90% | 4.24% |
| k ≤ 3 | 8 | yes | 16,742 | 6.75% | 6.44% | 3.87% | 4.41% | 3.21% | 3.96% |
| k ≤ 3 | 16 | no | 17,462 | 7.07% | 6.72% | 4.04% | 4.62% | 3.71% | 4.15% |
| all earlier | 8 | no | 17,652 | 8.30% | 7.86% | 4.73% | 5.42% | 4.94% | 4.87% |
| all earlier | 8 | yes | 17,281 | 7.80% | 7.42% | 4.46% | 5.09% | 4.16% | 4.58% |

\* `todays_models` is **incomplete, not small**: 130,399 of 220,908 rows have no price for their logged model (the price file covers only the catalogue models; ADR-0036 Consequences), so its shares cover the 90,509 priced rows only.

Repriced shares are lower than the recorded token-cost share because the repriced baselines price every token (input, cached and output) at list prices while the removed tokens are ordinary input only, and recorded `token_cost` also holds F-2's unbroken "other" cost.

**Against the Day 2 interim run** (k ≤ 1 / k ≤ 3 / all: 5.3 / 7.2 / 8.4% of recorded token cost): now 5.08 / 6.86 / 7.86%. Cause: `period` is now per row from `a_timestamp` (shared `replay_scope.scope`) instead of per session from the first user time. That moves 3,860 LLM rows out of the tune period, **all of them later turns** (`turn > 0`) of sessions that began in July and were answered in August to October. Later turns are where cross-turn repeats are, so savings fall more than the 1.7% row change. No split is involved (R-B2 fits nothing), and the frequency bias of ADR-0036 does not apply. The conservative default is still 0.

Denominators: ordinary input tokens of all tune LLM rows; token cost and total cost (token cost + recorded fees) of the tune LLM rows whose input rate is known; for the repriced columns, the baseline's `token_cost` over the rows it can price. The append-only ledger always costs more than plain pointers here. No interval is given: these are scenario totals under assumed visibility, not estimates of a measured quantity.

Reading: under the conservative default nothing is saved. If the model keeps the last 1 to 3 turns' chunks in view, about 5–7% of input-token cost is removable, with the quality impact unknown. Against the whole recorded total, this is a share of a total that also holds F-2's unbroken "other" cost (`../../cost/exp-cost-002-cost-trace/README.md`).

## Run

```sh
.venv/bin/python -m pytest tests/unit/experiments/test_cross_turn_chunk_policy.py tests/unit/experiments/test_cross_turn_chunk_run.py -q
.venv/bin/python scripts/run_pipeline_b_day2.py rb2   # needs the local derived tables and raw billing table
```

Outputs: `reports/context/exp-ctx-002/summary.json` and `reports/levers/rb2.*.json` (32 `LeverResult` files: 8 scenarios × 4 baselines, evidence `hypothetical reconstruction`).
