# ADR-0001: Python tooling — 3.13, venv + pip, pyproject, locked deps, ruff, pytest

- Status: **decided** (the locking mechanism is **provisional**)
- Date: 2026-10-14
- Resolves: Q-07

## Context
The repo had no dependency declaration. The EDA ran in an Anaconda Python 3.13.5 kernel and was formatted with black (via `.vscode` settings). The tests are unittest-style but already run under pytest. Experiments must be reproducible, so the same dependency versions are needed on every machine and in containers (Stage 6).

## Decision
- **Python 3.13.**
- **venv + pip**, with dependencies declared in `pyproject.toml` (`src/metis_auto` layout). Development and experiment tools go in optional dependency groups (e.g. `dev`).
- The venv must be created from a **real Python 3.13 interpreter, not from inside conda base**. Example: `python3.13 -m venv .venv`, where `python3.13` comes from python.org, Homebrew, or pyenv. Conda's interpreter carries conda-specific site configuration and makes builds differ between machines and the Docker image.
- **ruff** for both linting and formatting (`ruff check`, `ruff format`). **black is dropped.** The ruff config lives in `pyproject.toml`.
- **pytest** is the test runner. Existing unittest-style tests stay as they are; pytest runs them.

### Locking (provisional — set up when `pyproject.toml` is created in Stage 5/6)
Proposal: **pip-tools** compiles a hash-pinned lockfile from `pyproject.toml`:
- `pip-compile --generate-hashes --extra dev -o requirements-dev.lock pyproject.toml` (and one lockfile without extras, for runtime images).
- Install with `pip install --require-hashes -r requirements-dev.lock`, then `pip install -e . --no-deps`.
- The lockfiles are committed and regenerated on purpose (an upgrade is its own reviewable change).

## Alternatives considered
- **`pip freeze > requirements.txt`.** Simple, but it captures whatever happens to be installed, has no hashes, and mixes direct and transitive dependencies without traceability.
- **`pip lock` (PEP 751 `pylock.toml`).** Present in the local pip 25.1, checked 2026-10-14, but marked **experimental**. Whether pip can *install* from `pylock.toml` is unverified and needs re-checking. This standards-based option is worth revisiting once it is stable.
- **uv / poetry.** Rejected by the user's choice of plain venv + pip.
- **conda environment.** Rejected. It also explains the "not from conda base" rule.

## Consequences
- **Setup TODO:** this machine has no non-conda Python 3.13. Found on 2026-10-14: Anaconda 3.13.5, python.org 3.14, and system 3.9.6. A standalone 3.13 must be installed before the first venv. The Docker image (Stage 6) will use an official `python:3.13` base image.
- Contributors who use `.vscode` with black must switch their editor to ruff. `.vscode/` is no longer tracked (ADR-0004), so this is per developer.
- pip-tools becomes a dev dependency.
