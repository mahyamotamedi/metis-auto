## Sprint Day 2, Pipeline C: within-message dedup as a token_cost saving, lever results (2026-11-02)

Sprint task S-6b, branch `context-within-message-dedup` (after S-6). **Awaiting review.** Traceability: FR-ACCT-01, FR-ACCT-02, FR-CTX-03, ADR-0032, ADR-0036, U-04, A-84.

- **Owner decisions (2026-11-02):** tokens = duplicate characters x 0.3384 (claims ledger `recon.t0rag.coef_rag`, *hypothetical reconstruction*); the saving comes out of uncached input only (A-84); a multi-call request saves once; `as_logged` priced at the model's `implied_input_per_M` (`reports/full_eda/tables/implied_unit_rates.csv`), no rate = unknown; repriced baselines lower the input and reprice with the tiers; fees never change. Repriced `baseline_cost` keeps no `fees` key (ADR-0036 kept; owner, asked during this task). Recorded as ADR-XXXX (context-token-saving-conversion), `docs/adr/draft-context-token-saving-conversion.md`.
- **New:** `scripts/context_dedup_levers.py`; `tests/unit/experiments/test_exp_ctx_001_token_saving.py` (5 tests, 11 cases, synthetic); `reports/levers/ctx.within_message_dedup.{as_logged,premium_gpt_5_5,todays_models,best_single_cheap}.json`; `reports/context/exp-ctx-001/saving.csv`.
- **Changed:** `analysis/baselines_full.py` (additive public helpers `token_counts`, `lower_uncached_input`, `repriced_row_costs`, `REPRICED_KEYS`; existing functions unchanged) + `test_repriced_row_costs_sum_to_baseline_costs`; the EXP-CTX-001 `version.py` (`tokens_per_char`, `input_rate_per_m`, `baseline_frames`, `lever_result`) and README; one row in `docs/architecture/module_reference.md`.
- **TDD:** the new test modules first failed to import (`lower_uncached_input` missing; the baselines test `ImportError`), then the 11 version cases failed (`TypeError: unexpected keyword argument 'tokens_per_char'`), then all passed.
- The tune split was used for a dry run (output in a scratch folder, not kept); the report split was read once.

### Results (report split, full data, aggregates only)

73,063 requests, 20,750 LLM; 14,519 LLM requests hold a duplicate; 55,135,530 saved input tokens (cost-known LLM rows). No LLM row with a duplicate lacked an implied rate (`n_saving_unknown` 0 for every baseline). Best single cheap model: `gpt-5-nano`.

| Baseline | Unit | Cost known / LLM | Baseline total (known) | Saving (token_cost) | Saving share |
|---|---|---:|---:|---:|---:|
| as_logged | recorded | 20,744 / 20,750 | 146.50 (fees 65.50, token_cost 81.00) | 8.948 | 0.0611 |
| premium_gpt_5_5 | price-file USD | 20,744 / 20,750 | 3,737.89 | 305.56 | 0.0817 |
| todays_models | price-file USD | 2,874 / 20,750 | 2.935 | 0.403 | 0.1373 |
| best_single_cheap | price-file USD | 20,744 / 20,750 | 39.75 | 3.032 | 0.0763 |

Shares are the same in slices `all` and `llm_only`: both sum cost over LLM rows only. Fee saving is 0 everywhere. `levers.py` computes no interval, so `ci_low`/`ci_high` are None. `todays_models` is incomplete (17,876 LLM rows have no price for their model), not small. Repriced shares exceed `as_logged`'s because repriced baselines carry no fees. Manifests carry `code_commit` `unknown` (the tree was uncommitted).

- **Open:** whether Metis sent the duplicate copies is unknown (U-04): the saving is an upper bound. The quality of dropping a copy is unmeasured (FR-CTX-03). The D-1 view shows the repriced baseline totals as unknown (no fees key); D-2 follow-up: show them as "token cost only, fees not priced".
