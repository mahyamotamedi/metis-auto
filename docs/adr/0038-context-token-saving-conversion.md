# ADR-0038: A context saving is characters x a ledger coefficient, taken from uncached input, priced per baseline

- Status: **decided** by the project owner, 2026-11-02 (Pipeline C, sprint task S-6b). The coefficient and the implied rates are **provisional** (hypothetical reconstruction).
- Date: 2026-11-02
- Relates to: [ADR-0032](0032-lever-result-and-manifest-format.md) (lever results, two cost blocks), [ADR-0036](0036-replay-scope-split-and-baselines.md) (split, baselines, recorded vs repriced units), [ADR-0020](0020-token-and-cost-accounting.md) (token and cost accounting); FR-ACCT-01, FR-ACCT-02, FR-CTX-03, U-04, A-84; sprint plan S-6, R-B2, R-C2.
- Code: `src/metis_auto/analysis/baselines_full.py` (`token_counts`, `lower_uncached_input`, `repriced_row_costs`), `experiments/context/exp-ctx-001-within-message-dedup/version.py`, `scripts/context_dedup_levers.py`.

## Context
Context versions remove text from a request: S-6 drops exact duplicate chunks inside one message; R-B2 (cross-turn chunk reuse) and R-C2 (history budget) will drop other text. The logs give the dropped text's size in **characters** (`n_chars`), not tokens, and give no per-component token count (U-04: what reached the provider is unknown). `requests.parquet` holds the billed input, cached and output tokens and the recorded total cost, but no input price per row (ADR-0032). The four baselines use two kinds of unit (ADR-0036): `as_logged` in recorded units with `fees` and `token_cost`; the other three in price-file units with `token_cost` only.

FR-ACCT-01 asks every token count to carry its method; FR-ACCT-02 asks that an unknown price gives "not computed", never zero. FR-CTX-03 forbids promoting a reduction without a quality ablation.

## Decision
1. **Characters to tokens:** saved tokens = dropped characters x the claims ledger value `recon.t0rag.coef_rag` (0.3384 tokens per retrieved-chunk character; OLS over 8,495 turn-0 single-call billed RAG requests without memory; `reports/full_eda/tables/claims_ledger.csv`). The value is read from the ledger, not typed into code. The method label is *hypothetical reconstruction* (FR-ACCT-01).
2. **Uncached input only:** retrieved chunks follow the target message (A-84), so they lie outside the cacheable prefix. The saving lowers effective input and never the cached part, capped at `input - cached` (`baselines_full.lower_uncached_input`). Effective input follows the S-3 rule (cached tokens added back for models that report them separately).
3. **Once per request:** a multi-call request saves once, not once per call.
4. **`as_logged` (recorded units):** saving = saved tokens x the logged model's `implied_input_per_M` / 1e6 from `reports/full_eda/tables/implied_unit_rates.csv`, taken off `block_token_cost` (capped at it). A model with no rate makes the saving **unknown**: the row leaves both the baseline and the saving and is counted in `n_saving_unknown` (FR-ACCT-02). A request with nothing to drop saves exactly 0, with or without a rate.
5. **Repriced baselines (price-file units):** the logged tokens and the lowered tokens are both repriced with the price table's tiers (`baselines_full.repriced_row_costs`), so a lower input can move a request to a cheaper tier. `baseline_cost` keeps no `fees` key (ADR-0036).
6. **Fees never change** under a context version: `saving.fees` = 0 for every baseline. `saving` always holds `fees`, `token_cost` and `total`; `as_logged`'s `baseline_cost` holds all three, a repriced one `token_cost` and `total`.
7. **Results:** one `LeverResult` per baseline, evidence class `hypothetical reconstruction`, `correctness_state` `unmeasured` until a quality ablation (FR-CTX-03), each assumption above in `assumptions`.

R-B2 and R-C2 reuse points 1 to 7. A version that drops history (R-C2) states its own coefficient source if chunk characters do not fit history text.

## Alternatives considered
- **chars/4:** the repo's reference estimate, not a measurement; Persian makes it unreliable (context.md). Rejected for the saving, kept as a sensitivity check.
- **A local tokenizer pass per model:** exact per model, but needs the chunk text again and tokenizers for models without public ones (Gemini, Grok). Deferred: a later upgrade of point 1, same interface.
- **Take the saving from cached input first, or pro rata:** contradicts A-84's layout (chunks after the message are never in the cached prefix). Rejected.
- **Save once per call:** would multiply a saving the logs cannot show was ever paid more than once. Rejected.
- **Price `as_logged` at a price-file rate:** mixes recorded and repriced units (ADR-0036). Rejected.
- **Unknown rate = 0 saving:** understates the saving and hides the gap. Rejected (FR-ACCT-02).
- **Fees 0 in repriced `baseline_cost`:** would show a known zero where the fee is not priced. Rejected by the owner (keep ADR-0036); the demo labels the repriced total "token cost only, fees not priced" (D-2).

## Consequences
- Every context saving is labelled hypothetical; it changes when the coefficient or the rate table changes, and the manifest's `config_hash` records the coefficient source.
- `implied_input_per_M` is a model average; requests on tiered or cached-heavy models are priced roughly.
- `todays_models` stays incomplete while the price table lacks most logged models (ADR-0036).
- Whether Metis sent the dropped text at all is unknown (U-04); the saving is an upper bound under that uncertainty.
- Guarding tests: `tests/unit/experiments/test_exp_ctx_001_token_saving.py` — `test_saved_tokens_are_uncached_input_only`, `test_as_logged_uses_model_implied_rate_and_unknown_stays_unknown`, `test_repriced_saving_can_cross_a_price_tier`, `test_fees_block_unchanged`, `test_lever_result_has_all_blocks_and_total`; `tests/unit/analysis/test_baselines_full.py` — `test_repriced_row_costs_sum_to_baseline_costs`.
