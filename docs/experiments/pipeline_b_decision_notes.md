# Pipeline B: decision notes per step (sprint task N-1)

Status: **B's versions only**, 2026-11-02. This file feeds the team's Day 3 decision; it declares **no cross-pipeline winner**. The team picks one version per step with the plan's decision rules ([final plan](../2026-11-01-final-plan.md), "Decision rules"). A shared `docs/experiments/sprint_decisions.md` exists on no branch (checked 2026-11-02), so this is a separate file with one block per step that can be copied into it.

Common to every block: tune period March–July 2026 (`a_timestamp`, naive, Q-06); fitted values and results on `split_by_session == "tune"` rows unless stated (ADR-0036); the report period is **not read**; workflow rows never count; recorded and price-file units are never mixed; unknown is never 0. Overhead (L-1): **not measured**: `scripts/measure_lever_overhead.py` (Pipeline A) reached `main` in #23 (f44d84f, blob 3a766bc) after the B runs. Borrowed read-only and dry-run on one R-B1, R-B2 and R-B3 `lever_id` each: it stops with "no known version" (it builds only R-A1 and R-A2 versions), and it samples report-period rows, which this session does not read. No substitute was written; the `overhead_ms_*` fields stay empty, never 0.

## Cache: R-B1 retrieval-result cache (`exp-cache-002`)

| | |
|---|---|
| Tried | Reuse a retrieval lookup's chunks for the same tenant + bot + settings + `normalize_safe` query within a backstop TTL of 1, 7, 30 or 90 days; tenant = requesting user (bot-owner scope as a sensitivity); no TTL gives no hits (no corpus-version evidence in the log). |
| Data shows | TTL rule (agreement ≥ 0.9 with at least half the hits evaluable) picks **1 day**: mean agreement 0.976. Fee avoided 3.31% of the fee block, **1.09% [0.96, 1.23]** of recorded LLM cost (session-clustered). Agreement falls with age (0.89 at 7 days, 0.60 at 90) while chunk text barely changes (0.45% of chunk IDs). All of the saving comes from one tenant (rank 4). |
| Evidence class | *simulation*; **measured potential**, conditional on Metis-Auto being able to intercept retrieval (open Metis question). Candidate reuse only. |
| Unit and baseline | Recorded units, `as_logged` (fee block = recorded `costBreakdown.per_call`). Against the three repriced baselines: **not computed** (they have no fee block). |
| Decision rule | Retrieval versions: agreement with the later real lookup ≥ 0.9. **Passes at 1 day** on the predeclared metric (mean Jaccard of `(chunk_id, content_hash)` sets). |
| Open question | Can Metis-Auto sit in front of retrieval? Is retrieval sometimes free or billed elsewhere (34,569 of 91,807 tune lookups have no per-call item, Q-B19)? `served_from_cache` stays false for a retrieval reuse (P-B1, `combine` owner). |
| Blocked | The shared waterfall entry until P-B1 is confirmed by the `levers.py` owner (Pipeline A). The accounting decision (slug `retrieval-result-cache-accounting`) is ADR-0037 on `main` since #21 (80b17b2); on this branch it is still the draft until `main` is merged. |

## Context: R-B2 cross-turn chunk policy (`exp-ctx-002`)

| | |
|---|---|
| Tried | Drop a chunk (same session, same user + bot scope, same content hash) assumed already visible from an earlier turn, replaced by a pointer (8 or 16 tokens) or an append-only session ledger; visibility windows 0 (conservative default: nothing visible), 1, 3 or all earlier turns. Within-message copies left to S-6. |
| Data shows | Conservative default saves **0**. Hypothetical windows: **5.08%** (k ≤ 1), **6.86%** (k ≤ 3), **7.86%** (all earlier turns) of the recorded token-cost block. |
| Evidence class | *hypothetical reconstruction*; tokens only, **quality not measured** (the history policy that decides what the model saw is unidentified, EDA §2). |
| Unit and baseline | Recorded units against `as_logged` (net tokens × the request's recorded ordinary input rate); price-file units against the three repriced baselines (baseline re-priced before minus after). |
| Decision rule | Context: needs loss rate − win rate within noise + 3 points, no group 10 points worse, and no worse JSON validity, language or refusal rate. Without the paid ablation (cut-first d) the result is **"tokens only, quality not measured"**: the rule **cannot be passed**. |
| Open question | Which visibility assumption matches what the model saw (needs Metis or the ablation)? S-6 must count within-message duplicates by the same first-occurrence rule (Q-B18). Shared name of the context column (P-B3). |
| Blocked | Any claim beyond the conservative default needs the history policy or the ablation. |

## Routing: R-B3 kNN router, nearest-profile policy (`exp-route-011`)

| | |
|---|---|
| Tried | For each request, the `k` nearest tune profiles (never its own session or duplicate family); the cheapest eligible candidate those neighbours ran; never upward; `k` in {5, 15, 50}, default by the predeclared least-aggressive criterion in session/family-grouped nested CV inside the tune split. |
| Data shows | Default **k = 5** (chosen by all 5 outer folds): 3,692 of 209,331 LLM requests moved (1.76%), saving **0.70% [0.54, 0.89]** of today's-model cost on the 88,971 rows it can price (k = 15: 1.79%, k = 50: 3.55%, reported, not chosen). 57.3% of LLM rows run on an unpriced model and are untouched (unknown, not 0); the largest bot is one of them. Against `best_single_cheap` the saving is −131%: one cheap model everywhere costs less, ignoring constraints and quality. |
| Evidence class | *simulation*; **cost simulation; quality not proven**. Eligibility is **interim**, not the shared routing base: results stay out of any final comparison. |
| Unit and baseline | Price-file units against `premium_gpt_5_5`, `todays_models`, `best_single_cheap` (baseline cost minus routed cost; the router's own effect is the `todays_models` figure). `as_logged`: **not computed**. |
| Decision rule | Routing: move a bot only if its acceptable rate is within 10 points of the incumbent (lower 95% bound, judge-corrected). No quality label exists, so the rule **cannot be passed**. Supervised use is **blocked**: no benchmark labels with provenance on any branch (P-2/P-3), and golden-v2 labels are provisional rule labels. |
| Open question | `routing_base.eligible_models` (R-0) to replace the interim eligibility; candidates `gpt-5-nano` (3 tune rows) and `mimo-v2.5` (9) are almost never logged, so a nearest-profile policy almost never reaches them; most logged traffic runs on unpriced models (unknown, not routed). |
| Blocked | Final routing numbers until R-0 lands; any quality claim until P-1…P-3 run. |

## Combined (B only, I-1 dry run)

Tune split, R-B1 1-day TTL + R-B2 + R-B3 k = 5. Recorded units: combined **11.237 of 327.779 (3.43%)** with R-B2's stated scenario (k ≤ 1), equal to R-B1 + R-B2 (different blocks); 3.580 (1.09%) with R-B2's conservative default. Price-file units, over the 88,971 rows routing can price: context + routing **0.888** against today's models, below the 0.890 standalone sum (43 requests touched by both). As `combine` is today, routing reprices the pre-context tokens and the context saving vanishes (0.190 = routing alone). Overlaps: cache & context 1,414, context & routing 43, cache & routing 9. The units allow cache + context in recorded units and context + routing in price-file units, never all three in one unit. How `combine` should pass R-B2's reduced tokens to routing is a design question for the `combine` owner (Pipeline A): see [`experiments/pipelines/b-only-dry-run/README.md`](../../experiments/pipelines/b-only-dry-run/README.md).
