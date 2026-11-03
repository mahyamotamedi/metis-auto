# Pipeline B: interim contracts (sprint Day 1)

Status: **interim**, 2026-11-02. At the end of Day 1, `analysis/lever_result.py` and `analysis/levers.py` reached `origin/main`. **Update 2026-11-02:** this branch has merged `main` at `e974c48`, so the S-3 files (`replay_scope.py`, `baselines_full.py`, `sprint.toml`) are here too; Q-B7 to Q-B9 are answered below. The S-1 loader switch-over (checklist items 1 to 4, 6) is still open. Pipeline B's Day 1 code (S-2 comparison, S-5 cache guard, T-3 Postgres event sink) was written before the shared sprint files existed on `origin/main`. B's code depends on **shapes, not files**: each module declares a `typing.Protocol` for what it reads, tests use test-local fakes, and the real classes must satisfy the protocols with no change to B's code. This page lists every assumed shape, the file that will replace each stand-in, the switch-over checklist, and the questions the owners must confirm. Source plan: [`docs/2026-11-01-final-plan.md`](../2026-11-01-final-plan.md) ("Shared interfaces"). **Update 2026-11-03:** the Day 3 notes are folded in below (main is merged); the last stand-ins (interim `LeverResult` loader, interim R-B3 eligibility) are retired.

## Shared files: where they stand

| File (owner) | On `origin/main` | Elsewhere | B's stand-in |
|---|---|---|---|
| `analysis/lever_result.py` (S-1, A) | **yes**, since `b3fdaae` ("Sprint saba (#11)"), seen at the end of Day 1, 2026-11-02; identical to the checked `sprint-saba` code | — | `LeverResultLike` protocol in `analysis/compare.py`; JSON loader `wiring/_interim_lever_json.py` **retired 2026-11-03**: `wiring/lever_compare.py` reads `LeverResult.model_validate` |
| `analysis/levers.py` (S-1, A) | **yes**, since `b3fdaae` | — | none needed (B does not read `StepVersion`, `ReplayContext` or `combine` on Day 1); `CacheGuard` satisfies its `CacheGuardLike` |
| `analysis/replay_scope.py`, `analysis/baselines_full.py` (S-3, C) | **available on main (cb7066e)**; split rule changed in `e974c48` (ADR-0036, report side keeps a straddling family) | — | baseline keys `BASELINES` in `analysis/compare.py` (the same four keys as `baselines_full.BASELINE_KEYS`, Q-B7) |
| `config/evaluation/sprint.toml` (S-3, C) | **available on main (cb7066e)** | — | none left: `CacheGuard.shadow_sample` takes `rate` (callers pass `[cache_guard] shadow_rate`); `compare` takes the required `max_tenant_share` (`scripts/compare_levers.py` passes `[sample] tenant_cap`); `compare.MAX_TENANT_SHARE` removed |
| `analysis/routing_base.py` (R-0, Parham) | **yes**, since #35/ADR-0045 (2026-11-03) | — | not used on Day 1; R-B3's interim eligibility retired 2026-11-03 (Day 3 below) |

**Checked against the real file.** The `LeverResult` on `origin/sprint-saba` was exported to a scratch folder (`git archive`, nothing merged) on 2026-11-02. A real `LeverResult` was fed to `compare()` unchanged, and its `to_json()` output was read by the interim loader. Both gave the same ranks, savings and flags. The protocol fits that version. Re-check when it lands on `main`.

## S-2: the `LeverResult` fields `compare` reads

`analysis/compare.py` declares `LeverResultLike` (read-only properties) and `ManifestLike`:

| Field | Assumed type | Used for |
|---|---|---|
| `lever_id`, `step`, `version` | `str` | row identity; ranking stays within one `step` |
| `n_requests`, `n_eligible` | `int` | "`n_eligible` of `n_requests`"; `n_requests` is part of the data scope; `n_eligible <= 0` is insufficient evidence |
| `baseline` | `str`, one of the four keys below | one table per baseline |
| `baseline_cost`, `saving` | `Mapping[str, Decimal]` | the total is `"total"` if present, else the exact sum of the blocks; non-finite means unknown; a float is refused |
| `ci_low`, `ci_high` | `float \| None` | shown as the interval; missing or NaN means insufficient evidence |
| `slices` | `Mapping[str, Mapping[str, Decimal]]` | `llm_only` and `traffic_weighted`: key `"saving_share"`; `tenant_rank:<n>`: key `"share"` |
| `evidence_class`, `correctness_state` | `str` | grouping; displayed state (`unmeasured`, `sampled:<n>`, `measured`; anything else is "unknown") |
| `assumptions` | `Sequence[str]` | joined with `; ` |
| `overhead_ms_p50`, `overhead_ms_p95` | `float \| None` | "not measured" when both are `None` |
| `manifest.price_version`, `manifest.data_revision` | `str` | grouping: results with different price versions or data revisions are never ranked together |
| `min_n` (optional, not in the plan) | `int \| None` | read with `getattr` if a result carries it; `n_eligible < min_n` is insufficient evidence |

Baseline keys (`compare.BASELINES`, interim): `premium_gpt_5_5` (estimate only, repriced), `as_logged` (recorded cost units), `todays_models` (repriced), `best_single_cheap` (repriced).

JSON loader (retired 2026-11-03, now `LeverResult.model_validate`): `wiring/_interim_lever_json.result_from_json` read money only from decimal strings or integers. The `sprint-saba` `LeverResult.to_json` prints money as fixed-notation strings, so the two agree.

## S-5: cache guard

`analysis/cache_guard.py` implements the plan's frozen `CacheGuard` contract exactly. It depends on no shared file. Interim parts:
- `shadow_sample(keys, rate, seed)` has **no default rate**. The plan's 1% default is `[cache_guard] shadow_rate = 0.01` in `config/evaluation/sprint.toml` (on main since `cb7066e`, Q-B9). Callers (a cache version's script or wiring) read it there and pass it in. The guard's signature does not change.
- The key encoding (`<key_version>|<digest>`) is defined in the module docstring. Cache versions (R-A1, R-B1, R-C1) build keys with `versioned_key(key_version, body)`; the body comes from text normalised by `analysis/text_features.normalize_safe` (the caller's job, the guard only sees strings).
- Addition to the frozen contract, pending approval: `refusal(key, bot) -> str | None` returns the first failing check (`disabled_bot`, `blocked`, `not_approved`, `key_version`), so the check order is testable and the D-2 cache monitor can count guard blocks by reason. `allows` is `refusal(...) is None`. The fields and the `allows` / `shadow_sample` signatures are exactly the plan's.
- `shadow_sample` selects **per key** (every row of a selected key is selected), so the rate is about the share of distinct keys. It equals the row share when keys are unique. Missing keys are never selected.

## T-3: Postgres event sink

Layout decided in [ADR-0033](../adr/0033-postgres-event-sink-layout.md). It depends on no teammate file. Interim or provisional parts:
- `exp.lever_results` (Alembic revision `0007`) is **provisional**. Its columns are the content-free plan fields, with the manifest flattened. When the shared `LeverResult` lands, compare its fields and privacy classes with the table and add a revision for any difference. No writer exists yet.
- Marker and extra: the plan's `services` marker and extra (T-0, Parham) do not exist. The live test uses the existing `postgres` marker (`--run-postgres`) and the `db` extra, which already pins `psycopg[binary]`. **Patch for T-0** (not applied here; `pyproject.toml` and the locks are Parham's): if a `services` marker is added, mark `tests/integration/test_postgres_sink_live.py` with it too, and drop `psycopg[binary]` from the planned `services` extra or keep it equal to the `db` pin.
- The plan's `test_psycopg_imported_only_in_postgres_sink` conflicts with `tests/architecture/test_db_imports.py`. The sink imports no database library, and psycopg is imported only in `data_access/postgres/event_store.py`.

## Version identity in `compare` (2026-11-02)

`compare` identifies a version by **`(step, version)`**, the same across baselines. `lever_id` names one result file (ADR-0032) and may carry a baseline suffix, as Pipeline B's do since the S-3 switch-over (`rb2.cross-turn.k-1.ptr-8.pointer.best_single_cheap`). Before this, `compare` keyed by `(step, lever_id, version)`, so the 48 Day 2 files gave 152 spurious "baseline missing" rows. Now:
- a version missing under the chosen baseline gets **one** "baseline missing" row, with a blank `lever_id` and the baselines it does have in `notes`;
- two results with the same `(step, version)` under one baseline both get status `duplicate version`, no rank, and each other's `lever_id` in `notes` (never merged).

**Who depends on it:** every pipeline whose results go to `reports/levers/` and through `scripts/compare_levers.py` (A: R-A*, C: R-C*, and the plan's final `comparison.md`). Each `version` label must be unique within a step for each baseline. `wiring/lever_view.py` (C) only sorts by `lever_id` and filters by baseline, so it is not affected.

## Switch-over checklist

When `analysis/lever_result.py` is on `main` (items 2, 3 and 6 **done 2026-11-03**):
1. Confirm the questions below with its owner.
2. ~~In `wiring/lever_compare.py`, replace `result_from_json(data)` with `LeverResult.model_validate(data)` and `is_result` with a validation attempt (catching `pydantic.ValidationError`). Delete `wiring/_interim_lever_json.py` and its `module_reference.md` row, and drop the "interim" note from the Markdown.~~ Done 2026-11-03. A float amount is no longer refused by the loader: the shared model converts it to an exact `Decimal` (`0.1` → `Decimal('0.1')`).
3. Optionally annotate `compare(results: Sequence[LeverResult], ...)`. Keep the protocol if `analysis.compare` should not import `analysis.lever_result` (both are in `analysis`, so the import is allowed). **Decided 2026-11-03:** the protocol stays (`compare` keeps no import of `lever_result`); `collect` returns real `LeverResult` objects, which satisfy it.
4. If the baseline keys from `analysis/baselines_full.py` differ, change `compare.BASELINES` keys only (labels stay).
5. ~~Move the 0.35 tenant limit to `sprint.toml` if C puts it there.~~ Done 2026-11-02: `compare(..., max_tenant_share=...)` is required; `scripts/compare_levers.py` reads `[sample] tenant_cap` (`--sprint-config`).
6. ~~Re-run `tests/unit/analysis/test_compare.py` and `tests/unit/wiring/test_lever_compare.py`. Their fakes must still pass. Add one test with a real `LeverResult`.~~ Done 2026-11-03: both pass; `test_collect_returns_the_shared_lever_result` added.

`config/evaluation/sprint.toml` is available on main (cb7066e):
7. The caller of `CacheGuard.shadow_sample` reads the shadow rate from it. No change to `cache_guard.py`.

## Questions for the owners

For **S-1 (`LeverResult`, A; seen on `sprint-saba`)**:
- Q-B1. `saving` and `baseline_cost`: are the keys cost blocks only, or is there a `"total"` key? `compare` uses `"total"` if present, else the exact sum of the blocks. `sprint-saba`'s `levers.py` has `BLOCKS = ("fees", "token_cost")` and no total, which `compare` handles with the block sum.
- Q-B2. Slice inner keys: is the saving share under `"saving_share"` and a tenant's share under `"share"`? `sprint-saba` requires slices `all` and `llm_only`, but the plan's list has no `all` and adds `traffic_weighted`. `compare` shows `llm_only` and `traffic_weighted` and takes all-traffic from the top-level saving.
- Q-B3. `baseline_cost` is described as "recorded units" on `sprint-saba`, but three of the four baselines are repriced. Please describe it as "units of the baseline" or add a unit field.
- Q-B4. `evidence_class` on `sprint-saba` is a closed list without "measured potential", the label R-B1 needs (plan, R-B1). Add it?
- Q-B5. Where does a result's own minimum sample size live? `LeverResult` has no `min_n`. `compare` reads an optional `min_n` attribute.
- Q-B6. ~~ADR number collision~~ resolved: `sprint-saba` renumbered its ADRs to 0031 (full-data replay) and 0032 (lever result format). Pipeline B therefore uses 0033 and 0034.

For **S-3 (C)**:
- Q-B7. The four baseline keys returned by `baseline_costs` (B assumed the keys above). **Answered** (Saba, Pipeline C, 2026-11-02): the four keys are adopted unchanged (`premium_gpt_5_5`, `as_logged`, `todays_models`, `best_single_cheap`, `baselines_full.BASELINE_KEYS`). Each baseline has `total` (which `compare` reads first) plus the counts `n_requests`, `n_known`, `n_unknown`; only the cost keys go into `LeverResult.baseline_cost`. The repriced baselines have no `fees` key (ADR-0036, decisions 5 and 7).
- Q-B8. The cost-block column names. The plan lists fees, input, output, cached and other, while `sprint-saba` uses `block_fees` and `block_token_cost`. `requests.parquet` has no per-block cost columns, only `a_bill_totalCost`, the token sums and `a_n_per_call_only_items`. Which split is final, and does "other" (F-2) get its own block? **Answered** (Saba, Pipeline C, 2026-11-02): two blocks only, `fees` and `token_cost` (columns `block_fees`, `block_token_cost` from `levers.with_blocks`). F-2's "other" has no block of its own and is reported inside `token_cost` (owner decision 3, 2026-11-02).
- Q-B9. Does `sprint.toml` hold the shadow-check rate (plan: 1%) and the 0.35 tenant limit? Under which keys? **Answered** (Saba, Pipeline C, 2026-11-02): yes, `[cache_guard] shadow_rate = 0.01` and `[sample] tenant_cap = 0.35` in `config/evaluation/sprint.toml`. B switched `compare` to the cap the same day.

For **T-0 (Parham)**:
- Q-B10. The `services` marker and extra vs the existing `postgres` marker and `db` extra (see T-3 above).
- Q-B11. The plan's `test_psycopg_imported_only_in_postgres_sink` vs `test_db_imports.py`. B kept the existing rule.

For **the team**:
- Q-B12. Approve the `CacheGuard.refusal` addition ([ADR-0034](../adr/0034-cache-guard-key-encoding-and-check-order.md)), or B removes it and tests the order another way.
- Q-B13. `[events] sink = "postgres"` writes Postgres **in addition to** the JSON Lines file (ADR-0033). Is that the intended meaning of the switch?

## Day 2 (2026-11-02): R-B1, R-B2, F-2

**Shared files at Day 2.** `analysis/levers.py` (blob `896092d`) and `analysis/lever_result.py` (blob `dfca79e`) are on `origin/main`; this branch has not merged `main` (owner rule). They were **borrowed** as untracked, git-excluded copies only to run tests against the real `combine`, `StepVersion`, `summarise_slices`, `LeverResult` and `build_manifest`, and **deleted before handing over**. No B code depends on them at import time: the contract tests use `pytest.importorskip`, and the run helpers import them lazily. `analysis/replay_scope.py`, `analysis/baselines_full.py`, `config/evaluation/sprint.toml`, `analysis/routing_base.py` and S-6 (`experiments/context/exp-ctx-001-within-message-dedup/`) exist on no ref.

**Stand-in (retired 2026-11-02):** `experiments/caching/exp-cache-002-retrieval-result-cache/_interim.py` and its test are deleted. R-B1, R-B2 and F-2 now use `analysis/replay_scope.py`, `analysis/baselines_full.py` and `config/evaluation/sprint.toml` from `main` (cb7066e, split rule e974c48, ADR-0036). Results are written to `reports/levers/<lever_id>.json`, one per version per baseline; the old `reports/<area>/exp-*-002/levers/` files are removed and the `summary.json` files stay where they were. The table below is kept as the record of what the stand-in assumed.

| Interim piece | Assumed shape | Replaced by |
|---|---|---|
| `llm_request(req)` | nullable bool; False for `bot_provider_name == "workflow"` (103,561 rows, 29.7%); `<NA>` if unknown | `analysis/replay_scope.py` (S-3) |
| `assign_periods(req)` | `period` in `tune` / `report` / `outside` by the session's first request time (user time, else answer time); `family_leak` for report rows whose `u_h_norm` family first appeared in tune | `analysis/replay_scope.py` |
| `PERIODS` | tune 2026-03-01..07-31, report 2026-08-01..10-31, naive | `config/evaluation/sprint.toml` |
| baselines | only `as_logged` (recorded units); `premium_gpt_5_5`, `todays_models`, `best_single_cheap` not computed (need repricing) | `analysis/baselines_full.py` |
| shadow rate | 0.01 passed by the script | `sprint.toml` |

**Switch-over checklist (Day 2 code): done 2026-11-02.**
1. ~~Merge `main`.~~ Done (via the Day 1 branch). The contract tests in `tests/unit/experiments` run for real (no skips).
2. ~~Replace `_interim.llm_request` / `assign_periods` with `replay_scope`.~~ Done: `scope` (per-row `period` from `a_timestamp`; a missing provider is an error) and `split_by_session` (R-B1's fitting split). `_interim.py` and its row deleted.
3. ~~Build all four baselines from `baselines_full`.~~ Done. R-B1 against the repriced baselines: saving **not computed** (empty `saving`, never 0; ADR-0036 decision 5). R-B2: before-minus-after `baseline_costs` per repriced baseline.
4. ~~Read the shadow rate from `sprint.toml`.~~ Done, with every other setting (periods, seed, `min_n`, `[baselines]`).
5. ~~Re-run and move the `LeverResult` files to `reports/levers/`.~~ Done; results regenerated on a committed `code_commit`.

### Proposals for the S-1 contract (A); not applied, nothing edited
- **P-B1 (retrieval cache, plan §4.1).** A retrieval cache lowers only `block_fees`, leaves `served_from_cache` false, and adds `retrieval_reused`, `retrieval_lookups_skipped`, `retrieval_fee_avoided`. Today's `combine` already carries these columns (tested against the real one). Please change the `StepVersion` docstring from "cache versions … zero every cost block" to "answer-cache versions …; retrieval-cache versions lower only the fee block". [ADR-0037](../adr/0037-retrieval-result-cache-accounting.md).
- **P-B2 (fee block source).** `with_blocks` uses 0.002 × per-call items (35.8% vs 37.6% recorded). Let it take the recorded `costBreakdown.per_call` sum when available. R-B1 does this in its own run helper (`run.fee_blocks`), so fee avoided and the fee block share one source.
- **P-B3 (context columns).** The plan says context versions lower `input_tokens`. The frame has `a_bill_inputTokens` (raw, cached-token convention differs by model). R-B2 writes `input_tokens_ordinary` (input), `input_tokens_after` and `ctx_*`, and lowers only `block_token_cost`. Please name the shared column.
- **P-B4 (an "other" block).** F-2: 11.71% of recorded cost (all periods; 16.3% of tune) has no input/output/fee split. Almost all of it is March 2026 items logged without `costBreakdown`. `BLOCKS = ("fees", "token_cost")` folds it into `token_cost`. Please add an `other` block, or a slice that states how much of `token_cost` is unbroken, so no saving is stated against a total that hides it.

### Questions for the owners (Day 2)
- Q-B4 (open): `evidence_class` has no "measured potential". R-B1 uses `simulation`, with "measured potential, conditional on Metis-Auto being able to intercept retrieval" in `assumptions`.
- Q-B8 (**answered** 2026-11-02, see the S-3 questions above): two blocks; "other" is reported inside `token_cost` (owner decision 3). P-B4 is therefore declined; F-2's breakdown is the reference for the share of `token_cost` that is "other".
- Q-B14 (A): confirm P-B1. Until then the combined run with R-B1 is **blocked** in the shared waterfall. R-B1's standalone fee accounting stays valid.
- Q-B15 (A): where do a result's cache-specific aggregates go? R-B1 puts lookups, hits, guard blocks, agreement and shadow counts in a `retrieval` slice. R-B2 puts tokens in a `context_tokens` slice. `LeverResult` has no field for them.
- Q-B16 (A, C): `traffic_weighted` for a full, unsampled replay. B copies `all`. Is that the intended meaning?
- Q-B17 (C): the shadow-check source. Offline, the "later real lookup" of a reused lookup is the logged lookup itself. Is that acceptable for the D-2 monitor, or should the shadow check use the next logged lookup of the same key?
- Q-B18 (C, S-6): within-message duplicates. R-B2 counts only the first occurrence of `(chunk_id, hash)` per request and leaves copies to S-6. Please report S-6 savings per request with the same rule, so the two never double count.
- Q-B19 (Metis, via O-1): 34,569 of 91,807 tune RAG lookups sit in messages with **no per-call billing item**: almost all of March, part of April and May, and every RAG message in October. Is retrieval sometimes free, billed elsewhere, or missing from the log?

## Day 3 (2026-11-02): R-B3, T-1, I-1

Folded in from `pipeline_b_interim_contracts_day3.md` on 2026-11-03 (that file is now a pointer here). Text as written on Day 3; status notes in **bold** are 2026-11-03.

**Shared files at Day 3** (every remote ref after `git fetch`, 2026-11-02): `analysis/routing_base.py` (R-0, Parham), the `services` extra, lock and pytest marker (T-0), a Redis service in `compose.yaml` (T-4), `experiments/pipelines/sprint-final.toml` and `docs/experiments/sprint_decisions.md` exist on **no ref**. R-A1 (`exp-cache-003`) is on `main` since `c17f184`. **Later the same day:** `main` reached `f44d84f` with S-6/S-6b (#22, `baselines_full` row helpers, ADR-0038) and R-A2 + L-1 (#23, `scripts/measure_lever_overhead.py`); this branch has not merged them (owner rule). `baselines_full` row-level helpers (`token_counts`, `lower_uncached_input`, `repriced_row_costs`): on `main` since #22.

### Stand-ins (B's experiment folders only): **both retired 2026-11-03**

| Stand-in | Shape | Replaced by | Switch-over |
|---|---|---|---|
| `experiments/routing/exp-route-011-knn-router/eligibility_interim.py` (`interim_eligible_models`, `LABEL`) | `(row, catalogue, prices, rules) -> tuple[str, ...]`, the plan's R-0 shape; `row` carries `input_tokens` (effective), `output_tokens`, `u_att_n`, `bot_n_functions`, `bot_provider_model`; `rules` carries `candidates` and `retiring` | `analysis.routing_base.eligible_models` (R-0) | **Done 2026-11-03** (`scripts/run_pipeline_b_day3.py` `_factory`, rules `sprint.toml [routing]`; file, test and row deleted; `rb3` re-run). 1. Confirm the row keys and the `rules` shape with Parham. 2. Inject the real function in `scripts/run_pipeline_b_day3.py` (`_factory`). 3. Drop `LABEL` from the assumptions, delete the file and its `module_reference.md` row. 4. Re-run `rb3`. |
| `version.candidate_costs` (per-row cost of a model, the public `baselines_full` pricing rule; sums tested equal to `baseline_costs`) | `(req, models, ctx, cached_separately) -> DataFrame` | `baselines_full.repriced_row_costs` / `token_counts` (S-6b, Pipeline C), on `main` since #22 | **Done 2026-11-03**: `baselines_full.model_row_costs` / `token_counts` (`routing_base.candidate_costs` not used: it blanks ineligible costs and refuses the incumbent, which the router needs). Replace the body with the shared helper; keep the test that sums match `baseline_costs`. |

No stand-in is under `src/` or in a teammate's file. Every R-B3 result said "interim eligibility, not the shared routing base" and had to stay out of any final comparison until step 4. **Since 2026-11-03 R-B3 runs on the routing base (ADR-0045) and the label is gone.**

### T-1: `[cache] store` and the `services` patch (not applied; `pyproject.toml` and the locks are Parham's)

- **Setting added** (shared files, smallest change): `settings/model.py` `CacheStoreSettings` and `Settings.cache` (`store = "memory" | "redis"`, `redis_host`, `redis_port`, `redis_db`, `redis_namespace`), `"cache"` added to `HASH_EXCLUDED_SECTIONS`; `wiring/from_settings.cache_store`; `wiring/chat.py` builds its store with it once per session. Default `"memory"`: same store, same config hash (tested). `config/defaults.toml` is not edited: like `[events] sink`, the default lives in the model. The password comes only from `METIS_REDIS_PASSWORD` in the process environment.
- **Patch for T-0:** add `redis` (version at lock time under `constraints-min-age.txt`) to the `services` extra and `requirements-services.lock`; register the marker `services: real-server tests (Redis, Postgres, MLflow), opt-in`; put `pytestmark = pytest.mark.services` in `tests/integration/test_redis_store_live.py` (today it skips unless `redis` imports and the server answers); `test_redis_imported_only_in_redis_store` holds already (the only `import redis` is inside `redis_store.redis_client`).
- **Patch for T-4:** a `redis` service in `compose.yaml`, port bound to `127.0.0.1:6379`, with a health check (`redis-cli ping`), in the `services` profile; the demo then sets `[cache] store = "redis"` in `config/local.toml`.

### I-1 (B-only dry run): findings for the `combine` owner (Pipeline A)

- **Q-B20 (routing after context; open).** `combine` hands routing the frame context returned. R-B2 lowers `block_token_cost` and adds `ctx_tokens_saved` / `input_tokens_after`, but leaves `a_bill_inputTokens` as logged, so a routing version that reprices from `a_bill_inputTokens` prices the pre-context tokens: the context saving vanishes from the combined repriced figure (`combined_today.*` in the dry run). The dry run's stated assumption is `PostContextRouting` (input lowered by R-B2's net tokens, R-B2's cached-token floor). Please decide the shared column a context version lowers (P-B3) so routing reads it.
- **Q-B21 (one definition of a repriced saving). Answered for Pipeline B 2026-11-03 (owner, Kimia): ADR-0046 point 6, incumbent per baseline, as R-C3 (ADR-0046) and R-A3 (ADR-0051); R-B3 also takes points 4 and 5 (ADR-0048 Amendment 1). I-2 still needs the team-wide confirmation that ADR-0046 and ADR-0051 ask for.** Earlier on 2026-11-03 R-B3 kept "baseline minus routed cost" while this was open; that definition is retired. R-B2 (Day 2) reports, per repriced baseline, the baseline re-priced before minus after (the effect priced at the baseline's model). R-B3 reports baseline cost minus the pipeline's routed cost (the prompt's `todays_models` method), which includes the baseline's own difference from today's models. Both are valid alone, but a waterfall that adds them double counts that difference. The dry run uses one definition (baseline minus pipeline cost) and checks the sum rule on the increment over today's models. Please fix one definition for I-2.
- **Q-B22 (two cache versions; open).** `combine` takes one cache version. R-A1 (answer cache: `served_from_cache = True`, known blocks zeroed, `pq_*` columns; `exp-cache-003` on `main`) and R-B1 (retrieval cache: `served_from_cache` stays false, only `block_fees` lowered, `retrieval_*` columns) target different blocks and their columns do not collide, so the representations do not conflict. Running both needs either two cache slots or a composite cache version, applied answer cache first (a served row then has no lookup to skip).
- **No `LeverResult` for a combined pipeline:** `LeverResult.step` is one of cache, context, routing, so the dry run writes a content-free summary instead (`reports/pipelines/b-only-dry-run/summary.json`). I-2's `final.json` needs a shape for it.
- **Q-B23 (`compare` and interim results). Answered 2026-11-03: no interim flag is needed; R-B3 uses R-0 (ADR-0045) and no B result is interim any more. The ranking point below stays (the declared default `k` is in `assumptions`).** `compare` ranks within a step and baseline by evidence class; nothing marks R-B3's interim eligibility. Until R-0 lands, R-B3 must not be ranked against R-A3 / R-C3 in a final comparison. Add an `interim` flag, or the team leaves R-B3 out. Also: `compare` ranks the three R-B3 grid points by saving (k = 50 first on the full run), which is exactly the ranking R-B3's declared criterion refuses without quality labels; the declared default (k = 5) is in each result's `assumptions` and in `reports/routing/exp-route-011/summary.json`, not in a field `compare` reads.
- **Q-B24 (L-1 script, Pipeline A). Answered 2026-11-03: B measures its own overhead with `scripts/measure_pipeline_b_overhead.py` (tune period, tenant cap, B targets), [ADR-XXXX (pipeline-b-lever-overhead)](../adr/draft-pipeline-b-lever-overhead.md); A's script is unchanged.** `scripts/measure_lever_overhead.py` (on `main`, #23, blob 3a766bc) was borrowed read-only and dry-run on `rb1.retrieval-cache.ttl-1d.user.tune.as_logged`, `rb2.cross-turn.k-0.ptr-8.pointer.as_logged` and `rb3.knn-router.k-5.tune.todays_models`: each stops at `target_for` ("no known version"), before any data is read. To time B's versions it needs (a) a `Target` per B family (R-B1 needs its lookups frame, R-B2 its chunks frame, R-B3 a fitted router: all built by `scripts/run_pipeline_b_day2.py` / `run_pipeline_b_day3.py` helpers), and (b) a period option: it samples report-period rows (`sample_rows`), while the plan reads the report period once at the end; a tune-period sample would serve the offline estimate. The prompt's "tenant cap applied" is not in `sample_rows` either. Until then B's overhead is "not measured", never 0. The copy was deleted.
