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
```

No secrets are needed for tests or the walking skeleton. Containers (`docker compose run --rm app`), configuration layers, the `.env` file (copy from `.env.example`), and the live-call budget (20 USD lifetime, [ADR-0018](docs/adr/0018-live-calls-for-development-under-a-lifetime-budget.md)) are explained in the [local development guide](docs/guides/local_development.md).

## Development Workflow

Experimental implementations are developed independently on feature branches.

The team compares results and selectively merges the strongest analyses and reusable components into `main`.

## Project Status

Active development.
