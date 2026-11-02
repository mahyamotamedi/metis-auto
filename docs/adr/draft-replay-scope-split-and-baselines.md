# ADR-XXXX (replay-scope-split-and-baselines): The replay split is for fitting only, a straddling duplicate family stays on the report side, and baselines never mix recorded with repriced units

- Status: **decided** by the project owner, 2026-11-02 (Pipeline C, task S-3). `min_n = 30` and the `todays_models` price coverage are **provisional**.
- Date: 2026-11-02
- Relates to: [ADR-0031](0031-full-data-lever-replay.md) (full-data lever replay in `analysis/`), [ADR-0032](0032-lever-result-and-manifest-format.md) (lever results, two cost blocks), [ADR-0002](0002-configurable-baselines.md) and [ADR-0026](0026-premium-baseline-gpt-5-5.md) (baselines, premium gpt-5.5); FR-EVAL-06, FR-EVAL-08, QA-REPRO; sprint plan S-3.
- Code: `src/metis_auto/analysis/replay_scope.py`, `src/metis_auto/analysis/baselines_full.py`, `config/evaluation/sprint.toml`.

## Context
The full-data lever replay (ADR-0031) fits thresholds and classifiers on a tune period (March to July 2026) and reports on a report period (August to October 2026), with times from `a_timestamp` (naive, timezone unknown, Q-06). A fit leaks into the report if the same session or the same question is seen on both sides. A question repeats as a duplicate family: `(bot_id, u_h_norm)` over rows with user text. Sessions and families can both cross the boundary.

The first S-3 rule sent a straddling family to the side that held more of its rows, with a seeded tie-break. On the full `requests.parquet` that excluded 9,130 report-period rows from the report side (tune 271,677, report 63,980, excluded 13,422). The report side then depended on what the tune side happened to hold, and every lever reported on a smaller, reshaped report period. The owner was asked whether the tune side should always lose (open question, 2026-11-02).

The baselines (ADR-0002, ADR-0026) mix two kinds of figure. `as_logged` is the cost the logs record (recorded units, a fee block and a token block). The other three reprice the logged tokens with a price file (price-file units, token prices only). Many logged models have no row in the price file.

The traffic is concentrated: the top user holds 41.6% of requests (ledger `tenant.*`, full EDA; to re-check per sample), so a sample can be one tenant's behaviour.

## Decision
1. **The split is for fitting data only.** `split_by_session` labels rows for fitting (thresholds, classifiers). A cache's time window (for example R-A1's d−90…d−1) uses `period`, not the split, and may look back across the boundary.
2. **A whole session takes the period of its earliest timed request** (`a_timestamp`, then `a_order`). A session without a time is `unknown`, never silently tune.
3. **Report side keeps a straddling family.** A duplicate family with rows on both sides keeps its `report` rows; its `tune` rows become `excluded`. No `report` row is relabelled, so the report side is exactly the report sessions. There are no ties, so the seed does not change the split (it stays in the signature for the plan's shared interface). `excluded` rows are counted and reported (FR-EVAL-08).
4. **Tenant = `user_id`, capped at 0.35.** `cap_tenant_share` downsamples the largest tenants (a missing `user_id` is its own tenant) so none holds more than `[sample] tenant_cap = 0.35` of a sample. The other tenants keep every row; inside a capped tenant whole sessions are kept in a seeded order.
5. **Recorded units are never mixed with repriced units.** `as_logged` is in recorded units with blocks `fees` and `token_cost`. `premium_gpt_5_5`, `todays_models` and `best_single_cheap` are in price-file units and carry `token_cost` only; they have no `fees` key.
6. **Unknown prices are unknown, not zero.** A row whose model has no catalogue entry or price is counted in `n_unknown` and left out of the sum; it is never priced at zero. A premium model without a price is refused.
7. **The four baseline keys** are `premium_gpt_5_5`, `as_logged`, `todays_models`, `best_single_cheap` (`baselines_full.BASELINE_KEYS`, the keys of `compare.BASELINES`). Each has `total` and the counts `n_requests`, `n_known`, `n_unknown`.

Results are reported per period and per stratum on the report side (FR-EVAL-06); the split keeps every report session, so a stratum is not thinned by what the tune side holds. Same data, config and seed give the same labels and sample (QA-REPRO).

## Alternatives considered
- **Majority side wins, seeded tie** (first S-3 rule): keeps more tune rows, but removes report rows (9,130 on the full data) and makes the report side depend on the tune side. Rejected by the owner.
- **Drop a straddling family from both sides:** no leakage, but loses report rows as above. Rejected.
- **Split by row time, not by session:** a session's later turns would land in the report while its start is fitted on. Rejected (leakage).
- **No family rule, sessions only:** the same question under the same bot would be fitted on and reported on. Rejected (leakage).
- **A seeded held-out split inside the tune period:** not needed now (owner, 2026-11-02); can be added later without changing this rule.
- **Price fees for repriced baselines, or price unknown models at zero:** both would invent figures; zero would also understate cost. Rejected.
- **Tenant = bot or session:** a user runs many bots and sessions; the concentration is per user. Rejected.

## Consequences
- On the full `requests.parquet` (2026-11-02, aggregates only): tune 234,759, report 73,063, excluded 41,257 (40,541 of them tune-period rows, 716 report-period rows from tune sessions that cross the boundary). The tune side is smaller than under the majority rule; fitting has less data, the report side has all of it.
- A family's whole tune history is dropped if it appears once in the report. Popular, recurring questions are therefore under-represented in tune fits; levers that fit on frequency should say so.
- `excluded` is a tune-side count; callers report it with every fit (FR-EVAL-08).
- Until a price file covers the logged models, most `todays_models` rows are unknown (150,089 of 245,518 LLM rows on 2026-11-02), and that baseline is incomplete, not small.
- A demo or report that adds `as_logged` to a repriced baseline breaks this ADR; `LeverResult.baseline_cost` copies only the cost keys (ADR-0032).
- Guarding tests: `tests/unit/analysis/test_replay_scope.py` — `test_straddling_family_keeps_report_rows`, `test_no_session_or_duplicate_family_straddles_the_split`, `test_seed_does_not_change_the_split`, `test_period_unknown_when_timestamp_missing`, `test_boundaries_inclusive`, `test_sprint_toml_periods_load_and_do_not_overlap`, `test_sample_caps_any_tenant_at_35_percent`, `test_cap_impossible_with_too_few_tenants`; `tests/unit/analysis/test_baselines_full.py` — `test_four_baselines_with_two_cost_blocks` (four keys, no `fees` on repriced baselines, unknown is not zero), `test_best_single_cheap_model_baseline_uses_only_callable_models`, `test_unpriced_premium_model_is_refused`.
