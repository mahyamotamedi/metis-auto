# Local development guide

> Just want to run the demo? The [demo quickstart](demo_quickstart.md) is the shorter, step-by-step version for teammates.

How to set up Metis-Auto from a fresh clone and run the smoke test, natively and in a container, **with no secrets**. Last updated 2026-10-18 (Stage 7: tokenizer files).

Background: [configuration.md](../architecture/configuration.md) (layers and rules), [ADR-0019](../adr/0019-configuration-format-layers-and-secrets.md) (format), [ADR-0018](../adr/0018-live-calls-for-development-under-a-lifetime-budget.md) (live calls and the budget), [ADR-0001](../adr/0001-python-tooling.md) (tooling).

## 1. Native setup (Python 3.13 venv)

You need a real Python 3.13 interpreter, **not** conda's (ADR-0001). On macOS with Homebrew: `brew install python@3.13`.

```sh
git clone <repo-url> metis-auto && cd metis-auto
/opt/homebrew/bin/python3.13 -m venv .venv        # or any non-conda python3.13
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install -e . --no-deps
.venv/bin/python scripts/fetch_tokenizer_assets.py   # once: tokenizer files (network)
```

The last step downloads two public tokenizer files (OpenAI's `o200k_base`, about 3.6 MB; DeepSeek-V4-Flash's `tokenizer.json`, about 6.4 MB) into `data/tokenizers/` (git-ignored), and checks them against the sha256 pinned in `config/reference/tokenizers.toml`. It needs no key and costs nothing. `--check` verifies without downloading. Without the files, counts fall back to the labelled chars/4 approximation and the exact-tokenizer tests skip, saying why ([token_accounting.md §2](../architecture/token_accounting.md#2-tokenizers-supported-models-methods-fidelity)). The libraries come from the `tokenizers` extra, which the dev lock includes.

## 2. Run the smoke test (no secrets needed)

```sh
.venv/bin/python -m pytest tests/integration -q    # walking skeleton + settings wiring
.venv/bin/python -m pytest -q                      # the whole suite (offline)
.venv/bin/python scripts/run_walking_skeleton.py   # prints content-free metadata
```

Everything runs offline with fakes. No `.env` is needed: without `METIS_FINGERPRINT_KEY`, a random key is used per process (fingerprints then don't compare across runs, A-44). Network tests are skipped unless you pass `--run-network` (none exist yet). Nothing in the suite downloads anything.

Lint and format: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`

## 3. Configuration in practice

| I want to… | Do this |
|---|---|
| see the defaults | read `config/defaults.toml` |
| change something on my machine only | `cp config/local.example.toml config/local.toml` (git-ignored) and edit |
| override one value for one command | `METIS__LOGGING__LEVEL=DEBUG .venv/bin/python scripts/run_walking_skeleton.py` |
| keep comparable fingerprints across runs | set `METIS_FINGERPRINT_KEY` in `.env` (generate: `python -c "import secrets; print(secrets.token_hex(32))"`) |
| change a model, endpoint, price, or tokenizer | edit or add a file in `config/reference/` with a **new version**; prices and tokenizers need a source and check date ([token_accounting.md §4](../architecture/token_accounting.md#4-price-schema)) |
| see every variable | read `.env.example` |
| measure the pipeline's overhead | `.venv/bin/python scripts/measure_overhead.py --requests 2000 --tokenizer openai-o200k-base` |

Precedence, lowest first: policy code defaults < `config/defaults.toml` < experiment file < `config/local.toml` < `METIS__*` environment (process, then `.env`) < caller overrides. Each run prints its `config_hash` and the layers it used.

## 4. Secrets and the Metis API key

- `.env` is git-ignored. It holds `METIS_API_KEY=` (empty). **Paste the key there yourself**; no tool or agent should read, print, or commit it. `.env.example` (committed) lists every variable with placeholders.
- Secrets are never logged, never written to events or run records, and never part of the config hash. A config file containing a secret-like key is rejected.
- **Having the key does not enable live calls.** All of these are needed (ADR-0018): an experiment asking for `counterfactual_source = "live"`, `live.enabled = true` in your runtime config (or `METIS__LIVE__ENABLED=true`), both budget caps set, and the key. The live client arrives with Stage 7.5 (§5.1); it needs the `live` extra (`openai`), which the dev lock includes.
- The **Metis dashboard** spending limit for the project's API key is **10 USD** (set by the owner; Q-29, 2026-10-18). It is the second safety net, and `budget.lifetime_cap` matches it.

## 5. The live budget and the spend ledger

- Lifetime cap **10 USD** (`budget.lifetime_cap` in `config/defaults.toml`), matching the Metis dashboard limit for the key (Q-29, [ADR-0018 amendment 1](../adr/0018-live-calls-for-development-under-a-lifetime-budget.md#amendment-1-2026-10-18-lifetime-cap-10-usd-q-29)). The **20 USD ceiling** stays the project maximum: only `config/defaults.toml` can set it, and no layer can raise a cap above it. Per-run cap **1 USD** by default. Warnings at 50 % and 80 % of the lifetime cap.
- The ledger is `data/spend/ledger.jsonl` (git-ignored), one line per live charge: amount, currency, time, run ID. **Never delete or edit it**: that resets or corrupts the lifetime total, and a malformed ledger blocks all live calls.
- Check the budget at any time (no calls are made): `.venv/bin/python scripts/show_budget.py`.

### 5.1 Live calls (Stage 7.5, [ADR-0021](../adr/0021-live-openai-compatible-adapter.md))

Only with your own or synthetic messages (ADR-0018). Every live call goes through the spend guard, the ledger, and the recording decorator (`data/recorded/live-<run>.jsonl`, git-ignored: it holds the messages and answers).

1. Put the key in `.env` (`METIS_API_KEY=...`); never commit or print it.
2. Enable live calls on this machine: create `config/local.toml` (git-ignored; copy `config/local.example.toml`) with

   ```toml
   [live]
   enabled = true

   [budget]
   run_cap = "0.10"   # optional: lower per-run cap for this machine
   ```

   The scripts below supply the other key (`counterfactual_source = "live"`) themselves. Remove the `[live]` lines, or set `enabled = false`, to switch live calls off again.
3. Check: `.venv/bin/python scripts/show_budget.py` should list nothing under `live_blocked_by` except `experiment.counterfactual_source is not 'live'`. The scripts set that key themselves.

Scripts:
- `scripts/live_wrapper_check.py`: without arguments it prints the pre-call estimate for one tiny synthetic message per test model and makes no call; `--run` asks before calling; results go to `docs/references/metis_wrapper_live_check_<date>.json`.
- `scripts/live_probe.py`: the follow-up probe (provider cache, mimo-v2.5, DeepSeek with thinking off); same pattern: plan by default, `--run` asks.
- Provider options per model (default: none): `[model_options."deepseek-v4-flash"] thinking = "disabled"` in `config/local.toml` or an experiment file (allowed for DeepSeek and MiMo only).
- `scripts/chat.py`: a command-line chat over the real pipeline, with history and a fixed model (`--model`, `/model <id>`, `/models`, `/reset`, `/budget`). After each answer it prints served by, the model and the provider-reported model, tokens, cost, the premium estimate, the savings decomposition, overhead, and the budget. `--fake` runs offline with no key. `grok-4-1-fast` is disabled (Q-32); `--allow-unknown-window` is only for diagnostics on models with unknown limits.
- If a live call's cost can't be computed (for example an error with no reported usage), the guard charges its pre-call estimate and stops live calls for that run; restart the chat to continue.

## 6. Container (Docker)

Needs Docker with Compose v2.24 or later. Docker Desktop on macOS puts the CLI in `~/.docker/bin`; if `docker` is not found, add it to `PATH` (`export PATH="$HOME/.docker/bin:$PATH"`). The `dev` image installs `requirements-dev.lock` and the repository; the `runtime` image installs only `requirements.lock` and runs the walking skeleton.

```sh
docker compose build
docker compose run --rm app python -m pytest tests/integration -q   # smoke test
docker compose run --rm app                                         # whole suite
docker compose run --rm app python scripts/run_walking_skeleton.py
docker build --target runtime -t metis-auto:runtime . && docker run --rm metis-auto:runtime
```

- `.env` is **not** copied into images (`.dockerignore`); Compose passes it at run time if it exists, and works without it.
- `runs/` and `data/spend/` are bind-mounted, so the container and native runs share **one** spend ledger.
- The `dev` image contains the committed sample data (it is in the repository). Don't push it to a registry.
- The images do **not** contain the tokenizer files (`data/tokenizers/` is git-ignored data), so in the container the exact-tokenizer tests skip and counts use the labelled chars/4 approximation (Stage 10 roadmap: a fetch step in the `dev` image).
- Optional PostgreSQL (Stage 9; nothing uses it yet): set `METIS_DB_PASSWORD` in `.env`, then `docker compose --profile db up -d postgres`. It listens on `127.0.0.1:5432` only.
- The base image is pinned by digest in the `Dockerfile` (multi-arch, checked 2026-10-18). To update it, pull `python:3.13-slim`, replace the digest, and rerun the commands above.
- **Verified 2026-10-18** (Docker 29.8.2, Compose v5.5.1, Apple Silicon, linux/arm64): `dev` image smoke test 16/16 and full suite 392/392; `runtime` image runs the walking skeleton with the same config hash as a native run; neither image contains `.env`, `config/local.toml`, or the spend ledger (see progress.md).

## 7. Where things go

- New config data: `config/` (rules: [repository_structure.md §5](../architecture/repository_structure.md#5-configuration-files-config)).
- Experiment configs: `experiments/<area>/<EXP-ID>/config.toml` (Stage 8). They may not set `live`, `budget`, `paths`, or `dev`.
- Never write into `data/sample_data/raw/` (read-only).
