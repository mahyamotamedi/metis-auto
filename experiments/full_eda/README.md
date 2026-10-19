# experiments/full_eda/ — full-dataset EDA (not started)

Home of the full-dataset EDA ([ADR-0008](../../docs/adr/0008-sample-eda-is-exploratory.md), [ADR-0009](../../docs/adr/0009-repository-structure-and-dependency-rules.md)). It starts when the full dataset arrives, as the first step of the Stage 9 onboarding checklist.

| What | Where |
|---|---|
| notebooks | here |
| tested analysis code | `src/metis_auto/analysis/` (re-implemented; nothing from `sample_eda/eda_helpers.py`) |
| figures and feature-only tables | `reports/full_eda/` |
| write-up | `docs/full_eda/` |

It re-checks every sample signal (context.md `F-n`) and the data-owner questions Q-04, Q-06, and Q-09. Data is read through `metis_auto` data sources, never from hard-coded paths.
