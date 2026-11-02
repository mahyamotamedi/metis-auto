# ADR-XXXX (history-token-measure): History tokens are the excess over the bot's net turn-0 base, single calls only, removed from cached input first

- Status: **decided** by the project owner, 2026-11-02 (Pipeline C, sprint task R-C2), points 1, 3, 4, 6 and 7; points 2 and 5 are the agent's precision of those decisions, **provisional** until the owner reviews them. The measure is a *hypothetical reconstruction* and an upper bound.
- Date: 2026-11-02
- Relates to: [ADR-0036](0036-replay-scope-split-and-baselines.md) (split, baselines, recorded vs repriced units), [ADR-0038](0038-context-token-saving-conversion.md) (context token saving: coefficient, pricing, once per request), [ADR-0039](0039-session-memo-gate-accounting.md) (greeting gate); FR-CTX-02, FR-CTX-03, FR-ACCT-01, FR-ACCT-02, H-2, X1, U-04; sprint plan R-C2 (and R-B2 or any later version that needs the history size).
- Code: `experiments/context/exp-ctx-004-history-budget/version.py` (`turn0_base`, `HistoryBudget`, `HalfOnLong`), `scripts/history_budget_levers.py`.

## Context
A history budget (R-C2) removes earlier turns from a request. The logs hold the whole conversation (`u_n_chars`, `a_n_chars`, `prior_chars`), but what reached the provider is unknown (EDA §2, U-04): at turn 20+ the median logged prior text is 34,506 characters (ledger `hist.median_prior_chars_turn20p`) while the median billed input is 1,024 tokens (`hist.median_input_turn20p`), so Metis already reduces history in an unknown way. A saving computed from logged characters would count text that was never sent. The EDA's proxy is the input above each bot's turn-0 median: 67.2% of billed input in single-call no-RAG requests (`hist.excess_over_t0_all`), flagged as an upper bound that also holds message growth.

ADR-0038 converts dropped characters to tokens and takes the saving from uncached input only, because chunks follow the current message (A-84). History lies **before** the current message, so it may be inside the provider-cached prefix, and that rule does not carry over.

## Decision
1. **History tokens** (owner): `hist_tokens = max(0, effective input - turn-0 base - chunk tokens)`, chunk tokens = `a_rag_chunk_chars` x ledger `recon.t0rag.coef_rag` (no logged chunk = 0), effective input as in ADR-0036 (cached added back for the models that report it separately), capped at the input. The base is fitted on the **tune** split only. A bot with fewer than `min_n` (`sprint.toml [sufficiency]`) turn-0 rows has no base: its rows are **unknown**, never 0.
2. **The base is net of chunks, from single calls** (precision): the base is the bot's median of (effective input - chunk tokens) over **single-call** turn-0 LLM rows. Without the chunk term, a retrieval bot's history would be under-counted by its typical turn-0 chunk size; for a bot without retrieval both readings are equal.
3. **Per-turn sizes** (owner): `hist_tokens` is spread over the earlier turns of the session in proportion to `u_n_chars + a_n_chars`, assuming the most recent turns are the ones sent (hypothetical). No allocation basis (earlier turns without characters) is unknown.
4. **Excluded, no saving** (owner): workflow rows, turn 0, memory bots, summarising bots, rows the greeting gate skipped (`memo_status == "skipped_phatic"`), unknown rows.
5. **Multi-call requests are unknown** (precision): a request with `a_bill_callCount` other than 1 (35,346 of 245,518 LLM rows in the full data, missing counts included; 8,560 of 17,205 over-8k LLM rows on tune) has unknown history, because its input adds up several calls and the ledger proxy covers single calls only. ADR-0038 item 3 (save once) still holds; there is just no measure here.
6. **Cached first** (owner): removed tokens come out of the request's cached tokens first, then uncached, capped at the input. Uncached only (ADR-0038 item 2) is the sensitivity, reported beside it. **Pricing** (precision of ADR-0038 item 4): `as_logged` prices the removed cached part at the model's `implied_cached_per_M` and the uncached part at `implied_input_per_M`; a missing rate for a removed part makes the saving unknown. Repriced baselines lower both input and cached and reprice (ADR-0038 item 5). Fees never change.
7. **Results** (owner): every `LeverResult` has slices `all`, `llm_only`, `over_8k`, evidence class `hypothetical reconstruction`, `correctness_state` `unmeasured`, and the assumption "tokens only, quality not measured (FR-CTX-03)". Parameters have no default.

## Alternatives considered
- **History from logged characters x a coefficient:** counts history Metis never sent (the turn-20+ gap above). Rejected by the owner.
- **Literal base (median turn-0 input, chunks included):** under-counts a retrieval bot's history by its turn-0 chunks. Rejected (point 2).
- **Multi-call input divided by the call count:** assumes every call carried the same prompt, which the logs do not show. Rejected for now; a later per-call billing join could replace point 5.
- **Uncached only, as for chunks:** for history inside the cached prefix it prices cached tokens at the full input rate and overstates the saving. Kept as the sensitivity, not the primary rule.
- **Cached part at `implied_input_per_M`** (ADR-0038's single rate): overstates the cached part. Rejected.
- **Pro-rata cached/uncached:** no evidence for either layout share. Rejected in favour of the conservative order.

## Consequences
- The measure is an upper bound (message growth, attachments and anything above turn 0 count as history). Any version that needs a history size (R-B2 visibility, a later prompt rebuild) can reuse `turn0_base` and points 1 to 3, and should cite this ADR.
- On the tune split (2026-11-02, aggregates): 81 bots have a base; 126,613 of 213,007 LLM rows have known history, 14,731 are unknown and 14,463 multi-call. Removed tokens are concentrated: one bot holds about 0.92 of them and one tenant about 0.97 (Review Focus 5), so results must be read per bot and per tenant.
- Removed cached tokens are a small part on tune (0.61M of 178.0M at `b2000`), so the primary and uncached-only `as_logged` savings differ by under 0.1%. Whether dropping old turns breaks the cached prefix for later turns (H-1) is not measured.
- Guarding tests: `tests/unit/experiments/test_exp_ctx_004_history_budget.py` — `test_hist_tokens_unknown_without_turn0_median`, `test_multi_call_request_has_unknown_history`, `test_removed_tokens_come_from_cached_first`, `test_stepped_window_drops_whole_turns`, `test_budget_only_reduces_requests_above_it`, `test_memory_and_summarising_bots_excluded`, `test_gated_rows_get_no_saving`, `test_fees_block_unchanged`, `test_parameters_have_no_default`, `test_result_labelled_upper_bound`.
