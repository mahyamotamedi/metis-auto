## Sprint Day 3, Pipeline A: R-A1 and R-A2 today's-models results repriced with the replay prices (2026-11-03)

Plan: [`2026-11-01-final-plan.md`](../../superpowers/plans/2026-11-01-final-plan.md), Day 3 Part 0. Branch `per-bot-reassignment-day3`, from `origin/main` 37262d4 (contains #28, the replay prices of [ADR-0041](../../adr/0041-replay-pricing-for-logged-models.md)). **Awaiting review.**

- **Why:** the R-A1 and R-A2 `todays_models` results were written with the test catalogue and `prices-metis-2026-10-18-s75-g55`, which do not price `gemini-2.5-flash`; they covered 4,919 of 24,609 report LLM requests. `sprint.toml [baselines]` now names `catalogue-metis-replay.toml` and `prices-metis-2026-10-18-logged.toml`.
- **How:** `scripts/run_popular_question.py --no-sheet` and `scripts/run_reranker_cut.py` re-run into a scratch folder (neither script can write one baseline alone); only the six `*todays_models.json` files and `context.reranker_cut.curve.csv` (priced at `todays_models`) were copied into `reports/levers/`. Every other result file was compared field by field: no figure changed, only `price_version`/`config_hash` (the price-file path is in the config) and the assumption lines that L-1 adds, so those files were left as they were. The K-1 sheet was not touched; R-A1 first_turn keeps `correctness_state` `sampled:30`. Headline points of R-A2 did not move (observed top_k 12 / q25, lexical q50).
- **L-1:** `scripts/measure_lever_overhead.py` re-run on the six new files only (staging folder). R-A1: p95 48.8 to 51.7 ms (before 51.8 to 63.1). R-A2: observed p95 **70.9 ms** (before 28.2), lexical **84.9 ms** (before 35.3); earlier runs the same day gave 68.8 / 69.0 and 83.0 / 85.1 ms. The older figures predate the last change in #26, which put the effective-input cap (`token_counts`, `lower_uncached_input`) inside `apply`. All pass the 100 ms target. The other three baselines' R-A2 files still carry the 2026-11-02 overhead (see the question below).

| Result (`todays_models`, report period) | Cost known / LLM req. before → after | Baseline total before → after | Saving before → after | Share before → after |
|---|---|---|---|---|
| `cache.popular_question.first_turn` | 4,919 → 24,561 / 24,609 | 3.622 → 251.425 | 0.0040 → 0.5432 | 0.11% → **0.22%** |
| `cache.popular_question.all_turns` | 4,919 → 24,561 / 24,609 | 3.622 → 251.425 | 0.0095 → 0.6475 | 0.26% → 0.26% |
| `cache.popular_question.first_turn.ttl24h` | 4,919 → 24,561 / 24,609 | 3.622 → 251.425 | 0.0001 → 0.1181 | 0.003% → **0.047%** |
| `cache.popular_question.all_turns.ttl24h` | 4,919 → 24,561 / 24,609 | 3.622 → 251.425 | 0.0001 → 0.1443 | 0.003% → 0.057% |
| `context.reranker_cut.observed_relevancy` (eligible 16,099) | 1,495 → 16,099 eligible priced | 3.622 → 251.425 | 0.175 → 6.084 | 4.83% → **2.42%** (2.24% to 2.63%) |
| `context.reranker_cut.lexical_overlap` (2,000 sample) | 183 → 2,000 / 2,000 | 0.488 → 28.959 | 0.040 → 0.736 | 8.15% → **2.54%** (2.22% to 2.89%) |

Price-file units, token cost only; R-A1 repriced results have no interval. Shares are now over (nearly) all report LLM requests, so the old R-A2 shares, which were over a non-representative subset, should not be quoted.

- **Text fix (found in Part 1):** `scripts/run_reranker_cut.py` wrote "gemini-2.5-flash is not [priced] … small, unrepresentative subset" into every R-A2 `todays_models` result. The line now names the replay prices; the two R-A2 `todays_models` files were regenerated (figures identical, field by field) and L-1 measured again.
- **Docs:** "today's models" lines in the [R-A1 README](../../../experiments/caching/exp-cache-003-popular-question/README.md) and the [R-A2 README](../../../experiments/context/exp-ctx-003-reranker-cut/README.md) (coverage, table, curve, overhead, assumption).
- **Baseline test state on `main` 37262d4 (Windows):** 6 failed, 3 errors before any change. With `PYTHONUTF8=1`, 2 remain: `tests/unit/settings/test_logged_prices.py::test_the_old_price_file_and_live_catalogue_are_unchanged` hashes two TOML files that a `core.autocrlf=true` checkout writes with CRLF (blobs are LF). The 7 others (#29 Gemini tests) read or write text without `encoding=`. Not Pipeline A's files; for their owners: a `.gitattributes` `eol=lf` rule for `config/**/*.toml`, and `encoding="utf-8"` in the #29 tests.
- **Question:** re-run L-1 over all four baselines of R-A2 so every file of a lever carries the same overhead figure? It would rewrite only the overhead fields of the `as_logged`, `premium_gpt_5_5` and `best_single_cheap` files.
