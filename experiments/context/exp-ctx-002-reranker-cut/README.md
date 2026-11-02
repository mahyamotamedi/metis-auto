# EXP-CTX-002: reranker cut (keep only the best chunks of a RAG request)

- **Hypothesis:** H-2 (sending fewer tokens cuts input cost), applied to retrieved context: X5 (top-*k* or score trimming of retrieved items, [context_plan.md](../../../docs/experiments/context_plan.md) §3). Final plan task R-A2.
- **What it measures:** **input tokens removed, not answer quality.** It is a token-sizing curve. Removing a chunk can remove the one the answer needed, and nothing here checks that (FR-CTX-03; decision rules: context results are "tokens only, quality not measured"). The real `bge-reranker-v2-m3` run on a local GPU (cut-first item a) **was not done**.
- **Assumes S-6 runs first.** Pipeline C's within-message dedup (S-6, `experiments/context/exp-ctx-001-within-message-dedup`, on `origin/context-within-message-dedup`, not merged when this was written) collapses exact copies before this version ranks anything. The tokens dedup removes are S-6's and are reported apart, never in this saving.
- **Traceability:** H-2, X5, FR-CTX-02, FR-CTX-03, QA-PERF (100 ms p95, Q-14), ADR-0031 (full-data replay path), ADR-0032 (result format), Review Focus 3 (cached-token convention).
- **Evidence class:** `observed_relevancy` result: *hypothetical reconstruction* (an observed platform score, tokens from the EDA slope). `lexical_overlap` result: *heuristic*. `correctness_state` is `unmeasured` for both.
- **Code:** [`version.py`](version.py), class `RerankerCut(scorer, floor, threshold, top_k, *, chunks, tokens_per_char, queries=None, cached_separately=frozenset())`, a `levers.StepVersion` of step `context`, and `lexical_overlap(question, chunk_texts)`. Loaded only through `wiring.experiments.load_candidate`; `metis_auto` never imports it. Settings: [`config.toml`](config.toml) (read by the scripts below, not by `run_experiment.py`). Tests: `tests/unit/experiments/test_reranker_cut.py` and `test_run_reranker_cut.py` (all frames [SYNTHETIC], scorer injected, no model).
- **Run:** `.venv\Scripts\python.exe scripts/run_reranker_cut.py` (about 4 min for the observed scorer, 1 min for the lexical sample), then `scripts/measure_lever_overhead.py context.reranker_cut.observed_relevancy context.reranker_cut.lexical_overlap`.
- **Status (2026-11-02):** done as a sizing curve on the full data; results below and in `reports/levers/`.

## Design

| Element | Rule | State |
|---|---|---|
| Eligible | LLM request, not served from cache, `a_rag_state == "ok"`, chunk rows present. Workflow rows and cache hits are never given to the version (`combine`), and the version checks again. | decided |
| Dedup first (S-6) | Inside one request: a row is a copy when an earlier row has the same `h_exact`; the first copy is kept; `chunk_id` is ignored (same ID with a changed text is **not** a copy); a row without `h_exact` is never a copy. Matches S-6's `within_message_duplicates` exactly (read 2026-11-02). | decided (S-6's rule) |
| Unique chunk score | The maximum of its copies' scores; missing only if every copy is missing. | decided |
| Cut | On unique chunks, ranked by score (ties by first position): keep the best `top_k`, drop those under `threshold`, keep at least `floor` (3) in all. A chunk without a score is **always kept and counted** (`rc_n_unscored`), never treated as 0. | decided |
| Scorers | `scorer=None`: the platform's own `relevancy` (*observed platform score*; higher is more relevant; chunks are sent best-first per RAG query, checked 2026-11-02; most eligible bots use the platform reranker `typesafe`/`jev-reranker-latest`, `top_k` 6 per query). `lexical_overlap`: share of the user message's distinct words found in the chunk, both after `normalize_safe`, `\w+` tokens, no stopword list (*heuristic*). A text scorer is called once per request with its unique chunk texts; a request without user text is unscored. | decided |
| Tokens | Characters × 0.3384 tokens per character (EDA `recon.t0rag.coef_rag`, *hypothetical reconstruction*; in `config.toml` and the config hash), taken from **uncached** input only, as S-6 does: the cut's saving = (dedup + cut, capped at input − cached) − (dedup alone, capped). Effective input adds cached tokens back for the five models that report them separately. | decided |
| Cost | Repriced at the logged model's price (`todays_models`, price-file units), tier chosen again by the new input. The recorded cost blocks are **never changed**, so recorded and repriced cost are not mixed. The repricing repeats S-6's `baselines_full.repriced_row_costs` for one baseline (that function exists only on S-6's branch); switch to it after the merge. | provisional |
| Thresholds | Quantiles 10/25/50% of the unique-chunk scores of eligible **tune** requests (March to July 2026), per scorer. | decided |
| Headline rule | Written before results: on the tune period, the point that removes the most input tokens while keeping ≥ 90% of the score mass (sum of unique-chunk scores); ties to the larger `top_k`, then the lower threshold; if none qualifies, the gentlest point. Reported on August to October 2026. | provisional |
| Output | `apply` adds only `rc_*` columns: counts, characters, tokens, summed scores and repriced cost per request. No ID, hash or text leaves memory. | decided |

**Cached tokens (the levers.py warning).** The saving is computed from characters, not from `a_bill_inputTokens`, so the raw-input convention does not change the tokens removed. It does matter for the baseline and for the cap: both use effective input (cached tokens added back for the five models), and removed tokens are priced as uncached input on the assumption that chunks sit after the cached prefix.

## Results on the full data (2026-11-02)

Report period August to October 2026. Tokens cover every eligible request. **Cost coverage is the main caveat:** `todays_models` can price only models in the sprint catalogue (`catalogue-metis-test.toml`), and `gemini-2.5-flash`, which carries 90% of eligible RAG requests and about 95% of their recorded cost, is not in it. So the observed cost share is over 4,919 of 24,609 report LLM requests (1,495 of 16,099 eligible), mostly `grok-4-1-fast` and `gpt-4o-mini`: **not representative**. Intervals are session-clustered 95% bootstrap.

**Three numbers per request group** (headline points, report period):

| Scorer | Requests | Raw chunk tokens | Removed by dedup (S-6, pipeline C, not counted in R-A2) | Removed by R-A2 on top of dedup | Unique chunk share removed | Score mass kept | Repriced cost share saved (95% CI) |
|---|---|---|---|---|---|---|---|
| `observed_relevancy` (top_k 12, threshold q25 = 0.231, floor 3) | 16,099 eligible | 140.3 M | 59.4 M | **18.6 M** | 23.1% | 91.3% | 4.83% (3.11% to 6.69%) of priced LLM cost |
| `lexical_overlap` (no top_k, threshold q50 = 0.20, floor 3) | 2,000 sampled eligible | 17.6 M | 7.5 M | **2.3 M** | 22.8% | 94.1% | 8.15% (4.84% to 13.08%) of priced RAG cost (183 priced requests) |

The two cost shares have different denominators (all priced LLM requests vs. the priced requests of a RAG-only sample) and are not comparable. On the tune period the observed headline saved 2.2% (1.5% to 3.0%).

**Curve, report period, observed scorer** (unique chunk share removed / repriced cost share saved; full table with both periods and scorers in `reports/levers/context.reranker_cut.curve.csv`):

| top_k \ threshold | none | q10 (0.111) | q25 (0.231) | q50 (0.509) |
|---|---|---|---|---|
| 3 | 68.3% / 14.8% | 68.3% / 14.8% | 68.3% / 14.8% | 68.3% / 14.8% |
| 5 | 48.1% / 10.8% | 49.1% / 11.0% | 51.8% / 11.5% | 59.6% / 12.3% |
| 8 | 21.2% / 5.3% | 24.6% / 6.2% | 33.0% / 7.5% | 52.4% / 9.2% |
| 10 | 9.6% / 2.8% | 14.5% / 4.1% | 26.2% / 5.7% | 50.6% / 8.1% |
| 12 | 3.4% / 1.2% | 9.4% / 2.9% | **23.1% / 4.8%** | 49.9% / 7.6% |
| none | 0 / 0 | 6.8% / 1.9% | 21.6% / 4.1% | 49.6% / 7.1% |

At `top_k` 3 the floor (3) equals `top_k`, so thresholds change nothing. For the lexical scorer the 10% and 25% tune quantiles are both 0.0 (at least a quarter of unique chunks share no word with the question), so those rows drop nothing beyond `top_k`.

**Overhead** (`scripts/measure_lever_overhead.py`, offline per-request estimate on one machine; not a load test, Q-14): `apply` on 1,000 seeded report-period LLM rows as one-row frames, chunks loaded before timing. Observed p50 70.3 ms, p95 86.4 ms; lexical p50 80.4 ms, p95 96.5 ms (AMD Ryzen 7 5800H, CPython 3.13.9). Both pass the 100 ms p95 target, but narrowly: most of the time is fixed pandas cost per call (three repricings and a frame copy), not the ranking.

## Assumptions

- *Current:* tokens only; answer quality is not measured, and a cut can remove the chunk the answer needed.
- *Current:* the 0.3384 tokens-per-character slope is a turn-0 regression (*hypothetical reconstruction*), applied to every request and model.
- *Current:* repeated chunks inside a request are billed (the slope counts every row); S-6 owns that saving.
- *Current:* the platform's relevancy scores are comparable across the queries of one request (one reranker); unverified.
- *Current:* the repriced cost covers only catalogue models (see Results).
- *Future:* a real reranker (`bge-reranker-v2-m3`, cut-first a) and a quality ablation would replace the score-mass rule.
- *Speculative:* the score-mass rule (≥ 90%) is a reasonable proxy for "nothing important removed".
