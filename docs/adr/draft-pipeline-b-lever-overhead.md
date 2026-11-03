# ADR-XXXX (pipeline-b-lever-overhead): Pipeline B measures its own lever overhead with a second script beside Pipeline A's

- Status: **provisional**, 2026-11-03 (Kimia, Pipeline B, sprint task L-1 for R-B1, R-B2 and R-B3). Can be merged into Pipeline A's script later with A's OK (then this record is amended, not deleted).
- Date: 2026-11-03
- Relates to: [ADR-0040](0040-reranker-cut-and-lever-overhead.md) (L-1 method: offline per-request estimate, one-row `apply`), [ADR-0032](0032-lever-result-and-manifest-format.md) (`LeverResult` overhead fields), [ADR-0036](0036-replay-scope-split-and-baselines.md) (tune/report periods, split, tenant cap), [ADR-0048](0048-knn-router-nearest-profile-routing.md) (R-B3), [ADR-0045](0045-routing-base-eligibility-and-failover.md) (R-B3 eligibility); QA-LAT, FR-ROUTE-04, Q-14 (100 ms p95 target), Q-B24; sprint plan L-1.
- Code: `scripts/measure_pipeline_b_overhead.py`. Tests: `tests/unit/experiments/test_measure_pipeline_b_overhead.py`. Output: `overhead_ms_p50` / `overhead_ms_p95` in `reports/levers/rb{1,2,3}.*.json`, `reports/levers/pipeline_b_overhead.json`.

## Context

L-1 asks for an offline per-request overhead (p50 and p95, against the 100 ms p95 target of Q-14) for every lever version. Pipeline A's `scripts/measure_lever_overhead.py` (ADR-0040) does this for A's versions. Run read-only on B's results (Q-B24, 2026-11-02), it stops at `target_for` with "no known version" for `rb1`, `rb2` and `rb3`: it has no target for B's families, which need their own data frames (R-B1 a lookups frame, R-B2 a chunks frame, R-B3 a router fitted on the tune split). It also samples **report-period** rows, while B's sprint plan keeps the report period for one read at the end, and it does not apply `[sample] tenant_cap`. Until then B's overhead fields were None ("not measured").

## Decision

1. **A second script, owned by Pipeline B**: `scripts/measure_pipeline_b_overhead.py`. It follows A's method and labels (one untimed warm-up, `apply` on each row as its own one-row frame, `time.perf_counter_ns`, p50 median, p95 nearest rank, an `Overhead:` assumption and an `Overhead caveat:`), but imports nothing from A's script. A's script is not edited.
2. **One target per B family**, built with B's run helpers (`scripts/run_pipeline_b_day2.py` / `run_pipeline_b_day3.py`): R-B1 `RetrievalResultCache` with the lookups frame of the sampled rows, R-B2 `CrossTurnChunkPolicy` with their chunks frame, R-B3 `KnnRouter` fitted on the tune split. Building frames and fitting happen before timing and are not timed.
3. **Sample**: `--n` (default 1,000) seeded LLM rows of the **tune** period with `split_by_session == "tune"`, `[sample] tenant_cap` applied with `replay_scope.cap_tenant_share` to the pool and again to the draw (so the actual `n` can be a little lower; it is reported). The report period is never read.
4. **Per version, not per baseline**: the four baseline files of one version get the same figures. Every other field, the manifest included, stays as the result runner wrote it.
5. **Never 0**: a version that cannot be measured keeps None, with the assumption "Overhead: not measured (<reason>)", and `not measured` in the summary.
6. **Summary**: a content-free `reports/levers/pipeline_b_overhead.json` (per version p50, p95, max, n, the 100 ms target, pass/fail; sample rule; machine as OS, architecture and CPU model, no host name).

## Alternatives considered

- **Extend A's script with B's targets** (the better end state: one script, one method). Not done now: the script has another owner, and changing its sampling period would change A's published figures. Open to it with A's OK; this script's helpers are separate so the move is a copy.
- **Leave B's overhead unmeasured**: keeps the fields honest (None) but leaves Q-14 unanswered for B's versions, and the comparison and dashboard cannot show B's overhead.
- **Time whole batches** (a frame of 1,000 rows, divided by 1,000): cheaper, but a batch replay hides per-request fixed costs that a serving path pays on every request, so it would understate overhead.

## Consequences

- B's results carry overhead figures, comparable with A's in method but not in sample (tune vs report period); the assumption says which.
- One-row timing of R-B1 and R-B2 holds no earlier state (no warm cache store, no earlier turn), so it times the decision path, not a hit or a session lookup; each file's caveat says so. R-B3's figure includes every per-call computation its `apply` does as implemented.
- Two scripts implement the same method; a change to the method must be made in both until they are merged.
- Guarding tests (`tests/unit/experiments/test_measure_pipeline_b_overhead.py`): fields filled and labelled "offline per-request estimate", only tune-period tune-split LLM rows sampled, tenant cap applied, same seed same sample, fit time not timed for the kNN router, an unknown `lever_id` fails clearly, the summary holds no IDs or text, all baselines of a version grouped and `--dry-run` writes nothing.
