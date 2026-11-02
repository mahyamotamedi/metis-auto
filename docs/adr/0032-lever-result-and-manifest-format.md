# ADR-0032: Lever results are content-free JSON with a reproducibility manifest; two cost blocks

- Status: **decided** (format, privacy classes, blocks, determinism rule); the number is provisional until merged with `main` (0032 was the second free number on `origin/main` on 2026-11-02). Final plan E-4, for tasks S-1 and E-2.
- Relates to: ADR-0017 (contracts, privacy classes), ADR-0020 (cost accounting), ADR-0022 (own runner, MLflow only as exporter), ADR-0031 (full-data lever replay), QA-REPRO, QA-PRIV, FR-EVAL-07, FR-REQ-01.
- Code: `src/metis_auto/analysis/levers.py`, `src/metis_auto/analysis/lever_result.py`.

## Context

Three people (Pipelines A, B, C) each produce results for the same steps. The comparison command, the savings waterfall and the demo all read them, so the format must be one shape, free of content and identifiers (licence: aggregates only), and reproducible (QA-REPRO). `requests.parquet` holds the recorded total cost and the number of per-call fee items, but not the input, output and cached cost split, which exists only in the raw billing table (checked 2026-11-02).

## Alternatives considered

- **MLflow-only records.** One tool, with a UI. But free-form params and tags do not enforce privacy classes, and a flat metric model loses states such as `correctness_state` (the reason ADR-0022 rejected MLflow as the record). Rejected as the record.
- **Four cost blocks** (fees, input, output, cached) by adding `costBreakdown` sums to `billing.py` and the ingest. Exact, but touches shared files and needs a re-ingest. Deferred, not rejected.
- **Split token cost by token counts.** A heuristic that would look like data. Rejected.
- **`created_at` read from the clock inside the manifest.** Conflicts with byte-identical re-runs. Rejected.

## Decision

1. **`LeverResult` and `Manifest` are frozen `ContractModel`s** (ADR-0017). Every field declares a privacy class (`OPERATIONAL` or `DERIVED`); none is `CONTENT`, `FINGERPRINT` or `REFERENCE`, and field names contain no text, ID or hash of content (tested).
2. **`LeverResult` fields:** `lever_id`, `step` (cache, context, routing), `version`, `n_requests`, `n_eligible`, `baseline`, `baseline_cost`, `saving`, `ci_low`, `ci_high` (None when not computed), `slices`, `evidence_class` (observed, metadata-derived, heuristic, hypothetical reconstruction, simulation), `correctness_state` (`unmeasured`, `sampled:<n>`, `measured`), `assumptions`, `overhead_ms_p50`, `overhead_ms_p95`, `manifest`. Costs are `Decimal`, finite, printed in fixed notation.
3. **`Manifest` fields:** `data_revision` (40-hex, the pinned revision), `code_commit` (7 to 40 hex or `unknown`), `config_hash` (SHA-256 of the canonical `config`, `min_n` and period bounds; key order does not matter), `seed`, `price_version` (the `version` key of the price table), `python_version`, `created_at` (UTC). Patterns reject paths and user names.
4. **Deterministic JSON:** sorted keys, fixed money notation, trailing newline. `created_at`, `code_commit` and `python_version` are **arguments** of `build_manifest`, so `analysis` has no clock or git call and the same inputs give the same bytes. Scripts pass the real UTC time and `wiring.experiments.code_version`; tests fix them.
5. **Slices:** every result has `all` and `llm_only`. `all` counts every row in `n_requests`; cost, savings and hits are summed over LLM rows with a known cost, so workflow rows (empty billing) add nothing and unknown is never zero.
6. **Two cost blocks:** `fees` = 0.002 x per-call items (a proxy) and `token_cost` = recorded total minus fees. Checked 2026-11-02 against the billing table: the proxy is 35.8% of cost against 37.6% (908 messages differ), so fees are understated by about 5%. Fee savings from it are labelled "proxy".
7. **Combine order:** cache, then context, then routing. Cache hits skip context and routing (no double counting).
8. **MLflow (plan T-2):** this does not contradict ADR-0022. That ADR chose its own runner and allowed an MLflow *exporter* as a read-only view, never the record, with its own decision record. T-2 logs the `LeverResult` JSON files to MLflow after they are written; the JSON stays the record. The `services` extra and the exporter need their own ADR (plan T-0). The exporter must keep `correctness_state` and the slices (for example as tags and artifacts), not drop them by flattening.

## Consequences

- Results are simulations; hits are candidate hits; recorded and repriced cost are never mixed (ADR-0031).
- Exact fees and the input, output and cached split need the upstream change to `billing.py` and the ingest. `a_bill_inputTokens` excludes cached tokens for five models, so routing repricing (task R-A3) must add them back, with a test.
- Changing a field after the 14:00 freeze needs everyone's agreement; the comparison, dashboard and exporter all read this shape.
- Guarding tests: `tests/unit/analysis/test_lever_manifest.py` (`test_result_records_revision_commit_config_hash_seed_price_and_python_version`, `test_same_inputs_same_seed_give_identical_json`, `test_changing_a_threshold_changes_the_config_hash`, `test_manifest_has_no_path_or_user_name`) and `tests/unit/analysis/test_levers.py` (`test_lever_result_has_no_text_or_id_field`, `test_every_result_has_all_and_llm_only_slices`, `test_with_blocks_derives_fee_and_residual_and_keeps_unknown`).
