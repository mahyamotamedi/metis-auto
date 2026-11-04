# Metis-Auto Final Sprint Plan (4 days)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each person runs their own tasks in their own session; no two people edit the same file.

**Goal:** In 4 days, three people each build one end-to-end saving pipeline (cache → context → routing) on the full Metis dataset, Parham adds the routing base and the JEV experiment, the team compares every step's versions with one command, combines the winners, and presents an engineering-first talk with a working demo.

**Architecture:** Full-data experiments are pandas replays over `requests.parquet` from the existing EDA (`src/metis_auto/analysis/`). The repo's Stage 8 runner reads only the sample, so it is not used for them (ADR-0027). Each step version is a small function from a requests frame to a modified frame. One `combine` applies cache, then context, then routing. One content-free `LeverResult` JSON per version (with a reproducibility manifest) feeds the comparison, the savings waterfall and the demo. Candidate code lives in `experiments/` until promoted (ADR-0009, ADR-0022).

**Tech Stack:** Python 3.13 (`.venv`), pandas/pyarrow (already used by `analysis/`), numpy, pytest, ruff, GitHub Actions (new, ADR), Streamlit (existing demo), Redis, Postgres and MLflow (new `services` extra with its own hash-pinned lock, ADR), Docker Compose (existing `compose.yaml`).  a local reranker model (licence and GPU gated). No other new dependency without an ADR.

**Spec:** [`Metis-Auto Master Plan.pdf`](Metis-Auto%20Master%20Plan.pdf) (Nov 1, 2026, @Mahya), all parts; evidence in [`docs/full_eda/`](../../full_eda/) and `reports/full_eda/tables/claims_ledger.csv` (on `origin/main`, PR #6). This file **supersedes** [`2026-11-01-4-day-sprint.md`](2026-11-01-4-day-sprint.md) and [`2026-11-01-phase-0-foundation.md`](2026-11-01-phase-0-foundation.md).

---

## One-page summary (slide)

- **Team:** Pipelines A, B, C (Mahya, Kimia, Saba; who is which is decided in hour 1 of Day 1). **Parham** owns the routing base and the JEV experiment. **Shakib** helps with reviews, testing and slides, but nothing depends on him.
- **Where the money is** (EDA, observed): per-call fees 37.6% of recorded cost, input tokens 36.0%, output 14.3%, cached 0.4%. About 12% is unexplained and gets traced. `gemini-2.5-flash` is 12.5% of requests and 65.0% of cost. Retrieval first, routing last.
- **What we prove:** fee and token savings by replay on the logs (simulation), with session-clustered intervals, against **four baselines**, reported per bot, per tenant and traffic-weighted, all requests and LLM-only. **What we do not prove:** answer quality (except the small paid benchmark, if it runs), cache hit correctness beyond a sampled review, savings in production.
- **How we work (judged first):** tests first, CI on every push, layer rules enforced, contracts with privacy classes, an ADR per decision, a reproducibility manifest on every result, traceability IDs, and a generated engineering scorecard. Redis, Postgres and MLflow are added as adapters behind existing interfaces and started with one `docker compose up`.
- **Money:** 100 USD (owner). Until the ADR-0018 amendment is committed, the code limit stays 10 USD. Every live call also needs the Metis licence answer and per-run approval.
- **Schedule:** Day 1 shared base and first numbers. Day 2 cache and context. Day 3 routing and integration. Day 4 final numbers, **code freeze at 12:00**, rehearsal, present.

## Team and roles

| Who | Role | Main files (one owner each) |
|---|---|---|
| Pipeline A (decided Day 1) | popular-question cache, reranker sizing, per-bot reassignment; shared: `levers.py`, `lever_result.py` (+ manifest), ADR-0027, overhead script, MLflow tracking | see tasks S-1, S-4, E-2, R-A*, L-1, T-2 |
| Pipeline B (decided Day 1) | retrieval-result cache, cross-turn chunk policy, kNN router; shared: comparison command, cache guard, cost trace, storage adapters (Postgres sink, Redis store) | S-2, S-5, F-2, T-1, T-3, R-B* |
| Pipeline C (decided Day 1) | session memo + skip gate, history budget, classifier; shared: scope/split/baselines, within-message dedup, CI, demo | S-3, E-1, D-1, D-2, R-C* |
| **Parham** (Claude Pro) | routing base (registry, hard constraints, failover chain), JEV onboarding and experiment, free Gemini check, paid benchmark owner, services extra and lock, Docker Compose, traceability test, scorecard | R-0, J-1…J-4, F-1, P-1…P-3, T-0, T-4, E-3, E-5 |
| **Shakib** (no AI tools) | hit-correctness review, word-list and language checks, demo tester, slide layout, Metis tracker | K-1…K-6, each with a named fallback owner |

Suggested by fit: B = Kimia (wrote `cache_replay`). File names are by version, not by person, so the choice costs nothing.

## Global Constraints

- Agents never run `git commit`, `git push`, or history-rewriting commands. Humans commit. Every task ends with a changed-files list and a suggested message (CLAUDE.md § Git).
- **Licence** (EDA report §2): use is limited to education, and redistribution is forbidden. Anything committed holds aggregates only: no content, no content hashes, no bot or user IDs. Demo screens show ranks like `bot-07`. No data is uploaded to Colab or any third party until Metis answers the licence question (O-1).
- Derived tables (`data/derived/`, `data/full_data/`) are git-ignored and local. Each person regenerates them with `scripts/full_eda_ingest.py` at the pinned revision `30f578f283b903cdbd06cd1b5f7f962f76452ded`.
- `.env` is never read, printed or committed. The leaked Hugging Face token is rotated by its owner before Day 1 (EDA report §7).
- **Money:** `config/defaults.toml` holds `lifetime_ceiling = "20"`, `lifetime_cap = "10"` and `run_cap = "1"` until the ADR-0018 amendment 2 is committed (O-1). The ledger is per machine, so there are four ledgers (A, B, C, Parham). No live call unless an owner asks in chat. Sample conversations need per-run approval (ADR-0018 point 5).
- **Definition of done for every task:** a test that failed first and now passes; a `module_reference.md` row for new modules; a traceability ID (`FR-`/`QA-`/`NG-`/`H-n`/`X-n`) in the README or docstring; an ADR if a decision was made; `ruff check`, `ruff format --check` and `tests/architecture` green; a changed-files list and suggested commit message.
- **Layer rules:** `analysis` may import only `domain`, `ports` and `contracts` (`tests/architecture/test_import_rules.py`). `experiments/` code is loaded only by scripts. `wiring` builds things; `scripts/demo_ui.py` holds no logic (ADR-0024).
- **Evidence labels** (EDA): *observed*, *metadata-derived*, *heuristic*, *hypothetical reconstruction*, *simulation*. A cache hit is a *candidate* hit until reviewed. Recorded cost is in unstated units and is never mixed with repriced cost. "Unknown" is never zero.
- Workflow bots (29.7% of requests, empty billing) are excluded from every hit rate and saving. Every rate is reported twice: over all requests and over LLM requests only.
- **Time split:** tune March–July 2026, report August–October 2026, by whole session and duplicate family. The report period is read once. Timestamps are naive (Q-06), and every time-based result says so.
- **Persian:** every key uses `analysis/text_features.normalize_safe`. No second normaliser.
- **Services:** Redis, Postgres and MLflow are imported only in their adapter modules (tested). They live in a `services` extra with its own lock, and the default test run never needs them. Real-server tests are opt-in (`-m services`). The Postgres password comes only from the environment.
- **Commands:** macOS (Mahya, Kimia) use `.venv/bin/python`; Windows (Saba) uses `.venv\Scripts\python.exe`. The known Windows failures (33 failed, 3 collection errors; `fcntl`, POSIX paths) are recorded as a baseline in S-0, not fixed.

## Review Focus

Failure modes the spec implies that need their own test, most likely first:

1. **Savings counted twice** (a cache hit also counted as a context saving): requests served from cache get no context or routing saving, and the combined saving is below the sum. → S-1.
2. **Leakage across the split** (a session or duplicate family in both tune and report): → S-3.
3. **Cached-token convention** (`inputTokens` excludes cached tokens for five models; the EDA adds them back): repricing must follow the same rule. → R-A3, J-3.
4. **Same chunk ID with changed text** (corpus update): never counted as a safe reuse or a safe drop. → R-B1, R-B2, S-6.
5. **One tenant dominating** (5 users make 97.0% of requests): no tenant above 35% of any sample, and per-tenant and traffic-weighted rows are always shown. → S-3, P-1.

---

## Scope tiers (nothing from the PDF is dropped silently)

| Tier | Contents |
|---|---|
| **Core** | Shared base (S-0…S-6); 9 step versions (R-A1…R-C3); routing base (R-0); JEV (J-1…J-3); free Gemini check (F-1); 12% cost trace (F-2); integration (I-1, I-2); overhead (L-1); decision notes (N-1); engineering track (E-1…E-5); services track (T-0…T-4: Redis, Postgres, MLflow, Docker Compose); demo (D-1, D-2); talk |
| **Paid, gated** (default on) | Small routing benchmark P-1…P-3, including JEV live (J-4) |
| **Cut first if behind** (kept, cut only with the team's OK at the Day 2 12:00 checkpoint) | (a) real reranker model run (R-A2 falls back to token sizing); (b) three extra free checks: hidden query rewriter, exact vs near-copy split, template formatting overhead; (c) prompt rebuild with history `k` fitted per bot; (d) heavy labelling: 250 human labels + κ gate + PPI, the paid cache judging (~15 USD) and the paid context ablation (~15 USD) |
| **Stretch** (after core; trigger listed below) | Gemini adapter + thinking A/B + 2.5 replacement; semantic retrieval cache; nightly paraphrase grouping; XProvence; explicit Gemini cache; cascade; multi-turn drift test; offline instruction shortening; embedding/rerank cache; remaining Phase S services (Langfuse, Prometheus/Grafana); production Compose profile and load test |

**PDF coverage map** (where each PDF item lives here): three rules → Global Constraints; Part 1 findings → summary and talk; Step 1 approaches → R-A1/R-B1/R-C1 and the stretch list; Step 2 → S-6, R-A2/R-B2/R-C2 and the stretch list; Step 3 → R-0, R-A3/R-B3/R-C3, J-*, P-*; Step 0 free checks → F-1, S-0 verify, and the checks inside R-B1/R-C1; Foundation data and replay → S-0, S-3 (EDA did the rest); evaluation admin → P-2, cut-first (d), O-1; decide rules → "Decision rules" section; ship (flags, shadow) → S-5 cache guard and the talk's "next steps"; software tools → E-1, T-0…T-4, plus stretch; frontend → D-1, D-2; final integration → I-1, I-2, N-1; bonus phases → stretch; budget → O-1, P-*; Metis questions → O-1; risks → Risks table.

## The pipelines (a row is one person's pipeline; a column is one step's competing versions)

| Step | Pipeline A | Pipeline B | Pipeline C | Parham |
|---|---|---|---|---|
| Cache | popular-question cache | retrieval-result cache | session memo + greeting skip gate | — |
| Context | reranker + threshold | cross-turn chunk policy | history budget (stepped window) | — |
| Routing | per-bot reassignment + rules | kNN router | small classifier | routing base (shared by all); JEV as a candidate model |

**Routing without quality labels (default unless P-1…P-3 ran):** B = **nearest-profile policy** (pick the cheapest model that bots with the nearest feature profiles already run). C = **threshold classifier** on the EDA's transparent rule features (short, no RAG, no attachments, no tools, no JSON; EDA §4.4). Both are cost simulations with "quality not proven". With benchmark labels, both train on them instead, with wide intervals.

## Decision rules (written before results; copied from the PDF, Part 3 and Part 4)

- **Cache, retrieval versions (B, C):** retrieval agreement with the later real lookup ≥ 0.9.
- **Cache, answer versions (A):** answer error ≤ 1%, which needs about 300 reviewed hits with no errors. With fewer reviewed hits (K-1 / X1 sample), the result stays a *candidate* saving and says how many were reviewed.
- **Pick:** the highest net saving that passes. Versions that target different cost blocks may be combined.
- **Context:** pass only if loss rate minus win rate is within the noise + 3 points, no user or language group is more than 10 points worse, and JSON validity, reply language and refusal rate do not get worse. Without the paid ablation (cut-first d), context results are labelled "tokens only, quality not measured".
- **Routing:** move a bot to a cheaper model only if its acceptable rate is within 10 points of the incumbent (lower 95% bound, judge-corrected) and its cost per request is lower. Keep a more complex router only if it beats per-bot reassignment outside the confidence interval. Use nested cross-validation grouped by session, bootstrap by bot then session, and one look at the held-out 30%.
- **Baselines, always four:** premium `gpt-5.5` (estimate only, ADR-0026), as-logged (recorded cost), today's logged models, and the **best single cheap model** (cheapest callable model on every eligible request, cost only).
- **Slices, always:** all vs LLM-only; per bot (ranked), per tenant, traffic-weighted; by language; the over-8,000-token slice; no tenant above 35% in any sample.
- **Conflict to settle (O-1):** ADR-0006 uses "judge score drop ≤ 3% overall, ≤ 5% per stratum". The PDF uses the rules above. Default: report both.

## Shared interfaces (defined once on Day 1; every later task uses them unchanged)

- **`requests` frame:** the output of `analysis/requests_table.build_requests`. Columns seen on `origin/main`: `bot_id`, `session_id`, `user_id`, `timestamp`, `lang`, `n_prior_msgs`, `prior_chars`, `hist_hash`, `h_exact`, `h_norm`, `rag_n_queries`, `rag_n_chunks`, `rag_chunk_chars`, `n_per_call_only_items`, `finish_reason`, `is_json`, `att_n`, `tool_n_calls`, `billing_state`, plus `bot_*` configuration and billing sums. S-3 adds `period` and `llm_request`, and confirms the cost-block column names (fees, input, output, cached, other).
- **`StepVersion`** (Protocol, `src/metis_auto/analysis/levers.py`): `name: str`, `step: Literal["cache", "context", "routing"]`, `apply(req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame`. The result is a copy with the same index:
  - cache versions set `served_from_cache = True` and zero every cost block on hit rows;
  - context versions lower `input_tokens` and the input block;
  - routing versions set `routed_model` and re-price.
- **`ReplayContext`** (frozen dataclass): `period_bounds`, `price_table`, `catalogue`, `seed: int`, `min_n: int | None`, `guard: CacheGuard`.
- **`combine(req, cache, context, routing, ctx) -> pd.DataFrame`:** rows served from cache skip context and routing.
- **`LeverResult`** (frozen pydantic, `src/metis_auto/analysis/lever_result.py`, every field privacy-classified):
  - `lever_id`, `step`, `version`;
  - `n_requests`, `n_eligible`;
  - `baseline: str`, `baseline_cost: dict[str, Decimal]`, `saving: dict[str, Decimal]`;
  - `ci_low`, `ci_high` (session-clustered, `analysis/stats.cluster_bootstrap_ratio`);
  - `slices: dict[str, dict[str, Decimal]]` (keys: `llm_only`, `traffic_weighted`, `lang:<label>`, `over_8k`, `tenant_rank:<n>`);
  - `evidence_class`, `correctness_state` (`"unmeasured"` / `"sampled:<n>"` / `"measured"`), `assumptions: tuple[str, ...]`;
  - `overhead_ms_p50`, `overhead_ms_p95: float | None`;
  - `manifest: Manifest`.

  It is written to `reports/levers/<lever_id>.json`.
- **`Manifest`:** `data_revision`, `code_commit`, `config_hash`, `seed`, `price_version`, `python_version`, `created_at` (UTC).
- **`CacheGuard`** (`src/metis_auto/analysis/cache_guard.py`): `approved: frozenset[str] | None` (None = no approval step), `blocked: frozenset[str]`, `disabled_bots: frozenset[str]`, `key_version: str`. It provides `allows(key: str, bot: str) -> bool` and `shadow_sample(keys: pd.Series, rate: float, seed: int) -> pd.Series`.
- **`eligible_models(row, catalogue, prices, rules) -> tuple[str, ...]`** (`src/metis_auto/analysis/routing_base.py`, R-0), with the failover chain `failover(model) -> tuple[str, ...]`: same model elsewhere, then the same tier, then one tier up.

---

## Schedule

| Slot | Pipeline A | Pipeline B | Pipeline C | Parham | Shakib  |
|---|---|---|---|---|---|
| **D1 08–10** | S-0 | S-0 | S-0 | S-0 | check data access; read the talk outline |
| **D1 10–13** | S-1 | S-2 | S-3 | J-1 JEV note | K-6 Metis tracker |
| **D1 14–18** | S-4 ADR, E-2 manifest | S-5 cache guard, T-3 Postgres sink | E-1 CI, D-1 demo shell | J-2 JEV config, F-1 Gemini check, T-0 services extra + lock (evening) | — |
| **D1 18:00** | Checkpoint (all, 30 min): demo features, amendment status, A/B/C confirmed | | | | |
| **D2 am** | R-A1 cache | R-B1 cache | S-6 dedup, R-C1 cache | R-0 routing base | K-1 / K-2 reviews (if allowed) |
| **D2 12:00** | Checkpoint: cut-first decisions | | | | |
| **D2 pm** | R-A2 context, L-1 script, T-2 MLflow (evening) | R-B2 context, F-2 cost trace | R-C2 context | P-1 benchmark set, J-4 live smoke (if approved) | K-3 language sheet |
| **D3 am** | R-A3 routing | R-B3 routing | R-C3 routing | J-3 JEV replay, P-2 benchmark run | K-4 demo tester |
| **D3 pm** | I-1 (all), L-1 (each), N-1 (each) | + T-1 Redis store | + D-2 dashboard | P-3 labels to B/C, T-4 Compose | K-4, K-5 slides |
| **D4 am** | I-2 final numbers | slides | slides, demo data | E-3 traceability, E-5 scorecard, slides | K-5 |
| **D4 12:00** | **Code freeze** | | | | |
| **D4 pm** | Rehearse ×2 (once on the presenting laptop), present | | | | |

**Critical path:** S-0 → S-1/S-3 → the cache versions → I-1 → I-2 → slides. Everything else runs in parallel.

---

## Day 1 tasks

### Task S-0: Pull, regenerate, baseline (everyone, 08:00–10:00)
- [ ] `git fetch` and work from `origin/main` (merge it into your branch, or `git switch -c sprint-<x> origin/main`; you commit, not an agent). Check that `src/metis_auto/analysis/` and `docs/full_eda/` exist.
- [ ] Set up `.venv` per CLAUDE.md with the hash-pinned dev lock and the `eda` extra.
- [ ] Put the rotated Hugging Face token in your own `.env`. Run `scripts/full_eda_ingest.py --smoke`, then the full ingest, then `scripts/full_eda_requests.py`. Expected: `data/derived/full_eda/requests.parquet`, consistent with ledger `scope.messages` (710,640) and 349,079 AI messages.
- [ ] Run `pytest -q`; save the failing IDs to your local `sprint-notes.md` (uncommitted).
- [ ] Verify in the claims ledger which free checks are already answered (`rag.*`, `bill.*`, `fees`); write the list in `sprint-notes.md`.
- [ ] Team decision: who is A, B, C.

Done when: all four builders have `requests.parquet` and a recorded test baseline.

### Task S-1: `StepVersion`, `ReplayContext`, `combine`, `LeverResult` (A)
**Files:** Create `src/metis_auto/analysis/levers.py`, `src/metis_auto/analysis/lever_result.py`. Test: `tests/unit/analysis/test_levers.py`.
- [ ] Failing tests:
  - `test_combine_applies_cache_then_context_then_routing`;
  - `test_cache_hit_gets_zero_context_and_routing_saving` and `test_combined_saving_is_below_sum_of_standalone_savings` (6-row synthetic frame; Review Focus 1);
  - `test_lever_result_has_no_text_or_id_field`;
  - `test_workflow_rows_never_counted`;
  - `test_every_result_has_all_and_llm_only_slices`.
- [ ] Run them and confirm they fail. Implement the names in "Shared interfaces". Run them and confirm they pass, along with `tests/architecture`.
- [ ] Add the module rows. Suggested commit: `feat(analysis): lever result format and combine`.

Done when: B and C have written an identity version against `StepVersion` by 14:00.

### Task S-2: Comparison command (B)
**Files:** `src/metis_auto/analysis/compare.py`, `scripts/compare_levers.py`. Test: `tests/unit/analysis/test_compare.py`.
- [ ] Failing tests:
  - `test_orders_versions_by_saving_within_a_step`;
  - `test_shows_unmeasured_correctness`;
  - `test_four_baselines_present_or_marked_missing`;
  - `test_results_with_different_baselines_are_not_compared`;
  - `test_tenant_share_above_35_percent_is_flagged`.
- [ ] Implement `compare(results: Sequence[LeverResult], *, baseline: str) -> pd.DataFrame` and a Markdown writer. CLI: `compare_levers.py reports/levers/*.json --out reports/levers/comparison.md`. Tests pass.
- [ ] Suggested commit: `feat(analysis): lever comparison command`.

### Task S-3: Scope, split, baselines (C)
**Files:** `src/metis_auto/analysis/replay_scope.py`, `src/metis_auto/analysis/baselines_full.py`, `config/evaluation/sprint.toml` (period dates, `min_n`, routing candidates, retiring models with source and date, word lists). Tests: `tests/unit/analysis/test_replay_scope.py`, `test_baselines_full.py`.
- [ ] Failing tests:
  - `test_period_unknown_when_timestamp_missing`;
  - `test_boundaries_inclusive`;
  - `test_workflow_rows_are_not_llm_requests`;
  - `test_no_session_or_duplicate_family_straddles_the_split` (Review Focus 2);
  - `test_bot_with_one_request_is_insufficient`;
  - `test_sample_caps_any_tenant_at_35_percent` (Review Focus 5);
  - `test_best_single_cheap_model_baseline_uses_only_callable_models`.
- [ ] Implement:
  - `scope(req, ctx) -> pd.DataFrame` (adds `period`, `llm_request`);
  - `split_by_session(req, *, seed) -> pd.Series`;
  - `cap_tenant_share(req, max_share: float) -> pd.DataFrame`;
  - `baseline_costs(req, ctx) -> dict[str, dict[str, Decimal]]` for the four baselines.
- [ ] Done when: the period counts and the `llm_request` split match the ledger's `scope.*` and `model.workflow_share` within rounding. Suggested commit: `feat(analysis): replay scope, split and four baselines`.

### Task S-4: ADR-0027, full-data lever replay (A)
- [ ] Write `docs/adr/0027-full-data-lever-replay.md`.
  - Context: the Stage 8 runner reads only the sample.
  - Alternatives: extend `ExperimentRunner`, or a separate pandas path.
  - Decision: a separate pandas path in `analysis/` with candidates in `experiments/`; the promotion rule is unchanged.
  - Consequences: results are simulations, and there is no live path.
  - Cite H-3, H-8, X1, X2, X5, X7.
  - Use the next free ADR number on `main` if 0027 is taken.
- [ ] Add it to `docs/README.md`. `tests/architecture` green.

### Task S-5: Cache guard (B)
**Files:** `src/metis_auto/analysis/cache_guard.py`. Test: `tests/unit/analysis/test_cache_guard.py`.
- [ ] Failing tests:
  - `test_unapproved_key_is_never_served_when_approval_is_on`;
  - `test_blocked_key_is_never_served`;
  - `test_disabled_bot_is_never_served`;
  - `test_key_version_change_invalidates_old_keys`;
  - `test_shadow_sample_is_seeded_and_about_the_given_rate` (1% default from `sprint.toml`).
- [ ] Implement `CacheGuard` as in "Shared interfaces". Every cache version calls `allows` before counting a hit and reports the shadow-check result.
- [ ] Suggested commit: `feat(analysis): cache guard with approval, blocklist, off switch, versions, shadow check`.

### Task E-1: CI (C, Day 1 afternoon)
**Files:** `.github/workflows/ci.yml` (none exists on `origin/main`); `docs/adr/00xx-ci-github-actions.md`.
- [ ] On push and pull request, CI installs with `--require-hashes` from `requirements-dev.lock` plus the `eda` extra, then `pip install -e . --no-deps`, then runs `ruff check`, `ruff format --check` and `pytest -q`. Matrix: `ubuntu-latest`, `macos-latest`. Windows is excluded, with the reason in a comment.
- [ ] Expected: green on a clean branch. Proof for the slide: a throwaway branch with a forbidden import (`domain` importing `adapters`) makes CI red. Take a screenshot, then delete the branch.
- [ ] Suggested commit: `ci: run lint, tests and architecture rules on push`.

### Task E-2: Reproducibility manifest (A, with S-1)
**Test:** `tests/unit/analysis/test_lever_manifest.py`.
- [ ] Failing tests:
  - `test_result_records_revision_commit_config_hash_seed_price_and_python_version`;
  - `test_same_inputs_same_seed_give_identical_json`;
  - `test_changing_a_threshold_changes_the_config_hash`;
  - `test_manifest_has_no_path_or_user_name`.
- [ ] Implement `Manifest`, filled by a helper `build_manifest(config: Mapping, ctx: ReplayContext) -> Manifest`. Tests pass.

### Task D-1: Demo shell (C, Day 1 afternoon)
**Files:** `src/metis_auto/wiring/lever_view.py` (Streamlit-free view model); `scripts/demo_ui.py` changes only through it. Test: `tests/unit/wiring/test_lever_view.py`.
- [ ] Failing tests:
  - `test_view_reads_only_lever_result_json`;
  - `test_rank_labels_not_ids`;
  - `test_waterfall_rows_sum_to_total`;
  - `test_empty_state_when_no_results`.
- [ ] Implement, then pass. At the **18:00 checkpoint** the team picks the demo features. Default: savings waterfall on real aggregates, a version switch per step, the per-bot recommendation table, the chat tab in fake mode with a cache hit and the cost panel, and the budget bars. Write the choice in `sprint-notes.md`.

### Task J-1: JEV note (Parham, Day 1 morning)
**File:** `docs/references/jev_model_note.md`.
- [ ] Write, with a source and check date for each fact:
  - provider (`typesafe` on the Metis price list);
  - endpoint and API format;
  - whether it is OpenAI-compatible;
  - context window and output limit;
  - Persian support;
  - price (the Metis list saved 2026-10-18 says input 0.0462 USD per 1M tokens and output 0.0000; **confirm the output price**);
  - tokenizer (published or not);
  - whether thinking tokens are billed.

  Anything unsourced is marked *unverified*.
- [ ] Done when: the note says whether JEV can go through the existing OpenAI-compatible adapter (`adapters/providers/openai_compat.py`) or needs a new adapter (then add an ADR to the stretch list; J-4 and P-2 use JEV only if it is compatible).

### Task J-2: JEV configuration (Parham, Day 1 afternoon)
**Files:**
- `config/reference/catalogue-metis-test.toml`: a JEV row, **disabled** until J-4;
- a new dated price file `config/reference/prices-metis-2026-11-0X-jev.toml`, copying the current one plus the JEV row; never edit the old file;
- an endpoint row in `endpoints-metis.toml` only if OpenAI-compatible;
- `tokenizers.toml`: an approximation row, labelled, unless a tokenizer is published.

**Test:** extend `tests/integration/test_settings_wiring.py` (macOS) with `test_jev_row_loads_and_is_disabled` and `test_unknown_limits_exclude_jev_from_routing` (FR-ROUTE-05).
- [ ] Suggested commit: `config: add JEV catalogue, price and endpoint rows (disabled, sourced)`.

### Task F-1: Free Gemini check (Parham, Day 1 afternoon)
**Files:** `experiments/cost/exp-cost-001-gemini-thinking/check.py`, `README.md`. Test: `tests/unit/experiments/test_gemini_thinking_check.py`.
- [ ] Failing tests:
  - `test_ratio_is_billed_output_tokens_over_answer_tokens_estimate` (answer tokens from characters using the EDA's chars-per-token slopes, labelled *hypothetical*);
  - `test_only_rows_with_the_given_model_label_are_used`;
  - `test_no_cached_tokens_logged_reports_logging_gap_not_no_caching`.
- [ ] Implement `gemini_thinking(req: pd.DataFrame, *, model_label: str, chars_per_token: float) -> dict`. Report the median and p90 ratio for `gemini-2.5-flash` against the other high-volume models.
- [ ] Done when: the report says whether hidden thinking looks likely. This is the trigger for the Gemini stretch item.

### Task O-1: Owner decisions and messages (Day 1)
- [ ] Send [`docs/full_eda/metis_questions.md`](../../full_eda/metis_questions.md) (15 questions, P0 first), plus:
  - (a) may samples be sent to model APIs, and shown to helpers and annotators (Shakib)?
  - (b) is there a batch tier on the gateway?
  - (c) what is JEV, and are its limits and price right?
- [ ] Budget:
  - Write ADR-0018 amendment 2 (ceiling 100 USD; four per-machine caps that sum to at most 85 USD with 15 USD reserve, matching the PDF's reserve line; per-run caps).
  - Make the reviewed change to `config/defaults.toml`.
  - Raise the Metis dashboard limit (the second safety net).
  - Suggested commits: `docs(adr): ADR-0018 amendment 2` and `config: raise budget caps`.
- [ ] Owner picks ADR-0006 thresholds, PDF rules, or both (default: both).

---

## Day 2–3 tasks: the step versions

Every version is `experiments/<area>/<exp-id>-<slug>/version.py` implementing `StepVersion`, with a `README.md` (hypothesis, assumptions, evidence class, traceability IDs), tests in `tests/unit/experiments/`, and a `LeverResult` per baseline in `reports/levers/`. Thresholds are fixed on the tune period. The report period is read once.

### Task S-6: Within-message dedup and stable order (C, Day 2, first 2 hours)
- [ ] `experiments/context/exp-ctx-001-within-message-dedup/version.py`. Tests:
  - `test_duplicate_chunk_counted_once`;
  - `test_same_id_different_hash_is_not_a_duplicate` (Review Focus 4);
  - `test_exact_and_normalised_duplicates_reported_separately`.
- [ ] Stable prompt order is a documented rule in its README: instructions first, then chunks, then history, then the message. No code unless a check needs it.
- [ ] Reference: 33.3% of chunk rows duplicate another chunk in the same message (EDA §4.3).

### Task R-A1: Popular-question cache (A)
- [ ] Tests:
  - `test_nightly_set_uses_only_previous_days` (day *d* from *d−90…d−1*; window maximum 180);
  - `test_requires_three_occurrences_in_two_sessions`;
  - `test_memory_and_rag_requests_ineligible`;
  - `test_guard_blocks_unapproved_and_blocked_keys`;
  - `test_most_typical_answer_choice_uses_answer_hash_mode`;
  - `test_hit_labelled_candidate`.
- [ ] Implement `PopularQuestionCache(window_days: int, min_count: int, min_sessions: int)`. Values: 90, 3, 2 in `sprint.toml`.
- [ ] Export the top keys for review (K-1) as a local, uncommitted sheet.
- [ ] Done when: report-period hit and cost shares sit beside the EDA references (bot + text cross-session 28.0%, full history 8.3%), and `correctness_state` reflects K-1.

### Task R-B1: Retrieval-result cache (B)
- [ ] Tests:
  - `test_key_is_bot_corpus_version_settings_and_normalised_query`;
  - `test_fee_avoided_equals_recorded_fee_of_skipped_lookups` (0.002-unit items);
  - `test_agreement_is_overlap_with_later_real_chunk_ids`;
  - `test_changed_chunk_hash_is_disagreement` (Review Focus 4);
  - `test_backstop_ttl_expires`;
  - `test_shadow_check_reported`.
- [ ] Free checks inside this task:
  - repeat rate of bot + normalised query within 1, 7, 30 and 90 days (this sets the TTL);
  - knowledge-base churn per bot (this sets freshness).
- [ ] Implement `RetrievalResultCache(ttl: pd.Timedelta | None)`. Report fees avoided against the fee block (37.6%) and the agreement distribution. Label **measured potential** (Metis question: can Metis-Auto sit in front of retrieval?).

### Task R-C1: Session memo + greeting skip gate (C)
- [ ] Tests:
  - `test_reuse_only_inside_one_session`;
  - `test_phatic_message_skips_retrieval` (word list in `sprint.toml`, marked `[PLACEHOLDER: Persian review]`);
  - `test_overlap_threshold_has_no_default`;
  - `test_turn_zero_never_skipped`.
- [ ] Free checks inside this task:
  - how often a turn's fresh chunk set mostly overlaps the previous turn's;
  - share of retrieval turns that are greetings, thanks or short meta requests.
- [ ] Implement `SessionMemo(overlap_threshold: float | None, phatic_words: frozenset[str])`. Report lookups skipped or reused, and agreement.

### Task R-A2: Reranker + threshold (A)
- [ ] Tests:
  - `test_curve_is_tokens_saved_against_top_k_and_threshold`;
  - `test_minimum_chunk_floor`;
  - `test_scorer_injected_so_tests_need_no_model`.
- [ ] Implement `RerankerCut(scorer: Callable[[str, list[str]], list[float]], floor: int, threshold: float)`.
- [ ] Core deliverable: a token-sizing curve with a lexical-overlap scorer (labelled *heuristic*).
- [ ] Cut-first (a): the real `bge-reranker-v2-m3` on about 2,000 sampled RAG turns, on a **local** GPU only (no Colab until the licence answer). This includes the "chunks the answer used against top-k" plot.

### Task R-B2: Cross-turn chunk policy (B)
- [ ] Tests:
  - `test_repeat_in_session_dropped_with_pointer_cost`;
  - `test_not_visible_chunk_kept` (visibility is an argument, because the history policy is unidentified, EDA §2);
  - `test_changed_hash_kept`;
  - `test_optional_session_ledger_counts_append_only_block`.
- [ ] Implement `CrossTurnChunkPolicy(pointer_tokens: int, assume_visible: Callable[[int], bool], session_ledger: bool)`. Tokens use the EDA slope of about 0.34 tokens per chunk character (*hypothetical*). Context: 61.2% of chunk rows repeat earlier in the session.

### Task R-C2: History budget (C)
- [ ] Tests:
  - `test_budget_only_reduces_requests_above_it`;
  - `test_stepped_window_drops_whole_turns`;
  - `test_memory_and_summarising_bots_excluded`;
  - `test_result_labelled_upper_bound`.
- [ ] Implement `HistoryBudget(budget_tokens: int, step_turns: int)`. Report the calibrated baseline, the half budget on long requests, and the stepped window. The saving uses the excess-over-turn-0 proxy (67.2%). Include the over-8,000-token slice (10.7% of requests, 65.2% of input).
- [ ] Cut-first (c): the PDF's prompt rebuild with `k` fitted per bot.

### Task F-2: Trace the unexplained ~12% of cost (B, Day 2 evening)
- [ ] `experiments/cost/exp-cost-002-cost-trace/check.py` and a test `test_blocks_sum_to_total_cost`. Break the remainder (100% − 36.0 − 14.3 − 0.4 − 37.6) into `costBreakdown` items (web search calls, audio tokens, cache writes, other) using `analysis/billing.parse_billing`.
- [ ] Done when: the waterfall has an "other" block with its own label, and no final saving is stated as a share of a total that hides it.

### Task R-0: Routing base (Parham, Day 2)
**Files:** `src/metis_auto/analysis/routing_base.py`. Test: `tests/unit/analysis/test_routing_base.py`.
- [ ] Failing tests:
  - `test_vision_requests_only_get_vision_models`;
  - `test_context_over_limit_excluded`;
  - `test_unknown_limit_excludes_model`;
  - `test_long_context_price_cliff_avoided`;
  - `test_retiring_model_replaced_from_config_list`;
  - `test_failover_chain_order`.
- [ ] Implement `eligible_models` and `failover` per "Shared interfaces", with the catalogue, prices and `sprint.toml` rules. Also tokenize per candidate model on Persian prompts with the existing tokenizers (labelled by fidelity), and replay the cost of every candidate on all eligible traffic (free).
- [ ] Done when: A, B and C import it for R-A3, R-B3 and R-C3 by Day 3 08:00.

### Task R-A3: Per-bot reassignment + rules (A)
- [ ] Tests:
  - `test_repricing_adds_cached_tokens_back_for_the_five_models` (Review Focus 3);
  - `test_fee_block_unchanged_by_routing`;
  - `test_never_routes_upward`;
  - `test_uses_routing_base_constraints`.
- [ ] Implement `PerBotReassignment(candidates: Sequence[str])`. First reproduce the EDA simulation (14.2% for the rule group, 41.6% for all billed requests; upper bounds), then the per-bot table.

### Tasks R-B3 / R-C3: kNN and classifier (B, C)
- [ ] Tests:
  - `test_labels_only_from_declared_source`;
  - `test_session_grouped_nested_cv`;
  - `test_small_n_insufficient_or_wide_interval`;
  - `test_quality_not_proven_in_assumptions_without_labels`.
- [ ] Implement per "Routing without quality labels". Use numpy logistic regression; scikit-learn only with an ADR.
- [ ] Done when: both are compared with R-A3 on the same split and baselines.

### Task J-3: JEV as a routing candidate (Parham, Day 3)
- [ ] No new routing code: run R-A3's `PerBotReassignment` with candidates including JEV (`sprint.toml` `routing.candidates_jev`), giving the `LeverResult` `route.per_bot+jev`. Test: `test_jev_result_differs_only_by_candidate_list`.
- [ ] Report the cost difference against R-A3 without JEV. Quality: "not proven" unless J-4 and P-2 ran.

### Task J-4: JEV live smoke test (Parham; only if an owner asks in chat)
- [ ] Synthetic Persian and English messages only. Print the estimated cost first; set the run cap to the approved amount; stay within the ledger.
- [ ] Use the existing `scripts/live_wrapper_check.py` pattern. Check that usage is reported, the finish reason, the reported model, Persian output, and whether thinking tokens are billed.
- [ ] Record the results in `docs/references/jev_live_check.md` with the date. If everything passes, enable the catalogue row (the owner commits).

---

## Paid branch (default on, gated): small routing benchmark

**Gates (all three):** ADR-0018 amendment 2 committed; Metis allows sending samples to model APIs; owner approval in chat per run, after the printed estimate.

- **P-1 (Parham, Day 2 pm):** **300 requests** (team decision) from the report period, run as a 20-request pilot first (discarded from results), then the main run on Day 2 evening so judging can finish on Day 3 morning, through E4 `evaluation/sampling`, with quotas by bot rank, language, RAG, length and turn; no tenant above 35% (S-3). Arms:
  - the logged answer (free);
  - the callable test models (`gpt-5-nano`, `gpt-4.1-nano`, `gpt-4o-mini`, `deepseek-v4-flash`, `mimo-v2.5`);
  - `gpt-5.5`;
  - JEV, if J-4 passed.

  `gemini-2.5-flash` cannot be called (no Gemini adapter, ADR-0018 point 2); the results slide says so. Estimate printed by `scripts/sampling_plan.py`; the PDF's 35 USD for 500 requests suggests about 20–25 USD for 300 (scaled estimate, to be replaced by the printed one). If the main run is not finished by Day 3 10:00, judge what has finished and report n. Use the batch tier if Metis confirms one.
- **P-2 (Parham with B, Day 3 am):** two judges from different families, both answer orders, strict JSON (E5 `evaluation/judging`); a 60-item human spot-check by the team (and Shakib if allowed).
- **P-3 (Parham → B and C, Day 3 pm):** give the labels to R-B3 and R-C3, then apply the routing decision rule.

## Day 3 pm – Day 4 tasks

### Task L-1: Overhead per version (A writes the script; each owner runs it)
- [ ] `scripts/measure_lever_overhead.py`, following the pattern of the existing `scripts/measure_overhead.py`: per-request time of `apply` on 1,000 sampled rows, p50 and p95, written into `LeverResult`. Test: `test_overhead_fields_filled_and_labelled_offline_estimate`.
- [ ] Compare with the 100 ms p95 target (Q-14). Label as an offline per-request estimate; no load test (stretch).

### Task N-1: Decision note per step (each column's owners together, Day 3 pm)
- [ ] `docs/experiments/sprint_decisions.md`: one block per step (cache, context, routing) saying what was tried, what won, why, the evidence class and the open question.

### Task I-1: Pick winners and combine (all, Day 3 pm)
- [ ] `scripts/compare_levers.py reports/levers/*.json`. Apply the decision rules to choose the winner per step.
- [ ] `experiments/pipelines/sprint-final.toml` names one version per step. Run `combine` for the four baselines, each pipeline alone (A, B, C) and the winners combined. Re-run `test_combined_saving_is_below_sum_of_standalone_savings` on real aggregates.

### Task D-2: Dashboard (C, with Shakib as tester)
- [ ] Through `wiring/lever_view.py`:
  - overview of savings;
  - waterfall by cost block (including "other" from F-2);
  - version comparison per step;
  - cache monitor (hits, misses, guard blocks, shadow-check result);
  - routing per bot (ranks);
  - Persian right to left.

  Tests: `test_cache_monitor_counts_match_lever_result`, `test_rtl_for_persian_labels`.
- [ ] The request explorer is in the stretch list (no Langfuse).

### Task E-3: Traceability test (B, Day 3 pm)
- [ ] `tests/architecture/test_lever_traceability.py`:
  - `test_every_experiment_readme_cites_an_id` (regex `FR-|QA-|NG-|H-\d|X\d`);
  - `test_every_lever_id_has_an_experiment_folder`;
  - `test_every_adr_listed_in_docs_index`.
- [ ] Check that the test fails when one ID is removed.

### Task E-4: Decision records (each author, as decided)
- [ ] ADR-0027 (full-data replay), CI, ADR-0018 amendment 2, `LeverResult` and manifest format, **routing without quality labels and the decision rules**, the JEV onboarding (if an adapter or a new family is needed), the `services` extra with the Redis store, Postgres sink and MLflow tracker (one ADR covering the three is acceptable), and one ADR per other added dependency. Use the next free numbers on `main`. Each ADR links its guarding tests.

### Task I-2: Final numbers (A leads, Day 4 am)
- [ ] `reports/levers/final.json`: the waterfall with `AccountingService.decompose` terms, intervals, the four baselines and all slices.
- [ ] `tests/architecture/test_reports_content_free.py`: no text, IDs or hashes under `reports/` (patterns agreed Day 1).
- [ ] **Freeze at 12:00.** After that, only slides, demo data and logged bug fixes.

### Task E-5: Engineering scorecard (Parham, Day 4 am)
- [ ] `scripts/engineering_scorecard.py` writes `reports/engineering_scorecard.json` with counts only: tests, architecture tests, ADRs, contract models with full privacy classes, `module_reference` rows, locked dependencies with hashes, CI status, levers with a manifest.
- [ ] Tests: `test_counts_come_from_the_repo`, `test_output_numbers_and_names_only`.

---

## Services track: Redis, Postgres, MLflow, Docker Compose (team decision)

Each service is an **adapter behind an interface that already exists or is added once**, so the pipeline code does not change ("we added Redis without touching the pipeline"). Default tests never need a running server. Each adapter is tested with a small fake client, and real-server tests are opt-in (`pytest -m services`, run against `docker compose up`).

### Task T-0: The `services` extra and its lock (Parham, Day 1 evening)
**Files:**
- `pyproject.toml`: a new extra `services` with `redis`, `psycopg[binary]` and `mlflow` (or `mlflow-skinny` if the full package conflicts; check the package exists at lock time). Versions are chosen at lock time under `constraints-min-age.txt`. **Shared file**: needs everyone's OK.
- `requirements-services.lock`: the dev lock plus this extra, with hashes, following the `requirements-ui.lock` pattern.
- `pytest.ini_options`: add the `services` marker.
- ADR: services extra and adapters.
- [ ] `pip install --require-hashes -r requirements-services.lock` works on macOS and in CI. `pip check` is clean.
- [ ] `tests/architecture/test_service_imports.py`:
  - `test_redis_imported_only_in_redis_store`;
  - `test_psycopg_imported_only_in_postgres_sink`;
  - `test_mlflow_imported_only_in_mlflow_tracker`.

  This follows the existing rule that `openai` is imported only in `openai_compat.py`.

### Task T-1: Redis `CacheStore` adapter (B, Day 3 pm)
**Files:** `src/metis_auto/adapters/stores/redis_store.py`; wiring switch `cache.store = "memory" | "redis"` in `wiring/from_settings.py`; `config/defaults.toml` keeps `"memory"`. Tests: `tests/unit/adapters/test_redis_store.py` (fake client), `tests/integration/test_redis_store_live.py` (`@pytest.mark.services`).
- [ ] Failing tests:
  - `test_put_then_get_round_trips_a_cache_entry`;
  - `test_missing_key_returns_none`;
  - `test_put_replaces_previous_entry`;
  - `test_store_applies_no_ttl_or_validity_rules` (`ports/cache.py`: stores hold data, policies decide);
  - `test_same_behaviour_as_in_memory_store` (one shared contract test run against both stores);
  - `test_keys_are_namespaced_by_key_version`.
- [ ] Implement `RedisCacheStore(client: RedisLike, *, namespace: str)` with `get(key: Fingerprint) -> CacheEntry | None` and `put(entry: CacheEntry) -> None`. Entries are serialised with the contract's JSON.
- [ ] Done when: the demo chat runs with `cache.store = "redis"`, a second user's greeting is a cache hit read from Redis, and switching back to `"memory"` changes nothing else.

### Task T-2: MLflow tracking of lever results (A, Day 2 evening)
**Files:**
- `src/metis_auto/ports/tracking.py`: `RunTracker` Protocol with `log_result(result: Mapping[str, object]) -> str`, returning the run ID. Plain mapping, because `ports` may not import `analysis`.
- `src/metis_auto/adapters/tracking/mlflow_tracker.py`.
- `scripts/log_levers.py`, which reads `reports/levers/*.json` and logs each one.
- `mlruns/` git-ignored.

Tests: `tests/unit/adapters/test_mlflow_tracker.py` (temporary local file store, skipped if the extra is missing).
- [ ] Failing tests:
  - `test_each_result_becomes_one_run_with_manifest_as_params_and_savings_as_metrics`;
  - `test_logging_twice_the_same_result_is_idempotent_by_lever_id_and_config_hash`;
  - `test_no_text_or_id_reaches_mlflow` (privacy).
- [ ] Done when: the MLflow UI shows every lever run side by side with its data revision, code commit, config hash, seed and price version (E-2).

### Task T-3: Postgres `EventSink` adapter (B, Day 1 pm)
**Files:** `src/metis_auto/adapters/sinks/postgres.py`; `migrations/0001_events.sql` (tables `events` and `lever_results`, content-free columns only); wiring switch `events.sink = "jsonl" | "postgres"`. Tests: `tests/unit/adapters/test_postgres_sink.py` (fake connection), `tests/integration/test_postgres_sink_live.py` (`@pytest.mark.services`).
- [ ] Failing tests:
  - `test_emit_writes_one_row_per_event_in_order`;
  - `test_close_is_idempotent`;
  - `test_sink_failure_raises` (observability §6: offline, a sink failure fails the run);
  - `test_schema_has_no_content_columns`;
  - `test_password_comes_only_from_environment` (`METIS_DB_PASSWORD`, never config).
- [ ] Implement `PostgresEventSink(connect: Callable[[], Connection])` with `emit(event: Event) -> None` and `close() -> None`.
- [ ] Done when: a demo chat session's events appear in Postgres with the same content as the JSON Lines sink.

### Task T-4: Docker Compose, one command (Parham, Day 3 pm)
**Files:**
- `compose.yaml` (exists): add `redis`, `mlflow`, and a `demo` service running `scripts/demo_ui.py`. Postgres already has the `db` profile; move it and the new services into a `services` profile.
- Ports bound to `127.0.0.1` only. Health checks on every service.
- Update `docs/guides/local_development.md` and `docs/guides/demo_quickstart.md`.
- [ ] CI step: `docker compose config -q` (validates the file without pulling images).
- [ ] Done when: `docker compose --profile services up` starts the demo, Redis, Postgres and MLflow on a fresh clone, and the demo uses Redis and Postgres through configuration only.

## Shakib

| Task | What | Needs | Fallback if Shakib is unavailable |
|---|---|---|---|
| K-1 | Hit-correctness review of the top popular-question keys and a sample of hits (EDA X1): "would the stored answer satisfy this request?" | Persian reading; data access; Metis OK to show data to helpers | A reviews 30 items; `correctness_state = "sampled:30"` |
| K-2 | Check the phatic (greeting/thanks) word list | Persian | C keeps the placeholder label |
| K-3 | Language-label sheet `reports/full_eda/review/language_validation.csv` | Persian; data access | stays *unvalidated* |
| K-4 | Demo tester: run the demo script Day 3 pm and Day 4 am, keep a bug list in `sprint-notes.md` | a laptop with the repo | the presenters' first rehearsal |
| K-5 | Slide layout and timing | the talk outline | the presenters |
| K-6 | Metis question tracker: sent, answered, which task it unblocks | email | the O-1 owner |

## Merge and integration rules

- One owner per file, named in `sprint-notes.md`. Shared files (`levers.py`, `lever_result.py`, `compare.py`, `cache_guard.py`, `routing_base.py`, `replay_scope.py`, `sprint.toml`) change only with everyone's OK in chat, made by their owner.
- Merge to `main` every day at 18:00, after CI is green and local `pytest -q` equals the Day 1 baseline plus new passing tests. Humans commit. Merge `main` into your branch; no rebase, no force push.
- Milestones:
  - Day 1 18:00: the shared base merged.
  - Day 2 18:00: all cache and context results.
  - Day 3 18:00: routing results, `final.json` draft and the dashboard.
- Code freeze: Day 4 12:00.

## Presentation (20–30 min; instructors and Metis people)

| Min | Section | Content | Who |
|---|---|---|---|
| 0–3 | Problem | where the money goes; one model carries 65% of cost | A |
| 3–10 | **Engineering** | layers and the import test (CI-red screenshot), contracts with privacy classes, ADRs, manifest and reproducibility, traceability test, offline by default, spend guard, licence-safe reporting, Redis, Postgres and MLflow behind existing interfaces ("added without touching the pipeline"), one `docker compose up`, the scorecard (E-5) | B |
| 10–15 | Three pipelines | the row and column table, shared base, `combine`, one comparison command | C |
| 15–20 | Results | winners per step, combined waterfall with intervals, four baselines, slices, break-even; prompt caching is small (provider caching covers 7.0% of input; the PDF puts its ceiling at about 6–7% of cost) | A |
| 20–22 | Routing and JEV | routing base, per-bot result, JEV result, benchmark result or "not proven" | Parham |
| 22–24 | **What we did not prove** | quality, hit correctness beyond the sample, overhead in production, cross-user caching, retrieval interception; offline savings may look bigger than in production; shadow mode would come next | B |
| 24–29 | Live demo | script below | C |
| 29–30 | Next steps, Q&A | stretch list, Metis answers needed | all |

**Demo script (5 min):**
1. The savings waterfall from `final.json`.
2. Switch one step's version and watch it change.
3. The cache monitor with guard blocks.
4. The per-bot table (ranks, caveats).
5. Chat in fake mode with a cache hit and its cost panel.
6. The budget bars and the refusal at the cap.
7. The MLflow UI: every lever run side by side with its manifest. The cache hit in step 5 is read from Redis, and its events are in Postgres.

**Fallback:** a 90-second screen recording plus `comparison.md` on a slide. The demo runs offline, so the network is never the failure point. If Docker fails, switch the config back to the in-memory store and the JSON Lines sink: same code path, nothing else changes.

## Stretch (ranked by value ÷ cost; trigger; needs the amendment?)

1. **Gemini adapter, thinking A/B on about 300 items, explicit thinking setting, 2.5 replacement.** Trigger: F-1 shows billed output much larger than the answer. Needs an ADR and the amendment (about 5 USD in the PDF).
2. **Semantic retrieval cache.** Trigger: R-B1 passes and replay shows at least 2 more points of fees avoided at agreement ≥ 0.9. Needs an embedding model (licence, GPU).
3. **Nightly paraphrase grouping.** Trigger: R-A1 passes. Free plus review time.
4. **Human Persian labels (250 + 60 double), κ ≥ 0.6, PPI** (Phase 0 plan Tasks 12–13). Trigger: P-2 ran and judge agreement is the weak point.
5. **XProvence sentence pruning.** Trigger: R-A2 wins or passes (about 3 USD).
6. **Explicit Gemini cache per bot.** Trigger: a bot has about 4+ identical-prefix requests an hour and implicit caching misses (about 1 USD).
7. **Cascade with non-LLM checks.** Trigger: the benchmark shows a cheap model passes most but not all structured requests.
8. **Multi-turn drift test** (30–60 conversations, about 2 USD). Trigger: a bot is about to move to a cheaper model.
9. **Offline instruction shortening** (about 2 USD). Trigger: phases 1–3 done.
10. **Embedding and rerank cache.** Trigger: the reranker or kNN ships.
11. **Remaining Phase S services** (Langfuse, Prometheus/Grafana), production Compose profile, load test of added latency. Trigger: after the sprint; one ADR each.
12. **Request explorer.** Trigger: Langfuse exists.

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| `requests.parquet` won't regenerate on a machine | Build it on Kimia's machine; others test on synthetic frames and say "not run on full data" |
| Metis answers late | Retrieval caches and fee findings stay "measured potential"; the paid branch is skipped; the popular-question cache and context still count |
| A version fails or saves nothing | Report the negative result in the same format |
| Amendment not committed by Day 2 12:00 | Paid branch skipped; routing = cost replay; the talk says "quality not proven" |
| Licence forbids APIs, Colab or helpers | No benchmark, no Colab, Shakib's review tasks fall back |
| JEV not callable, not Persian, or price wrong | J-3 still runs as cost only with a "price unverified" label, or JEV is dropped from routing; Parham keeps R-0 and P-* |
| Windows vs macOS | S-0 baseline; Saba's tasks avoid the `fcntl` ledger path; CI runs on Linux and macOS |
| GPU unavailable | R-A2 stays a token-sizing curve |
| Pipelines diverge in format | `StepVersion` and `LeverResult` frozen at 14:00 Day 1; changes need everyone |
| One tenant dominates | 35% cap in every sample; per-tenant and traffic-weighted rows |
| New service dependencies conflict with the locks (MLflow is large) | Try `mlflow-skinny`; if still blocked at the Day 2 12:00 checkpoint, MLflow moves back to stretch and the run records stay file-based (ADR-0022) |
| Docker unavailable on a machine (Saba on Windows) | Services run on one macOS machine for the demo; default tests never need them (fakes); real-server tests are opt-in |
| Unexplained 12% of cost | F-2 before any final share is stated |
| Rebuilt prompts differ from what was sent | Every token saving is labelled *hypothetical reconstruction*; compare the logged answer with the incumbent replay per bot in P-2 |
| `gemini-2.5-flash` retired suddenly | F-1 and stretch item 1 |
| Savings bigger offline than in production | Report against today's models, not only `gpt-5.5`; shadow mode is the first next step |
| Wrong cached answer served many times | Cache guard (approval, blocklist, per-bot off switch), K-1 review |

## Owner-only decisions (deadline)

1. Who is A, B, C (Day 1, 10:00).
2. ADR-0018 amendment 2, caps and the Metis dashboard limit (Day 1).
3. The licence question about APIs, Colab and helpers (send Day 1).
4. ADR-0006 thresholds vs PDF rules (Day 1; default: both).
5. Demo features (Day 1, 18:00).
6. Cut-first items (Day 2, 12:00).
7. scikit-learn as a dependency (Day 2 am; default no).
8. Whether Shakib may see real data (with item 3).

## Superseded files

- `2026-11-01-4-day-sprint.md`: everything in it is included here.
- `2026-11-01-phase-0-foundation.md`:
  - Tasks 1, 4, 5 and 10 are done by the EDA (S-0 replaces them).
  - Tasks 2–3 are now S-3.
  - Task 6 is cut-first (c).
  - Tasks 7–9 are verified in S-0 or are inside R-B1/R-C1, apart from the hidden-rewriter check (cut-first b).
  - Task 11 is F-1.
  - Tasks 12–13 are stretch item 4.
  - Task 14 is O-1.

---

## Self-review

- **Spec coverage:** the PDF coverage map points every PDF section to a task, a tier or the stretch list. Everything from the sprint plan is carried over. The four gaps you approved are in: measurement rigour (decision rules, four baselines, slices, 35% cap: S-2, S-3), cache safety (S-5), the free Gemini check and cost trace (F-1, F-2, prompt-caching slide), and overhead and decision notes (L-1, N-1, risks).
- **Placeholders left on purpose:**
  - who is A, B and C (team decision, Day 1);
  - the cost-block column names (confirmed in S-3);
  - ADR numbers (next free on `main`);
  - JEV facts (J-1).
- **Type consistency:** `StepVersion`, `ReplayContext`, `combine`, `LeverResult`, `Manifest`, `CacheGuard` and `eligible_models`/`failover` are defined once and used with the same names in every task.
- **Proportion:** about 40 tasks for about 16 person-days (four builders plus opti); signatures and test names only, no bodies.
- **Unverified here:**
  - the exact cost columns in `requests.parquet`;
  - whether the Metis wrapper serves JEV through the OpenAI-compatible format;
  - JEV's output price of 0.0000;
  - whether the claims ledger already answers the hidden-rewriter and chunk-carried checks.
