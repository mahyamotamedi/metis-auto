# ADR-0029: Lever results are content-free JSON with a reproducibility manifest; two cost blocks

- Status: **decided** (format, blocks, determinism rule); the number is provisional until merged with `main` (final plan E-4: next free number)
- Date: 2026-11-02
- Relates to: ADR-0017, ADR-0009, ADR-0022, QA-REPRO, QA-PRIV, FR-EVAL-07, H-3, X1, X5
- Code: `analysis/levers.py`, `analysis/lever_result.py`; tests `tests/unit/analysis/test_levers.py`, `test_lever_manifest.py`

## Context

Three pipelines compete per step (cache, context, routing) on the full dataset. Their results must be comparable, free of content and IDs, and reproducible. `requests.parquet` has a recorded total cost and the count of per-call fee items, but not the input, output or cached cost split (that is in the raw billing table).

## Alternatives considered

- **Four blocks** (fees, input, output, cached) by adding `costBreakdown` sums upstream: exact, but changes `billing.py`, the ingest and needs a re-ingest. Deferred.
- **Split token cost by token counts:** a heuristic that would look like data. Rejected.
- **Timestamp taken inside the manifest:** conflicts with byte-identical re-runs. Rejected.

## Decision

1. `LeverResult` and `Manifest` are frozen `ContractModel`s; every field has a privacy class and none can hold content, IDs or hashes of content (tested). Written as sorted-key JSON with fixed-notation money, by callers, to `reports/levers/<lever_id>.json`.
2. Two cost blocks: `fees` = 0.002 x per-call items (a proxy) and `token_cost` = recorded total minus fees. Measured 2026-11-02: the proxy is 35.8% of cost against 37.6% in the billing table (908 messages differ), so it understates fees by about 5%. Unknown cost stays unknown.
3. `combine` applies cache, then context, then routing; hit rows skip later steps; workflow rows are never given to a version.
4. `created_at`, `code_commit` and `python_version` are arguments of `build_manifest`, so analysis has no clock or git call and identical inputs give identical bytes.
5. Every result has `all` and `llm_only` slices. `all` counts every row in `n_requests`; cost and hits are summed over LLM rows with a known cost.

## Consequences

- Results are simulations; hits are candidate hits; recorded and repriced cost are never mixed.
- Fee savings stated from the proxy must say "proxy". Exact fee and the input/output/cached split need the upstream change.
- `a_bill_inputTokens` excludes cached tokens for five models; routing repricing (R-A3) must add them back, with a test.
