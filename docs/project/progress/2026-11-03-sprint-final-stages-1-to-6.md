## Sprint final: comparable candidates, rules-only decision router, decisions, combined run, final numbers (2026-11-03 to 2026-11-04)

Branch `sprint-final-pipelines` (from `main` 589c0d0). Rule zero held for the whole task: no live, hosted or paid call, no spend-ledger write, no change to caps or approvals. Stage 0 is in [2026-11-03-sprint-final-stage-0-verify-and-plan.md](2026-11-03-sprint-final-stage-0-verify-and-plan.md). Deadline moved to Wed 2026-11-04 12:00 (Tehran). Updated as the work goes.

### Stage 1: comparable candidates

- **`config/evaluation/sprint.toml`** (shared file, owner approval 2026-11-03; Pipeline C to confirm): `gpt-4.1-nano` and `mimo-v2.5` removed from `[routing] candidates` (not callable: HTTP 404, HTTP 400). Candidates are now `gpt-5-nano`, `gpt-4o-mini`, `deepseek-v4-flash`; the primary set (reasoning-billed models out) is `gpt-4o-mini` alone.
- **New `analysis/lever_enrich.py`** (13 tests, failed first): adds a result's missing slices (`lang:*`, `over_8k`, `tenant_rank:*`, `traffic_weighted`) and its session-clustered interval from the same before/after frames; refuses an interval unless the rows reproduce the result's own share; keeps existing slices and intervals; states in `assumptions` any family it cannot compute (missing column).
- **Wired into Pipeline C's runners** (`context_dedup_levers`, `history_budget_levers`, `session_memo_levers`, `small_classifier_levers`), which also read `u_lang` (and `user_id` for dedup). Re-run on the splits they already used with unchanged settings (not a second look): dedup, history budget (4 variants), session memo. Savings equal the committed results in all 24 files; only slices, intervals and the enrich note changed.
- **L-1 targets** added to `scripts/measure_lever_overhead.py` (A's script) for dedup, history budget, session memo and the small classifier (4 tests, failed first; dry run on 200 rows: p95 18.8, 25.9, 24.5, 39.8 ms, all under 100 ms).
- Local, git-ignored, content-free tables derived with the existing scripts: `data/derived/cache/rag_query_fingerprints.parquet`, `data/derived/routing/turn_intent_flags.parquet`.

### Stage 2: decision router, rules-only (`router.mode = "off"`)

- **New** `experiments/routing/exp-route-013-decision-router/rules_only.py` (10 tests, failed first): tiers from the real domain `DecisionRouterPolicy.decide_tier` with no decision result (gate, rule-based fallback, safe tier), once per distinct feature tuple; `require_offline` refuses unless `router.mode == "off"`, no hosted approval, no unpriced router calls and `live.enabled` false; no network or adapter import (tested). Settings load hermetically (no `.env`).
- `version.py` `DecisionRouterRouting.apply` now also returns `route_target` and `route_target_cost` (the tier's cheapest eligible candidate, kept whether or not the row moves), so each baseline makes its own strict-cheaper test (test failed first).
- **New** `scripts/decision_router_levers.py` (`derive`, `run --split tune|report`; 9 tests, failed first). Flags (`has_code`, `has_coding_intent`, `is_greeting`) come from one local in-memory pass over raw user text (355,965 messages, 97 s), written without text to git-ignored `data/derived/routing/decision_router_flags.parquet`. Per-baseline accounting reuses R-C3's `baseline_frames` unchanged (ADR-0046 points 5 and 6). `LeverResult`s: `route.decision_router.rules_only.<baseline>` (report) and `.tune.<baseline>`.
- Results (cost simulation, quality not proven; primary candidates; one report-split run, no tuned value): tune `todays_models` 49.7% [42.6, 55.9]; report split (73,062 requests after the period filter, 20,750 LLM) `todays_models` 17.8% [16.4, 19.4], `as_logged` 21.9% [20.9, 23.3], `premium_gpt_5_5` 28.4% [25.7, 30.9], `best_single_cheap` 0. Almost all traffic takes the safe tier (1), whose only primary candidate is `gpt-4o-mini`, so this is mostly "move to `gpt-4o-mini`" and says nothing about quality.
- Assumptions in every result: quality not proven; rules-only, THX-01 changed no decision on the dev slice (agreement 1.0, A-121); Jev 72% on 100 synthetic requests is not evidence on real traffic.
- Cost estimates for the paid quality run: `scripts/benchmark.py plan` and `scripts/sampling_plan.py` were run in their no-call mode. Both report the estimate as not computed (owner values unset: `generation.max_output_tokens`, `judges.models`; golden-v2 database not used); "estimate not computed" stands.

### Stage 1, completed (re-runs, enrichment, overhead)

- **Candidate change re-runs** (owner: drop `gpt-4.1-nano`, `mimo-v2.5`): per-bot reassignment re-run (70 s; `todays_models` 3.74% [3.03, 4.48], was 6.28%); C's small classifier `rules`, `strict`, `strict_unknown_blocked` re-run (13 and 17 s; the tune check still chooses `MAX_INPUT_TOKENS` 16,000, so no setting changed); decision router (Stage 2). The report-split read of per-bot and the classifier is a second look at that split because the candidate list changed.
- **Not re-run, labelled not re-run with the new candidate list:** B's kNN router (`rb3` tune run stopped after 29 minutes against a 16-minute estimate; all `rb3.*` files, `k5` report, `k15`/`k50`, `with_reasoning_models` keep their old figures and their old candidate list, which includes the two retired models).
- **Re-runs with unchanged settings and the current `-logged` prices (not a second look):** A's popular question (3 min) and `rc-v1 observed_relevancy` (4 min); B's retrieval cache `ttl_1d` and cross-turn chunks report runs (75 and 31 s); C's dedup, history budget, session memo.
- **Enrichment (`analysis/lever_enrich.py`) now wired into** A's popular-question (recorded and repriced, the latter from per-row repriced cost) and reranker-cut runners and B's retrieval-cache and cross-turn helpers (recorded-unit result only: enriching a repriced result with recorded frames would mix units). Their repriced results keep "saving not computed" and say which slices are absent. The enrichment notes were reworded to plain language (the page test refuses identifier-like names) and rewritten in 71 result files; text only, no figure changed.
- **Overhead (L-1)**, p95, report-period sample unless stated: dedup 25.1 ms, `rc-v1` 52.8, popular question 36.8 (first turn) and 32.0 (all turns), per-bot 36.1, decision router 25.5; B (tune sample): retrieval cache 16.4, cross-turn `k1` 17.9. All under the 100 ms target. Not measured (non-winners): session memo, history budget, classifier (targets exist, dry-run only), kNN (old figure, 422 ms, fails).
- `compare_levers.py` (2026-11-03, before the final re-runs): 172 results, 1 skipped file (`pipeline_b_overhead.json`), 24 "duplicate version" flags (both popular-question variants carry the version string `pq-v1`), 58 "insufficient evidence" rows (repriced retrieval-cache and memo results, by design), 97 tenant-share flags (over 35%), no missing baseline. It is re-run at the end.

### Skipped, with the reason (user rules for the shortened deadline)

- kNN `rb3` tune and report re-run (over 1.5x its estimate); `with_reasoning_models`, kNN `k15`/`k50`, `strict_unknown_blocked` overhead and slices (non-winners).
- `rc-v1 lexical_overlap` (2,000-request sample): not re-run, excluded from the combined run.
- Overhead of the session memo, history budget and classifier; extra slices on non-winners.
- Services track T-0, T-2, T-4 (see the Stage 6 section).

### Stage 3: decisions

`docs/experiments/sprint_decisions.md`: provisional winners (cost only, pending quality): cache B retrieval-result cache `ttl_1d` (agreement 0.985 passes), context C within-message dedup, routing the rules-only decision router; runners-up A popular question, B cross-turn `k1`, A per-bot. The quality-run plan is written and **not run**; its cost estimate is "not computed" (owner values unset; both planning commands were run in no-call mode). The winners and the quality-run list were put to the owner as a Stage 3 decision.

### Stage 4: combined run (I-1)

- `experiments/pipelines/sprint-final/run.py` (engine, 13 tests), `experiments/pipelines/sprint-final.toml`, `scripts/run_sprint_final.py` (7 tests), `reports/pipelines/sprint-final/summary.json`. Population: the report split, 73,063 requests (20,750 LLM), history rows 349,078.
- Method fixes found by the smoke run and the sum rule, kept as tests: a step's combined part is its **marginal** effect in the order cache, context, routing (otherwise each part contains the others'); a context version that prices its recorded saving outside `apply` (`rc-v1`) must also lower the recorded cost routing sees.
- `PostContextRouting` stays a stated wrapper in the experiment folder; `levers.combine` is unchanged (the owner question is open, the default taken).
- Draft ADRs: `0061-sprint-final-combine-and-units.md`, `0058-rules-only-decision-router-replay.md`.

### Stage 4 results and Stage 5 (final numbers)

- Combined run, report split, one read, frozen settings; all five pipelines ran (B took 22 minutes; the first run was lost to the usage limit and B re-run alone, `--only` now merges into the summary). Sum rule held in every cell; answer-cache-served rows untouched; retrieval reuse rows never `served_from_cache`.
- Share of the baseline (`as_logged` / `todays_models`): A 5.4% / 6.1%, B 7.8% / 5.6%, C 10.6% / 9.1%, Parham (router alone) 21.0% / 17.8%, **winners 27.1% / 22.9%**. Provisional: cost only, pending quality. Details in `docs/experiments/sprint_decisions.md`.
- `reports/levers/final.json` (format `final-v1`, built by `scripts/build_final_numbers.py` through `analysis/final_numbers.py`, 10 tests): waterfall per pipeline and baseline, F-2's unexplained "other" (0.43% of recorded cost in the report period, 11.7% over all data), every result's interval, correctness state, overhead and slices, units caveat in words. No combined interval (steps overlap).
- Dashboard: `lever_view.load_final` / `final_view` and a "Combined pipelines" section on the Results page (10 tests; strings in fa and en, Persian `[PLACEHOLDER: Persian review]`). Rendered offline in fake mode; screenshot: `/Users/kimiakayvan/.claude/projects/-Users-kimiakayvan-Desktop-Metis-metis-auto/56812d98-bce4-42df-a814-94a282ab73fe/tool-results/mcp-Claude_Browser-blob-1793728217220-4a9aw6.jpg` (outside the repo).
- `tests/architecture/test_reports_content_free.py`: Arabic-script and UUID ban over the whole of `reports/`; no identifier key and no hex string except manifest fields in `reports/levers` and `reports/pipelines`; planted fixtures first (they failed against an empty checker).
- Draft ADR added: `0057-results-dashboard-final-v1.md` (amends ADR-0050 point 5). The numbering and the `adr_finalize` / progress-index merge steps stay with the merger.

### Stage 6 (engineering track)

- **E-3** `tests/architecture/test_lever_traceability.py` (6 tests; planted removals are caught). A README for `experiments/pipelines/sprint-final/` was added so every experiment cites an ID.
- **E-5** `scripts/engineering_scorecard.py` → `reports/engineering_scorecard.json` (4 tests): 107 of 107 contract models fully classified, 56 numbered ADRs and 3 drafts, 172 lever results all with a manifest, 48 pinned dependencies with 943 hashes.
- **F-1** `experiments/cost/exp-cost-001-gemini-thinking/` (8 tests, `scripts/gemini_thinking_check.py`, `reports/cost/exp-cost-001/summary.json`): `gemini-2.5-flash` median ratio 1.15 (ordinary) but p90 53.5 against 1.4 for its peers: a heavy tail, not typical hidden thinking (hypothetical reconstruction). Cached tokens are logged (no logging gap).
- **T-0, T-2, T-4 (services): not started**, as the shortened deadline allows. T-0 needs the `pyproject.toml` diff approved first (see the final message). No lock was written.

### Checks at the end

`ruff check` and `ruff format --check` clean; `tests/architecture` green except the known git `init -b` test; full `pytest -q`: 3 known failures (tokenizer assets ×2, git `init -b`), 2,437 passed, 40 skipped. No live, hosted or paid call was made; the spend ledger was not touched.
