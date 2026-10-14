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
- `config/` — versioned configuration data (catalogue, prices, defaults); no secrets
- `experiments/` — experiment definitions and notebooks, by area; `sample_eda/` is preliminary and frozen
- `reports/` — committed, feature-only outputs, figures, and tables
- `data/` — datasets (`sample_data/raw/` is read-only)
- `tests/` — automated tests, all offline by default
- `docs/` — documentation; start at [`docs/README.md`](docs/README.md)

Where new files go and what each package may import: [`docs/architecture/repository_structure.md`](docs/architecture/repository_structure.md).

## Development Workflow

Experimental implementations are developed independently on feature branches.

The team compares results and selectively merges the strongest analyses and reusable components into `main`.

## Project Status

Active development.
