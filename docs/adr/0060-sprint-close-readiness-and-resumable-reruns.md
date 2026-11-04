# ADR-0060: Paid checks refuse until every owner value is set; the real reranker needs owner-pinned weights; slow offline re-runs are block-cached and resumable

- Status: **provisional** (sprint close, 2026-11-04; the engineering is tested offline, nothing paid or GPU-bound has run). Points 1, 2 and 4 need the owner's confirmation.
- Date: 2026-11-04
- Relates to: [ADR-0018](0018-live-calls-for-development-under-a-lifetime-budget.md) (amendment 3: 92 USD ceiling), [ADR-0053](0053-paid-benchmark-p1-p3.md) (paid benchmark), [ADR-0040](0040-reranker-cut-and-lever-overhead.md) (reranker cut), [ADR-0032](0032-lever-result-and-manifest-format.md) (result format), ADR-0059 (optional heavy dependencies stay optional); FR-EVAL-04, FR-CTX-02, QA-COST, QA-REPRO, H-2, H-1, H-3.
- Code: `evaluation/benchmark/plan.py` (`estimate_gaps`, `total_estimate`), `evaluation/benchmark/quality_checks.py`, `evaluation/sampling/readiness.py`, `wiring/benchmark.py` (`record_ids`), `scripts/benchmark.py`, `scripts/sampling_plan.py`, `adapters/rerankers/`, `scripts/fetch_reranker_assets.py`, `config/reference/rerankers.toml`, `analysis/resumable.py`, `experiments/routing/exp-route-011-knn-router/version.py`, `scripts/run_pipeline_b_day3.py`, `scripts/small_classifier_levers.py`.

## Context

The sprint left three things unready: the paid benchmark (P-1 to P-3) and the two paid quality checks of cut-first item (d) had never been planned with a computed estimate, the real `bge-reranker-v2-m3` run (cut-first (a)) had no path that respected the weights rule and the licence question (O-1, unanswered), and the slow tune re-runs (kNN `k15`/`k50`, classifier variants) had to be redone from scratch after an interruption (the kNN run was stopped after 29 minutes).

## Decision

1. **A computed estimate exists only when every owner value is set.** `scripts/benchmark.py plan --estimate --with-db` and `scripts/sampling_plan.py --strict` refuse, listing each `set by owner: <key>`, while any of `run.hard_cap_usd`, `run.max_output_tokens`, `run.order_seed`, the judge values, the label values or the spend-share values is unset. The values stay commented-out `[OWNER-PLACEHOLDER]` entries in `config/evaluation/benchmark.toml`, and a test expects them unset in the committed file: no code or default fills them.
2. **The main 300-record run is the same code with `--scope main`** (every golden-v2 record; the pilot stays the default). It has a synthetic test only and has not run against the database. The gate text names ADR-0018 amendment 3.
3. **Cut-first (d) has inputs and an estimate, not a runner.** `quality_checks.py` builds the E5 pairs (stored answer against the hit's logged answer; context version against original, same arm) and the E4 generation calls, and bounds cost from counted sizes. Both plan commands sit behind the benchmark's gates and the O-1 answer. No judging or generation is wired to run them.
4. **The real reranker is opt-in, local-GPU-only and pin-gated.** `bge_reranker_v2_m3` is an injected scorer built by `adapters/rerankers/bge_local.py` (the only reranker importer of `torch`/`transformers`; the `compress` extra). The model's revision and sha256 pins in `config/reference/rerankers.toml` are owner placeholders (no value was checked or invented); `fetch_reranker_assets.py` and the run both refuse while unpinned, missing or mismatching, and the run refuses before reading data. Weights go to git-ignored `data/rerankers/`. CPU is refused. Nothing is uploaded.
5. **Slow offline re-runs are block-cached and resumable.** The kNN neighbour search is stored in blocks of 20,000 queries under `runs/knn_cache/`, keyed by a hash of the training matrix, the query set and `k`; the second candidate list of one run reuses it, and an earlier run's blocks are read only with `--resume`. `--max-minutes` stops a search whose estimated time left is over the budget. The classifier script keeps a ledger per version (same settings key only). The cache changes no result (tested).

## Alternatives considered

- **Fill the placeholders with plausible defaults.** Rejected: they are the owner's budget and judge choices (Q-62 to Q-64); a default would look like a decision.
- **Pin the reranker from memory of the model card.** Rejected: a wrong hash or revision is worse than none (never fabricate).
- **Cache whole variants instead of neighbour blocks.** Rejected: the expensive step is shared by the variants, and a block cache also survives an interruption inside one search.
- **Run the reranker on CPU as a fallback.** Rejected: hours on 2,000 turns; the plan says local GPU.

## Consequences

- The owner can see a real estimate as soon as the placeholders are set, and cannot start a paid run without it.
- A kNN tune re-run costs the search once; later runs and the second candidate list are cheap. Cache files hold row positions only and live in git-ignored `runs/`.
- Heavy reranker dependencies stay optional; the repo has no path that downloads weights without pins.
- Still open: Metis's written answer (O-1), the owner values, the reranker pins, a GPU run, `docker compose --profile services up`, K-1 to K-6 (`docs/project/sprint_open_items.md`).
