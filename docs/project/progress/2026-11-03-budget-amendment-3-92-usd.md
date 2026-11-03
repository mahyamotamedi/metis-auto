## Budget: ADR-0018 amendment 3, ceiling and lifetime cap 92 USD (2026-11-03)

Branch `sprint-final-i1-n1`. **Awaiting review.** Traceability: ADR-0018 ([amendment 3](../../adr/0018-live-calls-for-development-under-a-lifetime-budget.md)), Q-29, ADR-0030.

- **Owner decision (2026-11-03):** "Remaining credits = 80 USD." New ceiling = cap = 12.03 USD (golden answers, `ga-v2-20261101`) + 80 = 92.03, rounded down to **92 USD**. Spend on machines whose ledger was not visible is not counted, so 92 is an upper bound. This machine's ledger shows 0 USD.
- **Changed:** `config/defaults.toml` (`lifetime_ceiling` and `lifetime_cap` 20 to 92; `run_cap` and `warn_at` unchanged), `docs/adr/0018-...md` (amendment 3, Status), current-status mentions in `docs/architecture/configuration.md`, `config/README.md`, `config/local.example.toml`, `docs/guides/demo_quickstart.md`, `docs/guides/offline_evaluation.md`.
- **Tests that read the real defaults:** `tests/unit/settings/test_settings_loader.py` (cap 92; over-ceiling params now 92.01 and 200), `tests/integration/test_demo_ui_view.py` (cap 92; fixture ledger amount 78.2 to keep the 85 % / 80 % warning check).
- **Not done:** ADR-0053 and `docs/guides/benchmark_pilot.md` are not in this checkout, so their pointer sentences are not added; `scripts/spend_share.py` does not exist either. Historical records (earlier amendments, ADR-0003/0021/0030, the owner's brief, progress entries) are untouched.
- **Reminders:** every machine raises its `config/local.toml` lifetime cap if it has one; the owner checks the Metis dashboard limit is not below 92.
