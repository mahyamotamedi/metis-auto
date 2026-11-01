# Metis Auto

Metis Auto is an experimental LLM optimization platform focused on reducing inference cost while preserving response quality and latency.

The project explores:

- intelligent model routing
- semantic caching
- context reduction
- provider selection
- fallback and escalation strategies
- cost and latency observability

## Repository Structure

- `src/metis_auto/` — the package, in layers: contracts, ports, domain, application, adapters, data_access, settings, evaluation, analysis, wiring
- `config/` — versioned configuration data (TOML: defaults, model catalogue, prices, endpoints, baselines); no secrets
- `experiments/` — experiment definitions and notebooks, by area; `sample_eda/` is preliminary and frozen
- `reports/` — committed, feature-only outputs, figures, and tables
- `data/` — datasets (`sample_data/raw/` is read-only)
- `tests/` — automated tests, all offline by default
- `docs/` — documentation; start at [`docs/README.md`](docs/README.md)

Evaluation dataset and local PostgreSQL: [`docs/evaluation/golden_v1.md`](docs/evaluation/golden_v1.md); teammate setup: [`docs/guides/team_setup.md`](docs/guides/team_setup.md).

Where new files go and what each package may import: [`docs/architecture/repository_structure.md`](docs/architecture/repository_structure.md).

## Development Setup

Python 3.13 from a non-conda interpreter ([ADR-0001](docs/adr/0001-python-tooling.md)):

```sh
python3.13 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install -e . --no-deps
.venv/bin/python scripts/fetch_tokenizer_assets.py # once: tokenizer files (network, no key)
.venv/bin/python -m pytest                       # offline; network tests need --run-network
.venv/bin/python scripts/run_walking_skeleton.py # the pipeline end to end with fakes
.venv/bin/python scripts/chat.py --fake          # the terminal demo (Demo A), offline
```

The demo UI in the browser (Demo B; Streamlit, extra `ui`, never in the runtime lock):

```sh
.venv/bin/pip install --require-hashes -r requirements-ui.lock && .venv/bin/pip install -e . --no-deps
.venv/bin/python scripts/demo_ui.py              # http://localhost:8501, fake mode by default
```

Optional, for EXPERIMENTAL LLMLingua-2 compression only: `requirements-compress.lock` (torch; never in the runtime lock) and `scripts/fetch_compressor_assets.py` (about 2.2 GB, sha256-pinned); see the [local development guide](docs/guides/local_development.md).

No secrets are needed for tests or the walking skeleton. Containers (`docker compose run --rm app`), configuration layers, the `.env` file (copy from `.env.example`), and the live-call budget (10 USD lifetime cap under a 20 USD project ceiling, [ADR-0018](docs/adr/0018-live-calls-for-development-under-a-lifetime-budget.md)) are explained in the [local development guide](docs/guides/local_development.md).

**New to the project and want to try the demo?** Start with the [demo quickstart](docs/guides/demo_quickstart.md): setup, free fake mode, the browser UI and a 5-minute demo script, the terminal demo, reading the cost panel, your own Metis key, the `config/local.toml` safety switch, the shared budget, and troubleshooting.

## Development Workflow

Experimental implementations are developed independently on feature branches.

The team compares results and selectively merges the strongest analyses and reusable components into `main`.

## Project Status

Active development.
