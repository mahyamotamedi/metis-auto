# EXP-CTX-004: history budget, stepped window

- **Task:** final plan R-C2 (Pipeline C). **Traceability:** FR-CTX-02 (history windowing is an experimental context strategy), FR-CTX-03 (nothing is promoted without a quality-preserving ablation), FR-ACCT-02 (unknown is never zero), H-2 (history trimming cuts input; EDA §5), X1 (history window: last *N* turns or last *T* tokens, [context_plan.md](../../../docs/experiments/context_plan.md)), H-1 (stable prefix and provider caching: the risk below), U-04 (what reached the provider is unknown), Review Focus 1 (no saving on a row the greeting gate skipped) and 5 (concentration).
- **Hypothesis:** in long conversations a token budget on history, applied by dropping the oldest whole turns, lowers input tokens and only the `token_cost` block (ADR-0032, ADR-0036). EDA reference: input above each bot's turn-0 level is 67.2% of billed input in single-call no-RAG requests (ledger `hist.excess_over_t0_all`; 75.1% of turn >= 1 input, `hist.excess_over_t0_share`), an upper-bound proxy for history, memory and summaries. Requests over 8,000 input tokens hold 65.2% of input tokens (ledger `red.input_over_8000.tokens`) in 10.7% of requests (`red.input_over_8000.reqs`).
- **Strategy:** `version.py`: `HistoryBudget(budget_tokens, step_turns)` and `HalfOnLong(min_input_tokens, step_turns)`, `StepVersion`s with step `"context"` ([levers.py](../../../src/metis_auto/analysis/levers.py)). No parameter has a default; `None`, 0 or a non-integer refuses to run.
- **Evidence class:** *hypothetical reconstruction*. The result is an **upper bound** on what a budget could remove. **Tokens only, quality not measured (FR-CTX-03)**: without the paid context ablation (cut-first d) no context decision rule can pass. `correctness_state` is `unmeasured`.
- **Not duplicated:** R-A2 (EXP-CTX-003, reranker cut) and R-B2 (EXP-CTX-002, cross-turn chunk policy) drop retrieved chunks; this version drops history only and subtracts chunk tokens before measuring history. Cut-first (c), the prompt rebuild with `k` fitted per bot, is out of scope.

## Rules (owner decisions 2026-11-02; [ADR-XXXX (history-token-measure)](../../../docs/adr/draft-history-token-measure.md))

1. **History tokens actually sent** (the plan's excess-over-turn-0 proxy, not characters): `hist_tokens = max(0, effective input - turn-0 base of the bot - chunk tokens)`. Chunk tokens = `a_rag_chunk_chars` x the ledger coefficient `recon.t0rag.coef_rag` (no logged chunks = 0). The **turn-0 base** is the bot's median of (effective input - chunk tokens) over single-call turn-0 LLM rows of the **tune** split. A bot with fewer than `min_n` (`sprint.toml [sufficiency]`) such rows has no base; its rows are `unknown`, never 0. Effective input adds cached tokens back for the models that report them separately (`baselines_full.token_counts`). Two choices here go beyond the owner's wording and are recorded in the ADR: the base is net of turn-0 chunk tokens (otherwise a retrieval bot's history would be under-counted by its turn-0 chunk size), and a **multi-call** request has unknown history (state `multi_call`), because its input adds up several calls and the ledger proxy covers single calls only.
2. **Per-turn sizes** (hypothetical): `hist_tokens` is spread over the request's earlier turns of the session (every logged turn, all splits) in proportion to their logged characters `u_n_chars + a_n_chars`. The most recent turns are assumed to be the ones sent, so the oldest go first. Earlier turns with no characters give no allocation basis: `unknown`.
3. **Stepped window:** drop the OLDEST whole turns, `step_turns` at a time, until the remaining history fits the budget. A request already within the budget is untouched. A turn is never cut in part.
4. **Excluded, no saving** (column `hist_state`): workflow rows, turn 0, memory bots (`bot_memory_enabled`), summarising bots (`bot_summarizer_mode == "AI_SUMMARIZE"`), rows the greeting gate skipped (`memo_status == "skipped_phatic"`, if the column is present; ADR-0039), `multi_call`, and `unknown`.
5. **Cached vs uncached:** history lies before the current message, so it may be inside the provider-cached prefix (unlike chunks, ADR-0038 item 2). **Primary (conservative) rule, used in every `LeverResult`:** removed tokens come out of cached input first, then uncached, capped at the input. **Sensitivity:** uncached only (the S-6 rule, `baselines_full.lower_uncached_input`), in slice `history_budget` (`saved_tokens_uncached_only`, and for `as_logged` `saving_token_cost_uncached_only`). The sensitivity is an upper bound on cost per token; in tokens it can be lower than the primary rule, because it is capped at the uncached input.
6. **Pricing** (ADR-0038, extended in ADR-XXXX (history-token-measure)): once per request; `as_logged` (recorded units) prices the removed cached part at the model's `implied_cached_per_M` and the uncached part at `implied_input_per_M` (`reports/full_eda/tables/implied_unit_rates.csv`). A missing rate for a part that is removed makes the saving unknown: the row leaves both sides and is counted in `n_saving_unknown`. Repriced baselines lower input and cached tokens and reprice with the price table's tiers. Fees never change (`saving.fees` = 0); repriced `baseline_cost` has no `fees` key (ADR-0036).
7. **Results:** one `LeverResult` per variant and baseline, `reports/levers/ctx.history_budget.<variant>.<baseline>.json`, slices `all`, `llm_only`, `over_8k` (LLM rows with effective input above 8,000 tokens) and `history_budget` (counts per state, tokens removed under both rules, and the share of saved tokens held by the top bot, the top five bots and the top tenant, as ranks).

## Variants (frozen 2026-11-02, before any report-split run)

| Variant | Version id | Rule |
|---|---|---|
| `b2000` | `ctx.history_budget.b2000` | `HistoryBudget(2000, 1)` |
| `b4000` | `ctx.history_budget.b4000` | `HistoryBudget(4000, 1)` |
| `b8000` | `ctx.history_budget.b8000` | `HistoryBudget(8000, 1)` |
| `half_over_8k` | `ctx.history_budget.half_over_8k` | `HalfOnLong(8000, 1)`: requests whose effective input exceeds 8,000 tokens keep at most half their `hist_tokens` |

All four are explored on the tune split and all four are written for the report split; nothing is chosen on the report split. `scripts/history_budget_levers.py` `VARIANTS` holds the same list.

## Assumptions

- *Current (owner decision):* the excess over the bot's turn-0 base is the history sent. It also holds the current message's growth, attachments and anything else above turn 0, so it is an upper bound (ledger note on `hist.excess_over_t0_share`).
- *Current (owner decision):* history is sent most-recent-first and is spread over turns by logged characters (hypothetical). The logged history is complete, but what reached the provider is unknown (EDA §2, U-04).
- *Current:* the turn-0 base fitted on tune holds for the report period; a bot new in the report period has no base (unknown).
- *Current:* `implied_input_per_M` and `implied_cached_per_M` are model averages in recorded units; a request's real price may differ.
- *Speculative:* dropping old turns does not change the answer. Not measured (FR-CTX-03).
- *Speculative:* the provider-cached prefix survives the drop. Dropping old turns changes the prefix of every later turn, so later turns may lose cache hits (H-1). Not measured; on tune the cached share of removed tokens is small (below).
- *Future:* with the paid ablation, the plan's context decision rule applies; with a tokenizer pass on the history text, rule 1 can be replaced by counted tokens (same interface).

## Free checks, tune split (2026-11-02; LLM rows; `reports/context/exp-ctx-004/tune_checks.json`)

Tune split: 234,759 requests, 213,007 LLM. Turn-0 base for 81 bots (`min_n` 30). LLM rows by state: known 126,613; turn 0 38,297; unknown 14,731; multi-call 14,463; summarising 10,801; memory 8,102; gated 0 (no gate column in this run).

- Share with `hist_tokens > 0`: 0.517 of LLM rows, 0.870 of rows with known history.
- Median / p90 `hist_tokens` by turn: 1: 75 / 422; 2: 169 / 729; 3-4: 200 / 912; 5-9: 230 / 1,115; 10-19: 263 / 1,191; 20+: 336 / 2,135.
- Over-8k slice: 17,205 LLM rows, of which only 3,823 have known history (8,560 are multi-call). In those 3,823, history is 0.979 of effective input; over all over-8k LLM input it is 0.460 (known history only in the numerator).
- **Concentration (Review Focus 5):** one bot holds 0.92 of the tokens removed at `b2000`, the top five bots 0.96, one tenant 0.97. These are very long sessions (median turn 172, median effective input about 41,700 tokens), with about 0.22 history tokens per logged prior character, so that bot seems to send its full history. The saving is a finding about a few bots, not about the traffic as a whole.

| Variant | Requests reduced (over 8k) | Tokens removed, primary | of which from cached | Tokens removed, uncached only | `as_logged` saving, primary | uncached only |
|---|---|---|---|---|---|---|
| `b2000` | 6,793 (3,656) | 178.0M | 0.61M | 177.5M | 18.02 | 18.01 |
| `b4000` | 4,471 (3,603) | 167.4M | 0.50M | 167.0M | 16.50 | 16.50 |
| `b8000` | 3,485 (3,485) | 152.3M | 0.36M | 151.9M | 14.83 | 14.83 |
| `half_over_8k` | 3,822 (3,822) | 98.5M | 0.32M | 98.2M | 9.69 | 9.69 |

`as_logged` savings are recorded units, against a tune `token_cost` of 233.15 over LLM rows with a known cost (`baseline_cost.total` 339.62 with fees). No row had an unknown saving. Tune dry run of the lever writer (scratch, not kept), `llm_only` saving share: `as_logged` 0.053 / 0.049 / 0.044 / 0.029; `todays_models` 0.073 / 0.062 / 0.051 / 0.043 (incomplete baseline, ADR-0036); in `over_8k` `as_logged` 0.100 / 0.096 / 0.088 / 0.058 (`b2000` / `b4000` / `b8000` / `half_over_8k`). These are tune figures for exploration; the report split is read once.

## Run

```sh
.venv/bin/python scripts/history_budget_levers.py --checks-only   # tune free checks -> reports/context/exp-ctx-004/tune_checks.json
.venv/bin/python scripts/history_budget_levers.py                 # report split, read once: 16 LeverResults in reports/levers/
```

Run the second command once, after committing, on a clean tree, so the manifest carries the code commit.
