# ADR-0019: Configuration — TOML files, six layers, `METIS__` overrides, secrets only from the environment

- Status: **decided** (format, layers, precedence, naming). The settings shape is **provisional** (it grows with each stage).
- Date: 2026-10-18
- Resolves: configuration.md §4 open items (file format, loading library, variable naming); contracts.md O-1 (`Settings` and its secret holder); ADR-0003 point 4 (`.env.example`).
- Relates to: configuration.md, ADR-0003, ADR-0015, ADR-0017, ADR-0018, MP§4 (configuration over code), QA-REPL, QA-REPRO
- Detail: [configuration.md](../architecture/configuration.md), [local development guide](../guides/local_development.md)

## Context

Stage 3 fixed the kinds of configuration (defaults, reference data, runtime, experiment, overrides, secrets) and a provisional precedence, and left the file format, the loader, and the naming to Stage 6. Stage 5 left the catalogue, the empty price table, and the fingerprint key in code. Stage 6 also needs real reference data: the Metis test catalogue, endpoints, and prices (ADR-0018).

## Decision

1. **Format: TOML**, read with the standard library's `tomllib`. No new dependency. Prices are **decimal strings** (`"0.055"`), never TOML floats, so amounts stay exact; the reader refuses floats.
2. **Layers, lowest precedence first:**
   1. each policy's typed **code defaults** in `domain` (A-43 placeholders), applied by wiring;
   2. `config/defaults.toml` (versioned application defaults, including strategy selection);
   3. an **experiment** file (`experiments/<area>/<EXP-ID>/config.toml`, or a run profile such as `config/profiles/walking_skeleton.toml`);
   4. a **runtime** file (untracked): `METIS_RUNTIME_CONFIG`, else `config/local.toml` if present;
   5. **environment overrides** `METIS__<SECTION>__<KEY>=value` (the process environment first, then `.env`); values are TOML literals when they parse, else strings;
   6. **explicit overrides** from the caller (`{"budget.run_cap": "0.5"}`, e.g. from a CLI).
3. **Layer rules** enforced by the loader:
   - `budget.lifetime_ceiling` only in `defaults.toml` (ADR-0018);
   - an experiment file may not set `live`, `budget`, `paths`, or `dev`: the runtime decides what this machine allows;
   - no layer may contain a secret-like key (`api_key`, `password`, `secret`, `token`, `fingerprint_key`, or `*_api_key`, `*_password`, `*_secret`);
   - unknown keys are errors (`extra="forbid"`), in settings and, through wiring, in every policy section.
4. **Reference data** lives in `config/reference/*.toml`: catalogue, prices, endpoints, baselines. Each file has its own `version`; a change is a new version (for prices, a new dated file). The loader checks them against each other (every `price_ref` priced, every provider has an endpoint, every baseline names a catalogue model).
5. **Secrets** come only from the environment or the untracked `.env`: `METIS_API_KEY`, `METIS_FINGERPRINT_KEY` (hex, ≥ 32 bytes), `METIS_DB_PASSWORD`. They are held in `Secrets` with pydantic's secret types (hidden in `repr`, `str`, and dumps), never enter `Settings` or the config hash, and leave the holder only in wiring, as arguments to the one component that needs them. An empty value means unset.
6. **`Settings` lives in the `settings` package, not in `contracts`.** It is configuration read by wiring, not data passed between pipeline components, and it holds no content. Like the policy configs, it uses `ContractModel` (frozen, `extra="forbid"`), without per-field privacy classes.
7. **Settings know no policies.** `[pipeline.*]` sections are opaque to `settings`; wiring validates them against each policy's own config type (configuration.md §3 rule 5).
8. **Config hash:** `cfg1:` + 16 hex of SHA-256 over canonical JSON of the settings, **excluding** machine-local sections (`paths`, `logging`) and reference file paths (replaced by the reference **version IDs**). Secrets are not in `Settings` at all. The hash goes into `Versions.config_hash` on every event. Settings hold no content, so a plain hash is enough (ADR-0015 covers content).
9. **Config directory:** `METIS_CONFIG_DIR`, else `<checkout>/config`. Relative paths in settings resolve against the config directory's parent (the checkout, or `/app` in the container).

## Alternatives considered

- **YAML.** Common and readable, but needs a third-party parser (PyYAML) and has surprising implicit typing (`no` → false, `1.10` → 1.1). Rejected.
- **pydantic-settings.** Handles environment variables, `.env`, and nesting. But it adds a dependency, its precedence model would have to be bent to four file layers plus the layer rules, and its `.env` handling would need its own review. The loader here is about 250 lines with tests. Rejected for now; revisit if settings grow much.
- **python-dotenv.** Only the reader would be used; the format needed is small. Rejected; the reader is tested here.
- **JSON config files.** No comments, which this project needs for sources and caveats. Rejected.
- **Environment variables for everything.** Hard to review and to version. Kept only for secrets and overrides.
- **`Settings` in `contracts`.** It would put configuration types next to the data contracts and into the generated contract reference. Rejected (point 6).

## Consequences

- The walking skeleton's synthetic catalogue and empty price table moved from code to `config/reference/*-synthetic-skeleton.toml`, selected by `config/profiles/walking_skeleton.toml` (Q-27, A-42 closed).
- The configuration diagram's arrows are now labelled (contracts.md §7).
- `METIS_FINGERPRINT_KEY` replaces the per-run random key when set (A-44 narrowed).
- The catalogue and price **schema** stay provisional until Stage 7. Rows the current `PriceTable` cannot represent (context-length tiers) are parsed and kept aside, and that model's cost is "not computed" until then.
- Experiment configuration files (Stage 8) are TOML at layer 3 and get the same rules.
