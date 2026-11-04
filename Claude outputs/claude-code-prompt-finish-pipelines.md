# Prompt for Claude Code: finish the four pipelines and evaluate them together

You are working in the `metis-auto` repo on `main` (last commit `80669eb`, #46).

## Rule zero: no money is spent

**Do not spend any money in this task, not one cent.**
- Make no live, hosted or paid call of any kind: no answering models, no Jev or any other hosted router, no judges, no Gemini, no embedding or reranking API. That holds even though the project budget is now higher.
- Do not run `scripts/benchmark.py`, `scripts/live_*.py`, `scripts/router_live_check.py`, `scripts/demo_live_check.py`, `scripts/demo_ui_live_check.py`, or anything that writes to the spend ledger.
- Use fake and replay clients only. Do not change budget caps, approvals or `router.real_data_approved`.
- If a step looks like it needs a call, stop and tell me. Do not look for a way around it.
- Everything in this task is offline replay over local data.

## Read first

Read these before writing anything:
1. `CLAUDE.md` and `AGENTS.md`.
2. The sprint plan, `docs/2026-11-01-final-plan.md`.
3. **Every ADR in `docs/adr/`** (0001 to the newest, every amendment, and the `draft-*.md` files), plus `docs/adr/README.md`. They hold the decisions this work must follow: replay, units, pricing, accounting, routing, the router, privacy and budget. Pay particular attention to ADR-0018, ADR-0031 to ADR-0041, ADR-0045 to ADR-0049, ADR-0051 and ADR-0053.
4. `docs/project/assumptions_and_questions.md` and the newest entries in `docs/project/progress/`.

In Stage 0, list the ADRs that constrain each stage.

The repo docs win over anything in this prompt. In particular:

- **Git:** never commit, push or rewrite history. End each stage with the changed files and a suggested commit message.
- **New docs:** progress goes in a new file under `docs/project/progress/`, then run `python scripts/progress_index.py`. A new ADR is a draft, `docs/adr/draft-<slug>.md`; never pick an ADR number yourself.
- **Privacy:** never read `.env`. Nothing with text, IDs or hashes goes under `reports/`.
- **Shared files** (`analysis/levers.py`, `lever_result.py`, `compare.py`, `cache_guard.py`, `routing_base.py`, `replay_scope.py`, `config/evaluation/sprint.toml`): **do not edit**. Propose the change and stop for my approval.
- **Report split:** each version reads the report split (Aug–Oct 2026) once, with frozen settings. Never tune on it.
- **Stages:** work stage by stage. After each stage give the 6-part report (changes, decisions, assumptions, questions, next stage, exit criteria) and **stop**.

The code freeze is **Day 4 (2026-11-04) at 12:00**. Work in the priority order below. If time runs out, cut from the bottom.

---

## What is already done (verified 2026-11-03; re-check in Stage 0)

**Shared base:** S-1 (`levers.py`, `lever_result.py`, `combine`), S-2 (`compare.py`, `scripts/compare_levers.py`), S-3 (`replay_scope.py`, `baselines_full.py`, `sprint.toml`), S-4 (ADR-0031), S-5 (`cache_guard.py`), S-6 (within-message dedup), E-1 (CI), E-2 (manifest), R-0 (`routing_base.py`), D-1 (`wiring/lever_view.py`), D-2 (Results dashboard, UI stages 1–3), F-2 (cost trace), L-1 (`scripts/measure_lever_overhead.py` and B's own `measure_pipeline_b_overhead.py`), T-1 (Redis store), T-3 (Postgres sink), K-1 (30 reviewed popular-question hits).

**The four pipelines and their step versions** (each version has its `LeverResult` per baseline in `reports/levers/`, 168 files):

| Pipeline | Cache | Context | Routing |
|---|---|---|---|
| A | `exp-cache-003` popular question: `pq-v1`, `pq-v2` (24 h TTL); report split | `exp-ctx-003` reranker cut `rc-v1` (scorers `lexical_overlap`, `observed_relevancy`); report split | `exp-route-001` per-bot reassignment `route.per_bot.v2` (+ `with_reasoning_models`); report split |
| B | `exp-cache-002` retrieval-result cache: TTL 1/7/30/90 d on tune, `ttl_1d` on report | `exp-ctx-002` cross-turn chunks: 8 scenarios on tune, `ptr8.k0` and `ptr8.k1` on report | `exp-route-011` kNN `route.knn.k5` frozen; report split (k15 and k50 tune only) |
| C | `exp-cache-004` session memo + greeting gate; report split | `exp-ctx-004` history budget (`b2000`, `b4000`, `b8000`, `half_over_8k`) and S-6 `exp-ctx-001` within-message dedup | `exp-route-012` small classifier (`rules`, `strict`, `strict_unknown_blocked`, + `with_reasoning_models`) |
| Parham | — | — | `exp-route-013` decision router: step version and tests done, THX-01 shadow run on the 150-record dev slice (agreement 1.0 with the rules, p95 10.8 s, so inline = rules only), Jev synthetic check (72% tier accuracy on 100 synthetic requests). **No full-data `LeverResult`.** |

**B-only integration** exists: `experiments/pipelines/b-only-dry-run/` (`run.py` with `PostContextRouting`, `scripts/run_pipeline_b_day3.py i1`, `reports/pipelines/b-only-dry-run/summary.json`). Its README records two findings that apply to every pipeline:
- **Units:** `as_logged` (recorded units) can combine cache + context only. The price-file baselines can combine context + routing only. No three-step total exists in one unit.
- **Routing after context:** `combine` passes routing the frame context returned. Routing reprices from `a_bill_inputTokens`, so the context saving disappears. B wraps the router in `PostContextRouting` as a stated assumption.

**Paid benchmark** P-1 to P-3 (#42, ADR-0053): engineering only, nothing run. Owner values Q-62…Q-64 are unset and gate 2 (Metis permission) is missing. **Every routing result stays "quality not proven".** Do not run the benchmark: it costs money (Rule zero).

## What is left (from the plan)

| ID | Item | State |
|---|---|---|
| — | Gaps in existing `LeverResult`s (see Stage 1) | partial |
| S-2 output | `reports/levers/comparison.md` | never generated |
| J-3 (remapped) | decision router as a full-data routing result | missing |
| N-1 | `docs/experiments/sprint_decisions.md` (only `pipeline_b_decision_notes.md` exists) | missing |
| I-1 | `experiments/pipelines/sprint-final.toml` + a combine run for A, B, C, Parham and the winners | missing (B only) |
| I-2 | `reports/levers/final.json` + `tests/architecture/test_reports_content_free.py` | missing |
| E-3 | `tests/architecture/test_lever_traceability.py` | missing |
| E-5 | `scripts/engineering_scorecard.py` → `reports/engineering_scorecard.json` | missing |
| F-1 | free Gemini thinking check `experiments/cost/exp-cost-001-gemini-thinking/` (the Gemini adapter and live check exist; this offline log check does not) | missing |
| T-0 | `services` extra, `requirements-services.lock`, `services` marker, `tests/architecture/test_service_imports.py` | missing |
| T-2 | MLflow: `ports/tracking.py`, `adapters/tracking/mlflow_tracker.py`, `scripts/log_levers.py` | missing |
| T-4 | `compose.yaml`: `redis`, `mlflow`, `demo` services under a `services` profile, loopback ports, health checks, CI `docker compose config -q` | missing (only `app` and `postgres`/`db`) |
| E-4 | ADR drafts for: services extra + adapters, the I-1/I-2 combine and units rule, and any change to `combine` | missing |

---

## Stage 0: verify and plan (no code)

1. Re-check the two tables above against the repo: `git log`, the experiment READMEs, `reports/levers/*.json` and `docs/project/progress/`. Report any difference.
2. For every `LeverResult`, tabulate: step, version, split (from `lever_id`, assumptions, README), baselines present, `ci_low`/`ci_high`, `overhead_ms_p50/p95`, `correctness_state`, and slice keys. Gaps already seen, to confirm:
   - **No interval:** popular question, retrieval cache, session memo, cross-turn chunks, history budget, dedup.
   - **No overhead:** session memo, history budget, dedup, all small-classifier variants.
   - **Missing slices** (the plan requires `llm_only`, `traffic_weighted`, `lang:*`, `over_8k`, `tenant_rank:*`): dedup and `rc-v1` have only `all`/`llm_only`; session memo, history budget and cross-turn lack several.
3. Write the plan for Stages 1–6 as a short list and stop.

## Stage 1: make every candidate comparable

Fix gaps **in each version's own runner** (`scripts/*_levers.py`, `scripts/run_*.py`), never in shared files.
- **Overhead:** fill the missing fields with `scripts/measure_lever_overhead.py`. If it can't time a version (`target_for` has no entry), add one there, or show me why not.
- **Intervals:** add session-clustered intervals with `analysis/stats.cluster_bootstrap_ratio`, as the routing results do.
- **Slices:** add the missing ones where the data allows. Where a slice can't be computed, say so in `assumptions` rather than leaving it out silently.
- **Re-runs:** re-run only the versions you changed, on the split they already used. A report-split re-run with **unchanged settings** is not a second look. Say so in the progress entry.
- Then run `scripts/compare_levers.py reports/levers/*.json --out reports/levers/comparison.md`. Report counts: skipped, missing baselines, duplicates, tenant flags.

## Stage 2: Parham's pipeline on full data (rules-only decision router)

THX-01 can't run on ~300k requests (p95 10.8 s). Jev is a paid hosted call (Rule zero), and it may not see dataset text anyway (Q-53, Q-55). So:
- Produce a full-data routing result with the decision router in `router.mode = "off"`, i.e. the rules-only policy that is its inline mode (A-118). This mode calls nothing and costs nothing. Check that no hosted backend is configured before the run. Feed its tiers into `exp-route-013/version.py` (`DecisionRouterRouting`) on R-0.
- Write `LeverResult`s `route.decision_router.rules_only.<baseline>` per ADR-0046 points 4–6, as R-A3, R-B3 and R-C3 do. Use the tune split first, then one report run with frozen settings. Overhead goes through L-1.
- Assumptions must say: "quality not proven", "rules-only; THX-01 changed no decision on the dev slice", and "Jev 72% on 100 synthetic requests is not evidence on real traffic".
- New script: `scripts/decision_router_levers.py`. Tests go in `tests/unit/experiments/` and must fail first.

## Stage 3: pick winners (N-1)

Write `docs/experiments/sprint_decisions.md`: one block per step (cache, context, routing) with what was tried, what won and why, the evidence class and the open question. Apply the plan's **Decision rules** literally:
- **Retrieval caches** (B, C) need agreement ≥ 0.9.
- **Answer caches** (A) need error ≤ 1% over about 300 reviewed hits. With 30 reviewed, A stays a *candidate*.
- **Context** is "tokens only, quality not measured".
- **Routing:** without labels, no version can pass the acceptable-rate rule. Pick by cost only, state that, and keep a complex router only if it beats per-bot reassignment outside the interval.
- **Combining:** versions that target different cost blocks may be combined. Examples: B's retrieval cache saves fees and A's popular question saves whole answers. C's history budget and S-6 dedup save different tokens.

Put the candidates in a table with the winner marked.

**Winners are provisional, pending quality.**
- Label every winner in `sprint_decisions.md`, `sprint-final.toml` and later `final.json` as `provisional: cost only, pending quality`.
- Quality will be measured later in a separate paid step. That step is not part of this task (Rule zero).
- Keep every candidate's `LeverResult` and its row in the table, so a winner that later fails on quality can be swapped for the next one without re-running anything.
- In each step block, also name the runner-up and say what quality result would make it the winner.

**Prepare the paid quality run, but do not run it.** Add a section "Quality evaluation plan (not run)" to `sprint_decisions.md`. For each step it says:
- **Versions:** which versions go into the paid quality run (the provisional winner plus the runners-up worth testing). Use the cost results to drop versions that aren't worth paying for, and give the reason.
- **Routing:** which candidate models are the benchmark arms. Check them against `config/evaluation/benchmark.toml` and the arm callability in ADR-0053, and list any arm that has to be added or that can't be called.
- **Checks:**
  - Routing: the P-1 to P-3 benchmark (ADR-0053).
  - Answer cache: hit judging, the plan's cut-first (d), about 15 USD in the plan.
  - Context: the context ablation, cut-first (d), about 15 USD in the plan.
  - Retrieval caches: the agreement check already measured.
- **Decision rule:** which rule each check decides, from the plan's Decision rules.
- **What changes when labels arrive:** which result fields change (`correctness_state`, `assumptions`, `evidence_class`), and which command re-runs the final combination.
- **Gates:** the open gates before any spend: Metis permission (gate 2, Q-55), owner values Q-62 to Q-64, the budget caps raised to the new budget through an ADR-0018 amendment, and per-run approval.
- **Cost:** the estimate comes from `scripts/sampling_plan.py` and `scripts/benchmark.py plan`, run only in their **no-call planning mode**. If either would make a call, don't run it; write "estimate not computed".

**Do not decide alone:** stop and ask me to confirm the winners and the quality-run list before Stage 4.

## Stage 4: combine all pipelines (I-1)

1. **Ask me first:** whether `PostContextRouting` (or an equivalent fix) moves into the shared `combine` in `levers.py` (Pipeline A owns it), or stays a stated wrapper in the pipeline runner. Without it, every combined repriced figure drops the context saving. Draft the ADR either way (`0061-sprint-final-combine-and-units.md`).
2. **Context chaining:** `combine` takes one context version. If C's history budget and dedup (or a cross-pipeline pair) are both winners, propose a small `ChainedContext` wrapper in the experiment folder. Test that its saving ≤ the sum and that no token is counted twice.
3. **The run file:** generalise `experiments/pipelines/b-only-dry-run/` into `experiments/pipelines/sprint-final/` (`run.py`, `README.md`) plus `experiments/pipelines/sprint-final.toml`. The toml names one version per step for each of: `pipeline_a`, `pipeline_b`, `pipeline_c`, `parham` (routing only, with the cache and context winners) and `winners`.
4. **Runner:** `scripts/run_sprint_final.py` applies frozen versions to the **report split** (the final read) for every run against all four baselines. It reuses B's helpers:
   - the unit cells (`as_logged`: cache + context; price-file baselines: context + routing);
   - the sum rule (combined ≤ the compatible standalone sum; equality allowed when the steps touch different rows or blocks);
   - overlaps between steps;
   - the check that retrieval reuse rows keep `served_from_cache` false.
   Re-run `test_combined_saving_is_below_sum_of_standalone_savings` on real aggregates.
5. **Output:** `reports/pipelines/sprint-final/summary.json`, content-free. A combined pipeline is not a `LeverResult` (it has no single step), so keep B's summary format and extend it. Tests on synthetic frames.

## Stage 5: final numbers (I-2)

- `reports/levers/final.json`, in the format `wiring/lever_view.py` expects (`FINAL_JSON`; read `lever_view.py` and the D-2 tests first). Contents: the waterfall per cost block, with an "other" block from F-2 so no share hides the unexplained ~12%; intervals; four baselines; all slices; each pipeline alone and the winners; the units caveat in words.
- `tests/architecture/test_reports_content_free.py`: no text, IDs or hashes under `reports/`. Reuse the patterns of `test_router_reports_privacy.py` and B's ID scan. It must fail on a planted fixture first.
- Check the dashboard renders `final.json` (offline, fake mode). Report a screenshot path, not content.

## Stage 6: engineering track (cut from the bottom if short of time)

1. **E-3** `tests/architecture/test_lever_traceability.py`, with three tests:
   - every experiment README cites `FR-|QA-|NG-|H-\d|X\d`;
   - every `lever_id` prefix in `reports/levers/` maps to an experiment folder;
   - every ADR is listed in `docs/README.md`.
   Show that it fails when one ID is removed.
2. **E-5** `scripts/engineering_scorecard.py` → `reports/engineering_scorecard.json`, counts only: tests, architecture tests, ADRs, contract models with privacy classes, `module_reference` rows, hashed locked dependencies, CI status, levers with a manifest. Tests: `test_counts_come_from_the_repo`, `test_output_numbers_and_names_only`.
3. **F-1** the offline Gemini thinking check per the plan (billed output tokens over the answer-token estimate from the EDA chars-per-token slopes, labelled *hypothetical*; median and p90 for `gemini-2.5-flash` vs other high-volume models; "no cached tokens logged" is a logging gap, not "no caching"). Its three tests come from the plan.
4. **T-0 / T-2 / T-4** (services):
   - **T-0:** a `services` extra (`redis`, `mlflow-skinny` or `mlflow`; psycopg is already in `db`), its hash-pinned lock under `constraints-min-age.txt`, the `services` pytest marker, and the import-rule tests. `pyproject.toml` is a shared file: show me the diff and stop before writing the lock. If the lock conflicts, MLflow moves to stretch (plan, Risks).
   - **T-2:** `ports/tracking.py` `RunTracker`, the MLflow adapter, and `scripts/log_levers.py`. One run per lever, idempotent by `lever_id` + `config_hash`, nothing content-bearing reaching MLflow.
   - **T-4:** `compose.yaml` gets `redis`, `mlflow` and `demo` under a `services` profile, loopback-only ports, health checks, a CI `docker compose config -q` step, and guide updates.
   - One draft ADR covers all three.

## Definition of done (every task)

- A test that failed first and now passes.
- A `module_reference.md` row for every new module.
- A traceability ID.
- A draft ADR if a decision was made.
- `ruff check`, `ruff format --check`, `tests/architecture` and the full `pytest -q` green, or equal to the known baseline: 3 known failures (tokenizer assets ×2, git 2.23 `init -b`).
- A progress entry, the changed-files list and a suggested commit message.

## Questions to ask me, not to guess

1. Whether the `combine` fix goes into `levers.py` (Stage 4.1).
2. The provisional winners per step and the list for the paid quality run (end of Stage 3).
3. Whether the I-1 report-split run counts as the one allowed final read.
4. The `pyproject.toml` change for T-0.
5. Anything that needs Q-53, Q-55 or Q-62…Q-64 answered.
6. Anything that would spend money. The answer is no: report it and skip it.
