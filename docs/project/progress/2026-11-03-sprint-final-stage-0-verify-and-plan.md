## Sprint final, Stage 0: verify the done/left tables, lever-result gaps, plan for Stages 1–6 (2026-11-03)

Branch `sprint-final-pipelines` (from `main` 589c0d0). Stage 0 of the "finish the four pipelines" task: no code, no data run, no model call, no spend. Traces: plan I-1, I-2, N-1, E-3, E-5, F-1, T-0…T-4, J-3 (remapped); QA-REPRO, QA-PRIV.

### Differences from the task's "done" table (checked 2026-11-03)

1. `main` is at 589c0d0, two commits past 80669eb: #47 (despite its title "Sprint final i1 n1") holds only ADR-0018 Amendment 3 (ceiling and lifetime cap 92 USD); #48 is UI Stage 4 (ADR-0056). No I-1 or N-1 work exists.
2. The budget amendment for the paid quality run already exists (ADR-0018 Amendment 3, 92 USD). Gate 2 (Metis permission, Q-55), Q-62…Q-64 and per-run approval are still open.
3. **Units** (B dry-run README, updated after ADR-0048 Amendment 1): `as_logged` now combines cache + context + routing (routing is priced at implied recorded rates). Price-file baselines combine context + routing, and also an answer cache: `cache.popular_question.*` has a `token_cost` saving in price-file units. Only the retrieval caches (R-B1, session memo) have no saving there (ADR-0037 item 7, ADR-0039 item 2).
4. **Routing after context:** with each step's own effect per baseline (Q-B21), `combine` as it is today *overstates* the combined saving by the context∩routing overlap (routing saves on pre-context tokens), rather than losing the context saving. `PostContextRouting` is still needed.
5. **Populations differ:** popular question and `rc-v1 observed_relevancy` cover 77,774 requests (report *period*), the B and C results 73,063 (report *split*), the small classifier 73,062, `rc-v1 lexical_overlap` a 2,000-request sample. A combined run needs one population.
6. **Every primary routing saving goes to `gpt-4.1-nano`** (ADR-0046, ADR-0051), which Metis no longer serves (HTTP 404, ADR-0053 point 2). The replay catalogue still lists it as enabled (TODO-17 not applied there).
7. Lever-id conventions differ: A puts the baseline only in the file name (`.<baseline>.json` or `__<baseline>.json`), B and C put it in `lever_id`.
8. `reports/levers/pipeline_b_overhead.json` is not a `LeverResult` but matches `reports/levers/*.json`; `compare_levers.py` says it skips non-results (to confirm in Stage 1).
9. This machine has no `data/derived/routing/turn_intent_flags.parquet`, so C's `strict` modes can't be re-run here until `scripts/derive_turn_intent_flags.py` runs locally.
10. No `docs/adr/draft-*.md` exists.

### Gaps per version (165 `LeverResult` files; three CSVs and the B overhead summary aside)

| Step | Version (files) | Split | Interval | Overhead | Missing slices |
|---|---|---|---|---|---|
| cache | `pq-v1`, `pq-v2` × first_turn/all_turns (16) | report period | `as_logged` only ("no interval computed" on repriced) | yes | `traffic_weighted` |
| cache | `retrieval_result_cache.ttl_*` (20) | tune; `ttl_1d` report | `as_logged` only (repriced saving empty by design) | yes | `lang:*`, `over_8k` |
| cache | `cache.session_memo_gate` (4) | report split, threshold from tune | `as_logged` only (repriced saving empty by design) | **no** | `lang:*`, `over_8k`, `tenant_rank:*`, `traffic_weighted` |
| context | `rc-v1` × 2 scorers (8) | report period | yes | yes | `lang:*`, `over_8k`, `tenant_rank:*`, `traffic_weighted` |
| context | `cross_turn_chunks.*` (40) | tune; `k0`, `k1` report | **no** | yes | `lang:*`, `over_8k`, `tenant_rank:*` |
| context | `ctx.history_budget.*` (16) | report split | **no** | **no** | `lang:*`, `tenant_rank:*`, `traffic_weighted` |
| context | `ctx.within_message_dedup` (4) | report split | **no** | **no** | `lang:*`, `over_8k`, `tenant_rank:*`, `traffic_weighted` |
| routing | `route.per_bot.v2` (+ reasoning) (8) | report split | yes | yes | none |
| routing | `route.knn.*` (24) | tune; `k5` report | yes | yes | none |
| routing | `route.small_classifier.*` × 4 modes (16) | report split | yes | **no** | `lang:*` |
| routing | decision router | — | — | — | no full-data result |

Every result has `correctness_state` `unmeasured`, except `pq-v1 first_turn` (`sampled:30`).

### Plan (Stages 1–6, priority order; cut from the bottom)

1. **Comparable:** in each version's own runner, add the missing intervals (`cluster_bootstrap_ratio`), the missing slices (or say in `assumptions` why a slice can't be computed), and the missing overhead (L-1 targets for the session memo, history budget, dedup and small classifier). Re-run only the changed versions on their own split with unchanged settings. Then run `compare_levers.py` and report the counts.
2. **Parham:** `scripts/decision_router_levers.py`. Rules-only tiers (`router.mode = "off"`) from a local, content-free features table, fed into `DecisionRouterRouting` on R-0. Tune first, then one report run. L-1 overhead. Tests fail first.
3. **N-1:** `docs/experiments/sprint_decisions.md`: the decision rules applied literally, provisional winners, runners-up, and "Quality evaluation plan (not run)". Stop for the owner.
4. **I-1:** combine draft ADR, `ChainedContext` if needed, `experiments/pipelines/sprint-final/`, `sprint-final.toml`, `scripts/run_sprint_final.py`, `reports/pipelines/sprint-final/summary.json`. Ask first about `PostContextRouting`.
5. **I-2:** `reports/levers/final.json`, `test_reports_content_free.py`, dashboard check.
6. **Engineering:** E-3, E-5, F-1, then T-0/T-2/T-4 (the `pyproject.toml` diff is shown before any lock is written).

### Owner decision (2026-11-03)

- **Population for the combined run (I-1, I-2):** the report split, 73,063 requests (`split_by_session == "report"`). Results scored on the report period (popular question, `rc-v1`) are applied in I-1 to report-split rows only. A cache's history may still look back into the tune period (ADR-0036 decision 1).
- **`gpt-4.1-nano`:** drop it from the routing candidates and re-run the routing versions (R-A3, R-B3, R-C3, the decision router). The change to `sprint.toml` (a shared file) waits for the owner's approval of the diff. The re-runs change a setting, so their report-split read is a second look on that split; each result and the decisions doc say so.
- **Stage 2 features:** a local, in-memory pass over user text writes a git-ignored, content-free features table (as `turn_intent_flags`); nothing leaves the machine (ADR-0047 point 5).
- **Stage 5 dashboard:** `wiring/lever_view.py` (Pipeline C) may be edited to read `final.json`, with its D-2 tests and an ADR-0050 amendment draft.

Stopped for review after Stage 0.
