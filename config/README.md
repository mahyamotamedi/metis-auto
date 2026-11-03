# config/

Versioned configuration **data**, not code ([ADR-0019](../docs/adr/0019-configuration-format-layers-and-secrets.md), [configuration.md](../docs/architecture/configuration.md)). Format: TOML.

| Path | What | Layer |
|---|---|---|
| `defaults.toml` | Application defaults: paths, logging, live switch (off), budget caps (default lifetime cap 20 USD) and the 20 USD ceiling, reference-file choice, experiment defaults, embedding and database placeholders, policy selection (`[pipeline.*]`) | 2 (defaults) |
| `reference/catalogue-metis-test.toml` | Five Metis test models plus `gpt-5.4` and the premium baseline `gpt-5.5` (both disabled, never called) | reference data |
| `reference/prices-metis-2026-10-18.toml` | Metis user prices, USD per 1M tokens, with source and check date; context tiers for `gpt-5.4` (Stage 7) | reference data |
| `reference/tokenizers.toml` | How each `tokenizer_ref` is counted: backend, pinned file (URL, sha256), fidelity, evidence, chat template (Stage 7, [token_accounting.md](../docs/architecture/token_accounting.md)) | reference data |
| `reference/prices-metis-router-2026-11-02.toml` | Decision-router backend prices (Jev via Metis: input 0.0462, output 0.0000 USD per 1M), apart from the answering-model table ([ADR-XXXX (system-one-decision-router)](../docs/adr/draft-system-one-decision-router.md)) | reference data |
| `evaluation/router_dev_slice_v1.toml` | The routing dev slice: 150 records, seed, exclusions, caps, soft quotas, review settings; no machine paths ([router_dev_slice_v1.md](../docs/evaluation/router_dev_slice_v1.md)) | evaluation config |
| `reference/routers.toml` | Local decision-router models (THX-01, a multilingual mmBERT model at the repository root; optional Mizan GGUF): repository, the exact files to fetch, required parts, and, once `scripts/fetch_router_assets.py pin` has run on the owner's machine, the commit and every file's sha256 ([ADR-XXXX (system-one-decision-router)](../docs/adr/draft-system-one-decision-router.md) point 7) | reference data |
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
- Experiment configs live with their experiment and only override these defaults; they may not set `live`, `budget`, `paths`, `dev`, `golden_answers` or `data`.
- **Runtime-only keys** (`router.real_data_approved`, `router.allow_unpriced`): per-run approvals, settable only in `local.toml` or an environment override, never in `defaults.toml` or an experiment file ([ADR-XXXX (system-one-decision-router)](../docs/adr/draft-system-one-decision-router.md)).
- **Decision router** (`[router]`, ADR-XXXX (system-one-decision-router)): `mode = "off"` by default. Switch for a run with `config/local.toml` or an environment override, e.g. PowerShell `$env:METIS__ROUTER__MODE = "local"` (any key works the same way: `METIS__<SECTION>__<KEY>`). Guide: [router_quickstart.md](../docs/guides/router_quickstart.md).
- **Machine-specific paths** (the full dataset: `[data] full_data_root`) go only in `local.toml` or `METIS__DATA__FULL_DATA_ROOT`, never in committed configuration; the `data` section is left out of the config hash.
- Production defaults may name only promoted components.

Rules for the folder: [repository_structure.md §5](../docs/architecture/repository_structure.md#5-configuration-files-config).
