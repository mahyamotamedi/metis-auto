# experiments/

Experiment definitions, candidate strategies, and notebooks. This directory is **outside** the `metis_auto` package: experiments import `metis_auto`, never the reverse.

| Area | For |
|---|---|
| `routing/` | routing strategies and router overhead (H-5, H-6) |
| `caching/` | exact and semantic cache key, validity, and threshold experiments (H-3, H-4) |
| `context/` | instruction, history, and RAG reduction ablations (H-1, H-2) |
| `cost/` | tokenizer-specific size estimates and price sensitivity (H-7) |
| `evaluation/` | judge calibration and metric validation (FR-EVAL-05) |
| `full_eda/` | full-dataset EDA notebooks (ADR-0008) |
| `sample_eda/` | **frozen**, preliminary sample EDA; nothing may import it |

- One folder per experiment: `<area>/<EXP-ID>-<slug>/`, holding a `README.md` (hypothesis, plan link), a `config.toml`, and candidate code if any. EXP-IDs are `exp-<area>-<nnn>` (`cache`, `route`, `ctx`, `cost`, `eval`); run with `scripts/run_experiment.py <config>`. Framework: [docs/experiments/framework.md](../docs/experiments/framework.md).
- Experiments so far: [caching/exp-cache-001-exact-baseline](caching/exp-cache-001-exact-baseline/README.md).
- Experiments don't import each other. Shared code is a promotion candidate.
- Run records go to `runs/` (gitignored). Committed, feature-only summaries go to `reports/<area>/<EXP-ID>/`.
- Notebooks are committed with no raw content in their outputs.

Layout, import rules, and the **promotion process** (experiment → `src/metis_auto/`): [repository_structure.md §6](../docs/architecture/repository_structure.md#6-experiments-experiments).
