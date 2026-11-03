# Pipeline B: decision notes per step (sprint task N-1)

Status: **B's versions only**, 2026-11-02; **updated 2026-11-03** (logged-model prices ADR-0041, R-B3 on the routing base ADR-0045 with per-baseline accounting ADR-0046 points 4 to 6, one report-split run per version, overhead measured). This file feeds the team's Day 3 decision; it declares **no cross-pipeline winner**. The team picks one version per step with the plan's decision rules ([final plan](../2026-11-01-final-plan.md), "Decision rules"). A shared `docs/experiments/sprint_decisions.md` exists on no branch (checked 2026-11-02), so this is a separate file with one block per step that can be copied into it.

Common to every block: tune period March–July 2026 (`a_timestamp`, naive, Q-06); fitted values and tune results on `split_by_session == "tune"` rows unless stated (ADR-0036); settings frozen on tune before **one report-split run** per version (owner decision 2026-11-03; report split 73,063 requests, 20,750 LLM, the same scope as A's report results); workflow rows never count; recorded and price-file units are never mixed; unknown is never 0; `code_commit` 9f05b25. Overhead (L-1): offline per-request estimates from `scripts/measure_pipeline_b_overhead.py` (tune-period sample; ADR-XXXX (pipeline-b-lever-overhead)), per block below.

## Cache: R-B1 retrieval-result cache (`exp-cache-002`)

| | |
|---|---|
| Tried | Reuse a retrieval lookup's chunks for the same tenant + bot + settings + `normalize_safe` query within a backstop TTL of 1, 7, 30 or 90 days; tenant = requesting user (bot-owner scope as a sensitivity); no TTL gives no hits (no corpus-version evidence in the log). |
| Data shows | TTL rule (agreement ≥ 0.9 with at least half the hits evaluable) picks **1 day** (frozen as the stated default): mean agreement 0.976. Tune: fee avoided 3.31% of the fee block, **1.09% [0.96, 1.23]** of recorded LLM cost (session-clustered). **Report split (one run, tune rows may warm the cache as R-A1's window): 1.37% [1.26, 1.49]** of recorded LLM cost, 3.00% of the fee block, mean agreement 0.985 over 991 hits. Agreement falls with age (0.89 at 7 days, 0.60 at 90) while chunk text barely changes (0.45% of chunk IDs). All of the saving comes from one tenant (rank 4). |
| Evidence class | *simulation*; **measured potential**, conditional on Metis-Auto being able to intercept retrieval (open Metis question). Candidate reuse only. |
| Unit and baseline | Recorded units, `as_logged` (fee block = recorded `costBreakdown.per_call`). Against the three repriced baselines: **not computed** (they have no fee block). |
| Decision rule | Retrieval versions: agreement with the later real lookup ≥ 0.9. **Passes at 1 day** on the predeclared metric (mean Jaccard of `(chunk_id, content_hash)` sets). |
| Open question | Can Metis-Auto sit in front of retrieval? Is retrieval sometimes free or billed elsewhere (34,569 of 91,807 tune lookups have no per-call item, Q-B19)? `served_from_cache` stays false for a retrieval reuse (P-B1, `combine` owner). |
| Blocked | The shared waterfall entry until P-B1 is confirmed by the `levers.py` owner (Pipeline A). The accounting decision (slug `retrieval-result-cache-accounting`) is ADR-0037 on `main` since #21 (80b17b2); on this branch it is still the draft until `main` is merged. |

## Context: R-B2 cross-turn chunk policy (`exp-ctx-002`)

| | |
|---|---|
| Tried | Drop a chunk (same session, same user + bot scope, same content hash) assumed already visible from an earlier turn, replaced by a pointer (8 or 16 tokens) or an append-only session ledger; visibility windows 0 (conservative default: nothing visible), 1, 3 or all earlier turns. Within-message copies left to S-6. |
| Data shows | Conservative default (`k` = 0, frozen default) saves **0**, tune and report. Hypothetical windows: **5.08%** (k ≤ 1), **6.86%** (k ≤ 3), **7.86%** (all earlier turns) of the recorded token-cost block (tune summary). As a share of recorded LLM cost (`as_logged` result): k ≤ 1 2.51% tune, **4.10% report (stated scenario, one run)**; `todays_models` 3.90% tune, 3.41% report (price-file units). No interval is computed for R-B2. |
| Evidence class | *hypothetical reconstruction*; tokens only, **quality not measured** (the history policy that decides what the model saw is unidentified, EDA §2). |
| Unit and baseline | Recorded units against `as_logged` (net tokens × the request's recorded ordinary input rate); price-file units against the three repriced baselines (baseline re-priced before minus after). |
| Decision rule | Context: needs loss rate − win rate within noise + 3 points, no group 10 points worse, and no worse JSON validity, language or refusal rate. Without the paid ablation (cut-first d) the result is **"tokens only, quality not measured"**: the rule **cannot be passed**. |
| Open question | Which visibility assumption matches what the model saw (needs Metis or the ablation)? S-6 must count within-message duplicates by the same first-occurrence rule (Q-B18). Shared name of the context column (P-B3). |
| Blocked | Any claim beyond the conservative default needs the history policy or the ablation. |

## Routing: R-B3 kNN router, nearest-profile policy (`exp-route-011`)

Decision record: [ADR-0048](../adr/0048-knn-router-nearest-profile-routing.md) with Amendment 1 (2026-11-03): eligibility from the shared routing base ([ADR-0045](../adr/0045-routing-base-eligibility-and-failover.md)), per-baseline accounting as R-A3 and R-C3 ([ADR-0046](../adr/0046-small-classifier-routing.md) points 4 to 6; Q-B21 answered for Pipeline B).

| | |
|---|---|
| Tried | For each request, the `k` nearest tune profiles (never its own session or duplicate family); the cheapest eligible candidate those neighbours ran; never upward; `k` in {5, 15, 50}, default by the predeclared least-aggressive criterion in session/family-grouped nested CV inside the tune split. Primary candidates `gpt-4.1-nano`, `gpt-4o-mini` (reasoning-billed models left out); secondary `with_reasoning_models` with all five. |
| Data shows | **k = 5 frozen** (all 5 outer folds). Tune: 9,513 of 209,331 LLM requests moved (4.54%), `todays_models` **16.74% [14.13, 19.74]**, `as_logged` 12.05% [10.16, 14.45]. **Report split (one run): 2,920 of 20,750 moved (14.07%), `todays_models` 2.25% [1.90, 2.74], `as_logged` 2.46% [2.18, 2.86]**, `premium_gpt_5_5` 3.34% [2.86, 3.88], `best_single_cheap` 0 (its model, `gpt-5-nano`, is cheaper than every candidate). Unpriced incumbents: 0.1% of tune LLM rows (was 57.3% before ADR-0041). |
| Evidence class | *simulation*; **cost simulation; quality not proven**. |
| Unit and baseline | Each baseline in its own units with its own model as the incumbent: price-file units for the three repriced baselines, recorded units for `as_logged` (target at implied recorded rates; 14 report requests unknown, out of both sides). |
| Decision rule | Routing: move a bot only if its acceptable rate is within 10 points of the incumbent (needs labels: **cannot be passed**). The plan's "keep a more complex router only if it beats per-bot reassignment outside the CI": on the report split R-B3 is **below** R-A3 (`route.per_bot`, `todays_models` 6.28% [5.03, 7.49]) outside the interval in every baseline, so it does not pass. No winner picked here. |
| Open question | I-2 still needs the team-wide confirmation of ADR-0046 point 6 that ADR-0046 and ADR-0051 ask for. Overhead p95 is far above the 100 ms target (see the overhead block) because `apply` rebuilds training-side indexes per call. |
| Blocked | Any quality claim until P-1…P-3 run. |

## Combined (B only, I-1 dry run)

Tune split, R-B1 1-day TTL + R-B2 + R-B3 k = 5 (primary candidates), `code_commit` 9f05b25. Each step's own effect per baseline, so the parts add (see [`experiments/pipelines/b-only-dry-run/README.md`](../../experiments/pipelines/b-only-dry-run/README.md)). Recorded units (`as_logged`, baseline 327.779): combined **50.235 (15.33%)** with R-B2's stated scenario (cache 3.580 + context 7.657 + routing 38.998 at implied rates); 42.816 (13.06%) with R-B2's conservative default. Price-file units against today's models: context + routing **45.676**, below the 45.871 standalone sum (1,289 requests touched by both are routed on fewer tokens). As `combine` is today, routing reprices the pre-context tokens and the combined figure counts that overlap twice (Q-B20, `combine` owner, Pipeline A). Overlaps: cache & context 1,414, context & routing 1,289, cache & routing 224, all three 193. No winner picked.

## Overhead (L-1, offline per-request estimate)

`scripts/measure_pipeline_b_overhead.py` ([ADR-XXXX (pipeline-b-lever-overhead)](../adr/draft-pipeline-b-lever-overhead.md)): `apply` on one-row frames, 987 seeded tune-period, tune-split LLM rows (tenant cap 0.35), one warm-up, Intel i5 laptop; not a load test (Q-14). Pipeline A's R-A3 figure (54.2 ms p95) used report-period rows, so the samples differ. Target: 100 ms p95 (QA-LAT).

| Version family | p50 | p95 | Target |
|---|---|---|---|
| R-B1 (four TTLs) | 6.2–6.3 ms | 7.5–7.6 ms | pass |
| R-B2 (eight scenarios) | 7.5–7.7 ms | 8.8–9.8 ms | pass |
| R-B3 primary (k = 5, 15, 50) | 375–389 ms | 422–439 ms | **fail** |
| R-B3 `with_reasoning_models` | 395–404 ms | 422–516 ms | **fail** |

R-B1 and R-B2 on a one-row frame hold no earlier state (no warm store, no earlier turn), so they time the decision path only. R-B3's figure is dominated by rebuilding training-side session and family indexes on every call (about 76% in a profile), not by the neighbour search; moving that to fit time is a follow-up.
