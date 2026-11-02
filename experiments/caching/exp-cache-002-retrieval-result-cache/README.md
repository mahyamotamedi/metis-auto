# EXP-CACHE-002: retrieval-result cache (sprint task R-B1)

- **Hypothesis:** H-3 (repeats exist and part of them can be served safely). Here the repeat is a *retrieval lookup*: the same bot, corpus, settings and normalised query within a TTL can reuse the earlier lookup's chunks and avoid that lookup's recorded fee. Traces: FR-XCACHE-01, FR-XCACHE-04, QA-PRIV, QA-REPRO; plan task R-B1; decisions in [ADR-XXXX (retrieval-result-cache-accounting)](../../../docs/adr/draft-retrieval-result-cache-accounting.md), [ADR-0034](../../../docs/adr/0034-cache-guard-key-encoding-and-check-order.md) (guard) and [ADR-0036](../../../docs/adr/0036-replay-scope-split-and-baselines.md) (scope, split, baselines and their units).
- **Evidence class:** *simulation* on logged lookups (the closest class the real `LeverResult` allows). It is **measured potential, conditional on Metis-Auto being able to intercept retrieval** (open Metis question). Three separate statements: *candidate reuse* (a hit in the replay), *verified agreement* (overlap with the later real lookup, measured offline on every hit) and *production correctness* (not measured).
- **Status:** tune period run on full data on the shared S-3 code (2026-11-02): `replay_scope.scope`, `replay_scope.split_by_session` and `baselines_full.baseline_costs` (ADR-0036). The Day 2 interim stand-ins are retired. The report period is not read yet (read once, at the end).

## Data scope (ADR-0036; owner decision 1, 2026-11-02)

- **`period`** is per row, from `a_timestamp`, with the inclusive bounds in `config/evaluation/sprint.toml [periods]` (`replay_scope.scope`). A missing provider is an error, not unknown.
- **Cache history:** every tune-period LLM row. A cache's state and time window may look back across the split boundary, so rows the split marks `excluded` (and tune-period rows of report sessions, if any) still look up and insert.
- **Fitting and results:** the TTL is a fitted threshold, so it is chosen, and every result is counted, on rows with `split_by_session == "tune"` only (`run.choose_ttl`, `run.evaluate(..., scored=...)`). The `excluded` count per period goes with every result (`split` slice and `summary.json` `split_counts`; FR-EVAL-08).
- **Frequency bias** (ADR-0036, Consequences): the split drops a duplicate family's whole tune history if the family appears even once in the report period. Recurring questions are therefore under-represented on the tune split, and the TTL choice rests on repeat rates, a frequency-based fit. `summary.json` reports the repeat-rate table on the tune split and, for comparison only, on all tune-period rows, and whether the TTL rule would choose a different TTL on all tune-period rows (`frequency_bias`). The comparison never picks the TTL. Every result carries this in its `assumptions`.
- **Settings** all come from `sprint.toml` in the script: periods, split seed, `[cache_guard] shadow_rate`, `[sufficiency] min_n` (in the manifest) and `[baselines]`. `[sample] tenant_cap` is not applied: this is a full replay, not a sample; the tenant ranks are reported instead.

## Baselines (ADR-0036, decisions 5 to 7)

One `LeverResult` per TTL **per baseline**, keyed by `baselines_full.BASELINE_KEYS`, written to `reports/levers/rb1.retrieval-cache.ttl-<d>.user.tune.<baseline>.json`.

| Baseline | Units | `baseline_cost` | `saving` |
|---|---|---|---|
| `as_logged` | recorded | `fees`, `token_cost` (R-B1's recorded per-call split), `total` (checked equal to the shared `as_logged` total) | fee avoided in `fees`; `token_cost` 0 |
| `premium_gpt_5_5`, `todays_models`, `best_single_cheap` | price-file | `token_cost`, `total` (no `fees` key) | **not computed**: empty, so `compare` shows "saving unknown" and never ranks it |

R-B1 saves fees only. The repriced baselines have no `fees` key, and recorded units are never converted, so R-B1's saving is not computed in those units. It is never 0.

## Files

| File | What |
|---|---|
| `version.py` | `RetrievalResultCache(ttl, *, lookups, shadow_rate)` (`StepVersion`-shaped), key, fee attribution, agreement metric, replay, summary, free checks (repeat rate, chunk churn) |
| `run.py` | lookups frame from raw `rag` JSON (fingerprints only, in memory), recorded fee block, evaluation over scored rows, the TTL rule (`choose_ttl`), one `LeverResult` per baseline |

No `config.toml`: sprint step versions run through `scripts/run_pipeline_b_day2.py`, not `scripts/run_experiment.py`.

## Method (declared before running)

- **Key:** tenant + bot + corpus version + retrieval settings + `fingerprint(normalize_safe(query))`. Default tenant is the requesting user (conservative). The bot-owner scope is a sensitivity. Equal text in another tenant or bot never matches.
- **Order:** lookups in user-message time. Ties keep request order, then query position. An entry is visible only once its answer time is strictly before the lookup. The store starts empty on 2026-03-01 (cold start).
- **Freshness:** the log has **no corpus-version evidence** and retrieval settings are a configuration snapshot. `ttl=None` (no backstop) therefore makes every lookup ineligible (`no_freshness_evidence`). With a TTL, every hit is `basis = ttl_only`.
- **Fees:** a lookup's fee is the recorded `costBreakdown.per_call` amount. It is attributed only when the message has exactly one per-call item per logged query and all amounts are equal. Otherwise the fee is unknown (`fee_unattributed`) and the lookup is never skipped. Each skipped lookup counts once. The fee block is the recorded per-call sum (not the 0.002 proxy). Token cost is unchanged.
- **Agreement:** Jaccard overlap of `(chunk_id, content_hash)` sets between the cached and the later real lookup. A changed hash counts as disagreement, any unknown hash makes the result unknown, and both sets empty makes it unknown. The decision rule (≥ 0.9) uses the mean over evaluable hits.
- **TTL rule:** the largest TTL in {1, 7, 30, 90} days whose mean agreement on the tune split's hits is ≥ 0.9, with at least half of the hits evaluable.
- **Guard and shadow:** `CacheGuard.refusal` on the versioned key (`rb1-v1`) before any hit. There is no approval set and no blocklist offline, so blocks are 0 by construction. Shadow rate from `sprint.toml [cache_guard] shadow_rate` (0.01).

## Results, tune period (March–July 2026, naive timestamps, recorded units; interim split)

Free checks (LLM lookups, tune):

| Window | Repeat rate of key within window |
|---|---|
| 1 day | 5.1% |
| 7 days | 7.9% |
| 30 days | 11.2% |
| 90 days | 13.2% |

The user scope and the bot-owner scope give identical rates on tune data (not explained further here). Chunk churn: 171 of 29,370 chunk IDs (0.58%) were seen with more than one content hash. They belong to 2 of 153 bots. No chunk hash is missing.

| TTL | Hits | Mean agreement | Share ≥ 0.9 | Fee avoided / fee block | Fee avoided / total cost | Rule |
|---|---|---|---|---|---|---|
| none | 0 | — | — | 0 | 0 | ineligible (no version evidence) |
| 1 day | 2,185 | 0.976 | 0.960 | 3.6% [3.3, 4.0] | 1.24% [1.12, 1.37] | **passes** |
| 7 days | 3,038 | 0.892 | 0.841 | 5.0% [4.6, 5.4] | 1.72% [1.55, 1.90] | fails |
| 30 days | 4,224 | 0.729 | 0.640 | 7.0% [6.4, 7.4] | 2.39% [2.17, 2.63] | fails |
| 90 days | 5,215 | 0.596 | 0.498 | 8.6% [7.9, 9.2] | 2.94% [2.67, 3.22] | fails |

Intervals are 95% session-clustered bootstrap (`analysis.stats.cluster_bootstrap_ratio`). Denominators: 91,807 LLM lookups in 30,359 LLM requests with lookups, out of 224,768 tune LLM requests and 276,016 tune requests. At 1 day, 1,949 requests reuse at least one lookup: 0.71% of all requests, 0.87% of LLM requests. 57,238 lookups have an attributable fee. 34,569 do not (their messages log queries but carry no per-call billing item). On the tune LLM rows, the fee block is 34.3% of recorded cost. The EDA's 37.6% (all periods, all billing items) is the reference. The two differ in period and row scope. Shadow check at 1 day: 22 sampled, 22 agree, 0 unknown. **Tenant concentration:** all fee avoided at 1 day comes from the tenant ranked 4th by requests (11.3% of tune requests). Per-tenant rows are in `reports/caching/exp-cache-002/summary.json`.

Reading: agreement falls quickly with age, even though chunk content barely changes. Over time the *set* of retrieved chunks changes (ranking or corpus additions), not the chunk text. A 1-day backstop passes the agreement rule on tune data and saves about 1.2% of recorded LLM cost. This is measured potential with a single-tenant source. Not yet checked on the report period.

## Run

```sh
.venv/bin/python -m pytest tests/unit/experiments -q
.venv/bin/python scripts/run_pipeline_b_day2.py rb1   # needs the local derived tables and raw export
```

Outputs: `reports/caching/exp-cache-002/summary.json` and `reports/levers/rb1.*.json` (16 `LeverResult` files: 4 TTLs × 4 baselines).
