# E2: scenario configuration, derivability, and what is computed while values are unset

Status: **provisional** (Stage E2, 2026-10-30). Code: `src/metis_auto/evaluation/costing/`. Spec: [evaluation framework §2](evaluation_framework.md). No scenario value, cache-hit rate or maximum age is set anywhere in the repository; every value below is supplied by the owner, or derived from recorded data once it exists.

## 1. Config fields and units

TOML under an experiment, parsed by `parse_scenario_config` (unknown keys are refused). Every section is optional.

```toml
max_age_days = <integer days, >= 0>      # price-table maximum age; unset = staleness not evaluated

[[output]]                                # output-length scenario (one table per scenario)
name = "<unique string>"
source = "recorded_quantile"              # or "documented_assumption"
# recorded_quantile only:
quantile  = <probability, 0 < q < 1>      # of recorded billed output tokens per request
estimator = "<name of a fitted estimator passed to the engine>"
# documented_assumption only (all required):
output_tokens_per_request = { "<model_id>" = <integer tokens, billed output incl. reasoning> }
assumption_note = "<why these numbers; non-empty>"

[[cache]]                                 # provider prompt-cache scenario
name = "<unique string>"
source = "measured"                       # share derived from recorded usage; takes no value
# or:
source = "sensitivity_range"
cached_input_share = <fraction of billed input tokens read from cache, 0..1>
label = "<must say it is hypothetical; non-empty>"
```

| Field | Unit | Required when | Effect if unset |
|---|---|---|---|
| `max_age_days` | whole days | never | price age reported as `not_evaluated` (`max_age_unset`) |
| `output.quantile` | probability in (0, 1) | `recorded_quantile` | scenario refused at parse time |
| `output.estimator` | name | `recorded_quantile` | row `not_evaluated` (`estimator_not_provided`) |
| `output.output_tokens_per_request` | tokens per request, per `model_id` (reasoning included, because it is billed as output) | `documented_assumption` | a model not named gets `not_evaluated` (`model_not_in_scenario`) |
| `output.assumption_note` | text | `documented_assumption` | scenario refused at parse time |
| `cache.cached_input_share` | fraction of billed input tokens | `sensitivity_range` | scenario refused at parse time |
| `cache.label` | text | `sensitivity_range` | scenario refused at parse time |

Provenance: `recorded_quantile` and `measured` results are `estimated` (a fit on measured usage applied to other requests); `documented_assumption` and `sensitivity_range` results are `simulated`. A hypothetical share is never reported as a hit rate.

Other arguments the code needs (supplied by the caller or the experiment, no defaults): input tokens per request per model and their fidelity; `min_stratum_n` and the strata keys for the stratified estimator; the quantile list for cost summaries; `min_n`, `n_boot`, `seed`, `level` for estimator comparison.

## 2. What can be derived from existing recorded data

Recorded data in this checkout: no `data/recorded/` and no `data/spend/` directory exist here. The only recorded provider-reported usage is the committed live-check records in `docs/references/` (2026-10-18 and 2026-10-19): a few dozen tiny synthetic calls across `gpt-5-nano`, `gpt-4.1-nano`, `gpt-4o-mini`, `deepseek-v4-flash`, `mimo-v2.5` (and one `grok-4-1-fast`), with answers of 2–3 characters and prompts of roughly 1,300–1,800 tokens; the cache probe makes two identical calls per model, so most models have only a handful of observations.

| Value | Derivable now? | From what | Limit |
|---|---|---|---|
| Reasoning tokens as a scenario | **No** | probes report reasoning tokens (for example `gpt-5-nano` 64, 128, 256; DeepSeek 9–30; MiMo 10–13; the two non-reasoning OpenAI models 0) | trivial prompts, n = 2 per model, below the arithmetic floor for any quantile above the median; not Persian chat; no `gpt-5.5` data at all |
| Output-length scenario | **No** | same | same |
| Cached share | **No** (as a scenario) | probes show identical repeat calls reading 1,152 of 1,274 input tokens (`gpt-4.1-nano`, `gpt-4o-mini`), 1,280 of 1,535 (DeepSeek), 1,792 of 1,807 (MiMo), and none for `gpt-5-nano` | an immediate repeat of one identical prompt is a best case for a prefix cache, not a workload hit rate; it shows that provider caching exists and how it is reported, nothing about traffic |
| Price-table age | **Yes** | the price table's own `checked_on` | see §3 |
| Input cost, uncached | **Yes** | tokenizers and the price table | needs per-request input token counts (E3 / the sampling run) |
| Cost line and break-even | **Yes** | the price table alone | break-even assumes equal output length |
| Estimator accuracy (A, B, C) | **No** | needs the sampling run | the code is tested on synthetic records only |

## 3. Price information and the price-table age

- Current table: `prices-metis-2026-10-18-s75-g55`, from the Metis pricing page saved 2026-10-18 (committed extract `docs/references/metis_pricing_2026-10-18.csv`). Its **oldest check date is 2026-10-18**; `effective_from` is **unknown** (the page states none). As of 2026-10-30 its age is **12 days**.
- With `max_age_days` unset the engine reports `not_evaluated` / `max_age_unset` and says: staleness is not judged; every cost carries the table version and check date; nothing warns when prices may have changed. Set a maximum only as a documented decision, not a default.
- External price information still needed: a re-check of the `gpt-5.5` row (and the whole page) on the Metis pricing page before any budget decision or live run. The `gpt-5.5` figures (5.5 / 33.0 / 0.55 USD per 1M tokens; long tier 11.0 / 49.5 / 1.1) come from that 2026-10-18 extract, not from a first-party model page. `gpt-5.5` context window, output limit and reasoning capability are **unknown** (not found in a first-party source on 2026-10-30; third-party aggregators disagreed) and are left unset in the catalogue.
- Pricing differences between reasoning and non-reasoning modes, and between serving providers of the same open model, are not in the table; they need the pricing page or provider docs.

## 4. Additional experiments required

- The **pilot** (recorded sampling run, E4): provider-reported output, reasoning and cached tokens for realistic Persian requests per model and effort. Until it exists, every output-length and cache scenario above has no data-derived value.
- A **cache experiment** (repeat-prefix sequencing at realistic spacing) to measure a workload-like cached share; the instruction prefix is the cacheable part.
- A first-party check of `gpt-5.5` capabilities and limits.

## 5. What E2 computes while the values are unset

- **Always:** the price-table age report with its consequence; input-only cost per model (no cached discount, no output; caveat `output_not_included`, a lower bound) given input token counts; the cost line (fixed cost plus a price per output token) and the break-even output tokens between two models; cost quantiles with the arithmetic floor (a p99 needs at least 100 values, a p90 at least 10).
- **Row-by-row `not_evaluated`, with a reason:** `no_output_scenarios_configured`, `no_cache_scenarios_configured`, `estimator_not_provided`, `no_recorded_usage`, `cached_tokens_not_reported`, `model_not_in_scenario`, `model_not_in_catalogue`, `quantile_not_identifiable`, `min_stratum_n_unset` (pooled fallback, stated).
- **Computed only once an output scenario exists:** cost per output scenario under *no cache discount* (`uncached`) is shown for each configured output scenario, because it prices every token at the table's input rate and assumes no hit rate; configured cache scenarios add their own rows.
- **Estimators A, B, C** are implemented and tested on synthetic records; their comparison (paired loss difference with a session-cluster bootstrap interval) needs recorded data and a held-out split by session and duplicate group (E0).
