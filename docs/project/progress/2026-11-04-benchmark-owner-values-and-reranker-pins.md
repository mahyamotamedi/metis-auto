## Benchmark owner values, open Metis gate and reranker pins (2026-11-04)

Branch `sprint-final-pipelines`. **No model call, no spend, no weights downloaded, no GPU run, no push.** Decision record: ADR-0062. Traces: FR-EVAL-04, FR-CTX-02, QA-COST, H-2.

- **`config/evaluation/benchmark.toml`:** all owner values set as decided (cap 35 USD, 8192 output tokens, order seed, judges `gpt-4o-mini` + `deepseek-v4-flash` with the self-preference caveat, `acceptable_score` 0.5 fixed before results, cheap arms, four machines, 24 h) and the Metis gate open with the owner's statement as the reference.
- **Tests:** the refusal tests now use a temporary copy of the config with one value removed (parametrized over all ten keys); new tests: committed config passes the all-values check and both quality-check gates; `gpt-4.1-nano`, `mimo-v2.5`, `jev-latest` stay refused; missing ledger summaries are reported by `plan` and `spend_share.py merge`.
- **Ledger summaries:** `reports/spend/ledgers/` does not exist; none was created. `plan` shows `ledger_summaries.missing` = all four.
- **Estimate:** `plan --estimate` (no database on this machine) refuses only with "input sizes need the golden-v2 database". A derived worst case from known counts (1,413,173 input tokens over 300 records, 8192 output tokens on every call, judges at 64 tokens): about 13.1 USD for the main 300 and 0.9 USD for the pilot; both under 35 USD. It is a derivation, not the plan's output.
- **Reranker:** pinned (revision, licence, six files with sha256 and sizes); the three small hashes computed from our own download at the pinned revision. Tests: refusal when weights are missing or differ, the table is fully pinned, `--check` never downloads.
- **Open:** four ledger summaries, the golden-v2 database for the exact estimate, per-run approval, the GPU fetch and run, Q-53/Q-55 wording, the kNN pass, K-1 to K-6.
