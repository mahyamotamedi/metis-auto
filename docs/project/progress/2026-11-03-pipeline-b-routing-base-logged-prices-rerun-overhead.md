## Pipeline B: R-B3 on the routing base and per-baseline incumbent, logged-price re-run, one report-split run, overhead (2026-11-03)

Branch `pipeline-b-routing-base-logged-prices-rerun-overhead` (from `origin/main` 035d7b6; `origin/main` merged in at 83a4716 and 9f05b25). Commits: 0992085 (R-B3 on R-0, interim loader removed, B overhead script), 9d70d9e (R-B3 per-baseline incumbent, repriced slices in their own units, report-split commands), 8087f3e (`compare` duplicate fix), bfa1560 (results), and this docs commit. Owner exception for this branch: the agent may `git add` / `git commit`; it never pushed or merged.

- **R-B3 switch-over** ([ADR-0048](../../adr/0048-knn-router-nearest-profile-routing.md) Amendment 1): `analysis.routing_base.eligible_models` (ADR-0045) injected with `sprint.toml [routing]`; `candidates_jev` handled as R-A3; `eligibility_interim.py` deleted; `candidate_costs` / `effective_tokens` on `baselines_full.model_row_costs` / `token_counts`.
- **Q-B21 answered for Pipeline B** (owner): ADR-0046 point 6, incumbent per baseline, as R-C3 and R-A3, plus points 4 (reasoning-billed candidates out of the primary result; `with_reasoning_models` secondary) and 5 (`as_logged` at implied recorded rates). I-2 still needs the team-wide confirmation ADR-0046 and ADR-0051 ask for.
- **Interim loader removed:** `wiring/lever_compare.py` reads `LeverResult.model_validate`; `wiring/_interim_lever_json.py` deleted.
- **`compare` fix** (`analysis/compare.py`, S-2): a duplicate version is a reused `(step, version)` inside one group, not across data scopes, so a version's tune and report results no longer flag each other.
- **Overhead:** `scripts/measure_pipeline_b_overhead.py`, [ADR-0055](../../adr/0055-pipeline-b-lever-overhead.md) (draft; Q-B24 answered). Tune-period sample, tenant cap, one-row `apply`, fit not timed. A's R-A3 figure (54.2 ms p95) used report-period rows, so the samples differ.
- **Report-split runs** (owner decision, once each, settings frozen in the READMEs and summaries first): R-B1 1-day TTL (tune lookups may warm the cache, as R-A1's window), R-B2 `k` = 0 and `k` <= 1, R-B3 `k` = 5. Scope 73,063 requests, 20,750 LLM, `data_revision` 30f578f2: the same as A's report results.
- **Docs:** interim contracts Day 3 folded into `docs/experiments/pipeline_b_interim_contracts.md` (Q-B21, Q-B23, Q-B24 answered; Q-B4, Q-B20, Q-B22 open); the day3 file is a pointer, because finalized ADR-0048, ADR-0049 and the 2026-11-02 B entry link to it. Updated: R-B1, R-B2, R-B3 and `b-only-dry-run` READMEs, `pipeline_b_decision_notes.md`, `guides/redis_cache_store.md` (link), `module_reference.md`.

### Results (`code_commit` 9f05b25, `prices-metis-2026-10-18-logged`; cost simulation, quality not proven)

| Lever | Split | `todays_models` | `as_logged` | moved / note |
|---|---|---|---|---|
| R-B3 k = 5 primary | tune | 16.74% [14.13, 19.74] | 12.05% [10.16, 14.45] | 4.54% of 209,331 (was 0.70%, 1.76%) |
| R-B3 k = 5 primary | report | 2.25% [1.90, 2.74] | 2.46% [2.18, 2.86] | 14.07% of 20,750 |
| R-B1 ttl 1 day | report | not computed (fees only) | 1.37% [1.26, 1.49] | mean agreement 0.985 |
| R-B2 k <= 1 | report | 3.41% | 4.10% | no interval computed |

Unpriced R-B3 incumbents: 0.1% of tune LLM rows (was 57.3%). R-B1/R-B2 tune: `as_logged` unchanged; repriced slices now in price-file units. On the report split R-B3 is below R-A3 `route.per_bot` (`todays_models` 6.28% [5.03, 7.49]) outside the interval in every baseline: it does not pass "beat per-bot reassignment outside the CI". No winner picked (I-1/I-2). Overhead p95: R-B1 7.5 ms, R-B2 8.8–9.8 ms (pass); R-B3 422–516 ms (fail, 100 ms target).

### For Pipeline C (D-2)
- The repriced-slice units are fixed (ADR-0050 finding): `rb1.*` and `rb2.*` repriced results now carry only price-file figures in every slice (`price_file_slices`); recorded fee figures appear only under `as_logged`. R-B3 follows R-A3's per-baseline slices.

### Open
- `as_logged` grouping in `compare`: B's R-B1/R-B2 `as_logged` results record `prices-metis-…-logged` (they use no price file), A's and C's record `full-eda-implied-unit-rates`, so they sit in different groups. A team convention for the price version of a recorded-only result is needed; B was not relabelled.
- R-C3's report results have 73,062 requests (A and B: 73,063), so they form their own group (C's scope).
- R-B3 overhead: build training-side indexes at fit time. Q-B4, Q-B20, Q-B22 open.
