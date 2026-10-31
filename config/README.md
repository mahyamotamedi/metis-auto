# config/

Versioned configuration **data**, not code ([ADR-0019](../docs/adr/0019-configuration-format-layers-and-secrets.md), [configuration.md](../docs/architecture/configuration.md)). Format: TOML.

| Path | What | Layer |
|---|---|---|
| `defaults.toml` | Application defaults: paths, logging, live switch (off), budget caps and the 20 USD ceiling, reference-file choice, experiment defaults, embedding and database placeholders, policy selection (`[pipeline.*]`) | 2 (defaults) |
| `reference/catalogue-metis-test.toml` | Five Metis test models plus `gpt-5.4` and the premium baseline `gpt-5.5` (both disabled, never called) | reference data |
| `reference/prices-metis-2026-10-18.toml` | Metis user prices, USD per 1M tokens, with source and check date; context tiers for `gpt-5.4` (Stage 7) | reference data |
| `reference/tokenizers.toml` | How each `tokenizer_ref` is counted: backend, pinned file (URL, sha256), fidelity, evidence, chat template (Stage 7, [token_accounting.md](../docs/architecture/token_accounting.md)) | reference data |
| `reference/endpoints-metis.toml` | Base URL and wire format per model family (Gemini deferred) | reference data |
| `reference/baselines.toml` | Premium and as-logged baseline definitions | reference data |
| `reference/label-mapping-sample-v1.toml` | Logged model labels of the sample → catalogue models (fidelity or unmapped reason), for the as-logged baseline (Stage 8) | reference data |
| `reference/*-synthetic-skeleton.toml` | **Synthetic** catalogue (not real models) and empty price table for the walking skeleton | reference data |
| `profiles/walking_skeleton.toml` | The walking skeleton's run profile | 3 (experiment) |
| `local.example.toml` | Template for your untracked `local.toml` | 4 (runtime) |
| `local.toml` | **Git-ignored.** Machine-specific settings | 4 (runtime) |

Rules:
- **No secrets, ever.** Secrets come from the environment or the untracked `.env` (template: `../.env.example`). A secret-like key in any config file is rejected by the loader.
- Reference files carry a `version`. A change is a new version; a price change is a new dated price file with its source and check date.
- Prices are decimal strings (`"0.055"`), never TOML numbers.
- Experiment configs live with their experiment and only override these defaults; they may not set `live`, `budget`, `paths`, or `dev`.
- Production defaults may name only promoted components.

Rules for the folder: [repository_structure.md §5](../docs/architecture/repository_structure.md#5-configuration-files-config).
