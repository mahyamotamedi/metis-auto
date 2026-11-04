# EXP-CACHE-002: retrieval-result cache (sprint task R-B1)

- **Hypothesis:** H-3 (repeats exist and part of them can be served safely). Here the repeat is a *retrieval lookup*: the same bot, corpus, settings and normalised query within a TTL can reuse the earlier lookup's chunks and avoid that lookup's recorded fee. Traces: FR-XCACHE-01, FR-XCACHE-04, QA-PRIV, QA-REPRO; plan task R-B1; decisions in [ADR-0037](../../../docs/adr/0037-retrieval-result-cache-accounting.md), [ADR-0034](../../../docs/adr/0034-cache-guard-key-encoding-and-check-order.md) (guard) and [ADR-0036](../../../docs/adr/0036-replay-scope-split-and-baselines.md) (scope, split, baselines and their units).
- **Evidence class:** *simulation* on logged lookups (the closest class the real `LeverResult` allows). It is **measured potential, conditional on Metis-Auto being able to intercept retrieval** (open Metis question). Three separate statements: *candidate reuse* (a hit in the replay), *verified agreement* (overlap with the later real lookup, measured offline on every hit) and *production correctness* (not measured).
- **Status:** tune period run on full data on the shared S-3 code (2026-11-02): `replay_scope.scope`, `replay_scope.split_by_session` and `baselines_full.baseline_costs` (ADR-0036). The Day 2 interim stand-ins are retired. The report period is not read yet (read once, at the end).

## Frozen settings (2026-11-03, written before the report-split run)

Owner decision 2026-11-03: one report-split run, like R-A1/R-A2. Frozen on the tune split before any report-period read; nothing is changed after seeing report numbers. The tune summary (`reports/caching/exp-cache-002/summary.json`, key `frozen`) holds the same values.

- **TTL 1 day**, the stated default. The full TTL grid (1, 7, 30, 90 days) stays reported on the tune split; the TTL rule's own choice on the re-run is recorded next to it (`ttl_rule_choice_days`), never substituted.
- Scope `user` (tenant, bot, corpus version, settings, query fingerprint), guard key version `rb1-v1`, shadow rate from `sprint.toml [cache_guard]`.
- **Report run** (`python scripts/run_pipeline_b_day2.py rb1-report`): scored rows are the report split (`split_by_session == "report"`); the cache history is every tune- and report-period row, so **tune-period lookups may warm the cache**, as R-A1's window looks back into the tune period (owner decision 2026-11-02). Results: `reports/levers/rb1.retrieval-cache.ttl-1d.user.report.<baseline>.json`, summary `reports/caching/exp-cache-002/report.json`.

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

## Results, tune split (March–July 2026 by `a_timestamp`, naive timestamps, recorded units; regenerated 2026-11-02 on the shared scope, `code_commit` 91c5b35)

Split on the full requests frame (`split_by_session`, ADR-0036): tune 234,759, report 73,063, excluded 41,257 (40,541 tune-period rows, 716 report-period rows). Scored rows here: the 230,762 tune-split rows inside the tune period (209,331 LLM); 3,996 tune-split rows answered in the report period are not read. Cache history: all 271,303 tune-period rows (220,908 LLM, 88,037 lookups); 80,733 lookups belong to scored requests.

Free check, repeat rate of a key within the window (user scope; the bot-owner scope gives the same rates):

| Window | Tune split (decides) | All tune-period rows (comparison only) | Day 2 interim |
|---|---|---|---|
| 1 day | 4.8% | 5.3% | 5.1% |
| 7 days | 7.3% | 8.0% | 7.9% |
| 30 days | 10.4% | 11.4% | 11.2% |
| 90 days | 12.1% | 13.2% | 13.2% |

**Frequency bias, measured:** repeat rates on the tune split are 0.4 to 1.1 points lower than on all tune-period rows, as ADR-0036 expects (recurring families that reappear in the report period lose their tune rows). The TTL rule picks **1 day** on both, so the bias does not change the choice here. Chunk churn: 126 of 28,085 chunk IDs (0.45%) were seen with more than one content hash, in 2 of 153 bots; no chunk hash is missing.

`as_logged` results (recorded units; fee block = recorded `costBreakdown.per_call`):

| TTL | Hits | Mean agreement | Share ≥ 0.9 | Fee avoided / fee block | Fee avoided / total cost | Rule |
|---|---|---|---|---|---|---|
| none | 0 | — | — | 0 | 0 | ineligible (no version evidence) |
| 1 day | 1,738 | 0.976 | 0.960 | 3.31% [3.00, 3.62] | 1.09% [0.96, 1.23] | **passes** |
| 7 days | 2,359 | 0.897 | 0.849 | 4.47% [4.10, 4.83] | 1.48% [1.31, 1.66] | fails |
| 30 days | 3,272 | 0.739 | 0.652 | 6.19% [5.73, 6.59] | 2.04% [1.82, 2.27] | fails |
| 90 days | 4,025 | 0.611 | 0.515 | 7.60% [7.05, 8.08] | 2.51% [2.25, 2.78] | fails |

Intervals are 95% session-clustered bootstrap (`analysis.stats.cluster_bootstrap_ratio`). At 1 day, 1,555 requests reuse at least one lookup: 0.67% of scored requests, 0.74% of scored LLM requests. 54,337 tune-period lookups have an attributable fee. On the scored LLM rows the fee block is 33.0% of recorded cost. Shadow check at 1 day: 18 sampled, 18 agree. **Tenant concentration:** all fee avoided comes from the tenant ranked 4th by requests.

**Repriced baselines** (`premium_gpt_5_5` 4,466.99, `todays_models` 27.20, `best_single_cheap` 49.81 price-file units over the scored rows): R-B1's saving is **not computed** (empty `saving`, "saving unknown" in the comparison, never ranked). `todays_models` prices only 88,971 of 209,331 scored LLM rows (the price file covers the catalogue models only), so it is incomplete, not small.

**Against the Day 2 interim run** (1 day, agreement 0.976, 3.6% of the fee block, 1.24% of recorded LLM cost):
- Agreement is unchanged (0.976), and so is the chosen TTL.
- The saving falls to 3.31% of the fee block and 1.09% of recorded cost, from 2,185 to 1,738 hits. Two causes:
  1. **Per-row `a_timestamp` period** instead of the session's first user time. Later turns of July sessions answered in August to October leave the tune period: 91,807 → 88,037 lookups, 224,768 → 220,908 LLM rows.
  2. **The new split.** Scored rows are the tune split only. A duplicate family that recurs in the report period loses its tune rows (ADR-0036; 40,541 tune-period rows excluded), leaving 80,733 scored lookups. These are by construction the recurring questions, so hits fall more than lookups (frequency bias, above). The cache still uses those rows as history.
- The fee-block share of cost moves from 34.3% to 33.0% with the same row change.

Reading: a 1-day backstop passes the agreement rule and saves about 1.1% of recorded LLM cost on the tune split. This is measured potential, with a single-tenant source, and it is not yet checked on the report period. Agreement falls quickly with age even though chunk text barely changes: over time the *set* of retrieved chunks changes (ranking or corpus additions).

## Run

```sh
.venv/bin/python -m pytest tests/unit/experiments -q
.venv/bin/python scripts/run_pipeline_b_day2.py rb1   # needs the local derived tables and raw export
```

Outputs: `reports/caching/exp-cache-002/summary.json` and `reports/levers/rb1.*.json` (16 `LeverResult` files: 4 TTLs × 4 baselines).
