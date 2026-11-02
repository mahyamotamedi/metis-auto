## Stage 6 — Configuration, environment, containers (2026-10-18)

### Owner brief brought into the project first
- [live_testing_and_demo_brief.md](../live_testing_and_demo_brief.md): byte-identical copy of the owner's brief (sha256 `8e7293a4…7c`), linked from the docs index.
- [metis_pricing_2026-10-18.csv](../../references/metis_pricing_2026-10-18.csv): byte-identical copy of the price extract (sha256 `15197ad9…4178`). **Defect found:** its structured columns are wrong for context-tiered models (`gpt-5.4`); the `raw` column is right, and the price file uses it (A-47).
- [metis_wrapper_api.md](../../references/metis_wrapper_api.md): endpoints and notes from the saved OpenAI, DeepSeek, Gemini, and overview (Grok) pages, with the save date and canonical URLs. The API-keys page was not opened.
- Decisions recorded: **Q-08 answered** and **Q-12 answered** ([ADR-0018](../../adr/0018-live-calls-for-development-under-a-lifetime-budget.md), amending ADR-0003); **Q-05 partly answered** (`gpt-5.4`, never called, for development and the demo); A-13 decided; Stage 7.5 and the Demo milestone added above.

### Outputs
- **Settings** (`src/metis_auto/settings/`, [ADR-0019](../../adr/0019-configuration-format-layers-and-secrets.md); closes contracts.md O-1):
  - `model.py`: `Settings` (frozen; `paths`, `logging`, `live`, `budget`, `reference`, `experiment`, `embedding`, `database`, `dev`, opaque `pipeline`), `Secrets` (pydantic secret types), endpoint and baseline tables, `PendingPriceRow`, `ReferenceData`, `LoadedSettings`;
  - `loader.py`: six layers by precedence; layer rules (ceiling only in defaults; no `live`/`budget`/`paths`/`dev` in experiment files; no secret-like keys anywhere; unknown keys rejected); `.env` reader; `METIS__<SECTION>__<KEY>` overrides; secrets; config hash `cfg1:…`;
  - `reference.py`: TOML reference files → `ModelCatalogue`, `PriceTable`, endpoints, baselines; cross-file checks; tiered price rows kept aside.
- **Config files** (`config/`): `defaults.toml`; `reference/catalogue-metis-test.toml` (5 test models + `gpt-5.4` disabled; placeholder tiers and groups, A-48; limits unknown, A-51); `reference/prices-metis-2026-10-18.toml` (with source and check date); `reference/endpoints-metis.toml` (OpenAI, DeepSeek, Grok enabled; Gemini deferred); `reference/baselines.toml`; the synthetic skeleton catalogue and empty prices moved from code (Q-27, A-42 closed); `profiles/walking_skeleton.toml`; `local.example.toml`; README.
- **Spend ledger** (`adapters/system/ledger.py`): `FileSpendLedger`, persistent and cumulative (append-only JSON Lines under `data/spend/`, file lock); `remaining()` = the tighter of lifetime cap (all runs) and per-run cap (this run); warnings at 50 % and 80 %; fails closed on a damaged file. Defaults: lifetime **20 USD** (= the ceiling), per run **1 USD** (A-49).
- **Wiring** (`wiring/from_settings.py`): `pipeline_config` (policy types validate `[pipeline.*]`), `fingerprint_key` (`METIS_FINGERPRINT_KEY` or a random per-process key, A-44), `spend_ledger`, `live_permission` (experiment asks for `live` + `live.enabled` + both caps + `METIS_API_KEY`), `build_pipeline_from_settings`. `build_pipeline` now records the config hash in `Versions` (the Stage 5 TODO). The walking skeleton loads its profile from `config/`.
- **Scripts:** `run_walking_skeleton.py` uses settings (prints the config hash and layers); new `show_budget.py` (spend vs caps and why live calls are blocked; no calls).
- **Environment:** `.env` created with only `METIS_API_KEY=` (empty) and a comment; the owner pastes the key. `.env.example` lists every variable (secrets, locations, live and budget, reference data, pipeline/cache, embeddings, database, experiment, logging, dev flags) with comments and placeholders only. `.gitignore`: `.env.*` (except `.env.example`), `config/local.toml`, `data/spend/`.
- **Docker:** `Dockerfile` (targets `runtime`: `requirements.lock` + package, runs the walking skeleton; `dev`: `requirements-dev.lock` + repo, runs pytest), `.dockerignore` (no `.env`, no gitignored data), `compose.yaml` (service `app`, `.env` optional at run time, `runs/` and `data/spend/` bind-mounted so the ledger is shared; optional `postgres` behind the `db` profile).
- **Docs:** [configuration.md](../../architecture/configuration.md) (mechanism, diagram labelled), [local development guide](../../guides/local_development.md), ADR-0018, ADR-0019, ADR-0003 amended, contracts.md (O-1, §7), overview (CMP-19/20/26), module_reference (settings section, ledger and wiring rows), repository_structure (§1, §5, §8, §9), deployment_and_data, architecture README, docs index, README, GLOSSARY (5 terms), `CLAUDE.md` (two durable rules: never touch `.env`; live-call budget), register.
- **Tests (new, 60):** `tests/unit/settings/` (loader: precedence, layer rules, ceiling, secrets hidden and unhashed, config hash, `.env` reader, `.env.example` has placeholders only; reference: catalogue, endpoints, baselines, **every price checked against the CSV's `raw` text**, cross-file errors), `tests/unit/adapters/test_adapters_file_ledger.py`, `tests/integration/test_settings_wiring.py` (real config builds a valid `PipelineConfig`, the walking skeleton from config with the config hash on every event, live refusal with reasons, no secrets in events). `tests/architecture/test_module_reference.py`: `settings` counted as a whole package (it has no sub-packages).

### Validation
- **Full suite: 392/392 pass** in the venv, offline, warnings as errors (332 before + 60 new). No API key, no network.
- ruff check and format clean on the whole repository. Formatting touched only new Stage 6 files.
- Import rules pass unchanged (`settings` imports only `contracts`); the module reference matches the code.
- All 12 Mermaid blocks in `docs/architecture/` parse with Mermaid 11.4.1 (Node, jsdom, scratch directory outside the repo); a broken block is rejected.
- **Fresh-clone check:** a clean copy (tracked and new files only; no `.env`, no venv) installed from the locks into a new venv and passed 392/392; the scripts ran. This found the lock defect below.
- `scripts/run_walking_skeleton.py` and `scripts/show_budget.py` run natively. `show_budget.py` reports live calls blocked (source not `live`, `live.enabled` false, no key).
- No contract changed: `contracts_reference.md` is not stale (its test passes).
- Raw sample data unchanged (sha256 checked).
- **Container: not run.** Docker is not installed on this machine, so the images were written but never built (TODO-11). The base image is pinned by tag, not digest.

### Decisions and drift
- Decisions: ADR-0018 (live calls, budget, Metis wrapper), ADR-0019 (configuration). Defaults chosen and stated: TOML; `METIS__` override naming; ledger at `data/spend/` rather than `runs/` (clearing run records must not reset the budget); `Settings` in `settings`, not `contracts`; tiered prices kept aside so `gpt-5.4` costs are "not computed" until Stage 7.
- **Defect fixed (from Stage 5):** the documented install failed on a fresh venv, because `requirements-dev.lock` did not pin `setuptools` (needed by pip-tools) and `--require-hashes` refused it. The dev lock was recompiled with `--allow-unsafe`, keeping every pin; the only change is hashed pins for `pip` and `setuptools` ([ADR-0001 update](../../adr/0001-python-tooling.md)).
- Drift fixed: deployment_and_data.md said Compose would gain PostgreSQL only in Stage 9; the master prompt asks for an optional service now. It exists behind a profile and starts only on request.

**Assumptions added:** A-46…A-52. A-13 decided, A-42 closed, A-44 narrowed.
**Open questions raised:** Q-29 (Metis dashboard spending limit: owner action), Q-30 (confirm placeholder tiers and groups, and the 1 USD per-run cap). **TODOs:** TODO-10 (context windows before any live call), TODO-11 (build the images); TODO-02 partly resolved; TODO-09 re-checked.

**Carried into later stages:**
- **Stage 7:** price schema (context tiers, cache writes, effective dates) so `gpt-5.4`'s pending rows become usable; tokenizers for the six models; label mapping; premium-baseline estimate; overhead script.
- **Stage 7.5:** TODO-10; the live adapter built through `build_pipeline_from_settings`; the spend-guard TODO (uncomputable actual cost stops the run); verify A-33 (SDK retries off) and A-46.
- **Stage 8:** experiment configs as TOML at layer 3; candidate loading.

**Exit criteria:** "A fresh clone can follow the guide to run the smoke test both natively and in a container, with no secrets." **Natively: met.** The guide was followed in a clean copy of the tracked and new files (no `.env`, no `.venv`): fresh venv from Homebrew Python 3.13, hash-locked install, smoke test 16/16, full suite 392/392, both scripts run; the config hash matched the original checkout's. **In a container: written but not verified** (TODO-11).

### Stage 6 follow-up — answers to Q-29, Q-30; TODO-11 deferred (2026-10-18)

| Item | Status | Answer |
|---|---|---|
| Q-29 | open (owner action) | The owner will check the Metis dashboard for a spending limit and set it at or below 20 USD if available. Stays open until the owner confirms. |
| Q-30 | answered | Confirmed: price-based placeholder tiers and equivalence groups for development and the demo, to be replaced by Stage 8 evidence (A-48 decided for that scope); per-run cap 1 USD (A-49 decided). |
| TODO-11 | deferred | Docker Desktop isn't installed and the demo runs natively. Building and running the images stays on the Stage 10 roadmap. The container half of the Stage 6 exit criterion therefore stays unverified. |

**Changes:** register (Q-29 note, Q-30 answered, A-48 and A-49 status, TODO-11 deferred) and this file (status table, roadmap line, this section). No code or configuration changed: the confirmed values were already the configured defaults.

### Stage 6 follow-up — containers built and verified; TODO-11 resolved (2026-10-18)

The deferral above was withdrawn the same day: Docker Desktop was installed (CLI in `~/.docker/bin`, which was not on the agent shell's `PATH`). Environment: Docker 29.8.2, Compose v5.5.1, Apple Silicon, images linux/arm64.

| Check (guide §6) | Result |
|---|---|
| Base image pinned by digest | `python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f`: a multi-arch OCI index (linux/amd64, linux/arm64), Python 3.13.16, Debian trixie, pulled 2026-10-18. The `Dockerfile` TODO is replaced by update instructions. |
| `docker compose build` (`dev` target) | built; the hash-locked install of `requirements-dev.lock` succeeded |
| `docker compose run --rm app python -m pytest tests/integration -q` | **16/16 pass** |
| `docker compose run --rm app` (full suite) | **392/392 pass** |
| `docker compose run --rm app python scripts/run_walking_skeleton.py` | runs; 3 requests ok (miss, exact hit, follow-up) |
| `docker build --target runtime` + `docker run` | built from `requirements.lock`; the walking skeleton runs; config hash `cfg1:7fa58b3e7d2b5af5`, **identical to native** (machine-local paths are excluded from the hash, as designed); pytest not installed in the runtime image |
| `.env` kept out of images | `.dockerignore` lists `.env`, `.env.*` (with `!.env.example`), `config/local.toml`, `data/spend/`. A filesystem search of both built images found no `.env`, `.env.*`, `local.toml`, or `ledger.jsonl`, except `/app/.env.example` in `dev` (placeholders only, intended). Neither image's environment holds a secret variable (only `PATH`, Python's own variables, `PIP_*`, `PYTHON*`, `METIS_CONFIG_DIR`). `.env` itself was not read; at run time Compose passes it as environment variables, never as a file in the image. |

**Exit criterion:** "A fresh clone can follow the guide to run the smoke test both natively and in a container, with no secrets." **Met** (native: the clean-copy check earlier; container: this table).

**Changes:** `Dockerfile` (base image pinned by digest; update instructions), [the guide](../../guides/local_development.md) §6 (PATH tip, digest note, verified result), the register (TODO-11 resolved), deployment_and_data.md (status), and this file (status table, roadmap line, this section). The bind mounts created empty, git-ignored `runs/` and `data/spend/` on the host. No code changed.
