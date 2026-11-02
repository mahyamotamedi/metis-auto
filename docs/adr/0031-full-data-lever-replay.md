# ADR-0031: Full-data lever experiments are a separate pandas replay in `analysis/`, not an extension of the Stage 8 runner

- Status: **decided** (path, layer, promotion rule); the number is provisional until merged with `main` (0031 was the next free number on `origin/main` on 2026-11-02). Final plan S-4.
- Relates to: ADR-0006 (metric definitions, candidate hits), ADR-0008 (sample EDA is exploratory), ADR-0009 (layers, promotion), ADR-0022 (experiment runner), ADR-0027 and ADR-0028 (local database, golden-v1), H-3, H-8, X1, X2, X5, X7 (`docs/full_eda/full_eda_report.md`, `docs/full_eda/experiment_plan.md`), QA-REPRO.
- Detail: [final sprint plan](../superpowers/plans/2026-11-01-final-plan.md); format of the results: [ADR-0032](0032-lever-result-and-manifest-format.md).

## Context

The sprint compares competing versions of three saving steps (cache, context, routing) on the full dataset: 710,640 messages and 349,079 AI requests (full-dataset EDA, `requests.parquet`, observed). The Stage 8 `ExperimentRunner` (ADR-0022) cannot do that: `wiring/experiments.py` builds its cases from the sample file only (`SAMPLE_PATH`, `SampleDataSource`, checked 2026-11-02), and it records a run through pipeline events, which a replay over logged requests does not produce. The hypotheses to test are in the EDA (H-3 full-key exact cache, H-8 curated first-turn cache) and its experiment plan (X1 hit correctness, X2 retrieval fees, X5 chunk deduplication, X7 routing benchmark).

## Alternatives considered

| | (a) Extend `ExperimentRunner` to the full data | (b) Separate pandas path in `analysis/`, candidates in `experiments/` |
|---|---|---|
| Data | a full-data `DataSource`, case objects for 349,079 requests, events for each | the existing `requests.parquet` frame |
| Fit | the runner replays strategies through the pipeline per case; a cache replay needs time order across all requests, which per-case runs do not give | `analysis/cache_replay` already replays in time order over a frame |
| Cost to build | a large change to a stable, tested stage (ADR-0022) in four days | small: one protocol, one combine function, one result format |
| Event volume | ADR-0022 already notes about 35 MB of events for 465 cases; the full data would be far larger | none; results are aggregates |
| Risk | breaks Stage 8 tests, touches shared files | no shared file changes |

## Decision

1. **Option (b).** Full-data lever experiments are pandas replays over the requests frame, in `src/metis_auto/analysis/` (`levers.py`, `lever_result.py`). A step version is a small object with `apply(frame, context) -> frame`; `combine` applies cache, then context, then routing.
2. **Candidate versions live in `experiments/<area>/<id>-<slug>/version.py`** and are loaded only by scripts. `analysis` imports only `domain`, `ports` and `contracts` (ADR-0009, `tests/architecture/test_import_rules.py`).
3. **The promotion rule of ADR-0009 and ADR-0022 is unchanged:** evidence against both baselines, then a move into the package under the import rules, offline tests, selection by one config entry, and a decision record. A version that wins a replay is still a candidate.
4. **One content-free `LeverResult` JSON per version**, with a reproducibility manifest (ADR-0032). The Stage 8 runner stays the tool for sample runs.
5. **Splits are by whole session and duplicate family:** tune March to July 2026, report August to October 2026, so no session straddles the split (task S-3).

## Consequences

- Results are **simulations** on logged requests (evidence class), not production savings. A cache hit is a **candidate hit** until its correctness is reviewed (ADR-0006, X1). Recorded cost is in unstated units and is never mixed with repriced cost.
- There is no live path: nothing here calls a model, and answer quality is not measured unless a separate, approved benchmark runs (X7).
- The full-data path has no event stream (ADR-0012 applies to pipeline runs). Its record is the `LeverResult` with its manifest.
- Two experiment paths now exist (sample runner, full-data replay). `docs/experiments/` should say which to use when.
- Guarding tests (S-1): `tests/unit/analysis/test_levers.py::test_combine_applies_cache_then_context_then_routing`, `::test_cache_hit_gets_zero_context_and_routing_saving`, `::test_combined_saving_is_below_sum_of_standalone_savings`, `::test_workflow_rows_never_counted`; layer rule: `tests/architecture/test_import_rules.py`; module rows: `tests/architecture/test_module_reference.py`.
