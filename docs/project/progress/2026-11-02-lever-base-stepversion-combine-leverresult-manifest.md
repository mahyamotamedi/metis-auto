## Lever base: StepVersion, combine, LeverResult, Manifest (2026-11-02)

Final-plan tasks S-1 and E-2 (Pipeline A), branch `sprint-saba`. Status: **awaiting review**; nothing committed. Code: `analysis/levers.py`, `analysis/lever_result.py`; tests `tests/unit/analysis/test_levers.py`, `test_lever_manifest.py`; two rows in `module_reference.md`. No model calls, no data rows read.

- **Decided (owner, 2026-11-02):** cost blocks are `fees` (0.002 x per-call items, a proxy) and `token_cost` (recorded total minus fees); input, output and cached costs are not in `requests.parquet`. `created_at` is passed to `build_manifest`. The `all` slice counts every row in `n_requests` but sums cost and hits over LLM rows with known cost. Decision record: [ADR-0032](../../adr/0032-lever-result-and-manifest-format.md) and [ADR-0031](../../adr/0031-full-data-lever-replay.md) (numbers provisional; 0029 and 0030 are taken on `origin/main`).
- **Checked on real data (aggregates only):** blocks sum to `a_bill_totalCost` exactly; 104,084 unknown-cost rows stay NaN; the fee proxy is 35.8% of cost against 37.6% in the billing table (908 messages differ), so it understates fees by about 5%.
- **Open:** exact fees and the input/output/cached split need an upstream change to `billing.py` and the ingest.
