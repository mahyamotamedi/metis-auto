# CLAUDE.md

Durable working rules for agent sessions on Metis-Auto. Keep this file short and link to the docs rather than copying them. Also follow [`AGENTS.md`](AGENTS.md) (issue tracker in `.scratch/`, triage labels, `GLOSSARY.md` / `docs/adr/` conventions).

## Where things live
- Project state: [`docs/project/progress.md`](docs/project/progress.md). Read it first.
- Context & unknowns: [`docs/project/context.md`](docs/project/context.md).
- Requirements & traceability: [`docs/project/requirements.md`](docs/project/requirements.md). Every design element must cite an `FR-`/`QA-`/`NG-` or hypothesis/experiment ID. Terms: [`GLOSSARY.md`](GLOSSARY.md).
- Assumptions & open questions: [`docs/project/assumptions_and_questions.md`](docs/project/assumptions_and_questions.md).
- Decision records: `docs/adr/` (`NNNN-slug.md`: context, alternatives, decision, consequences). Docs index: [`docs/README.md`](docs/README.md).
- Architecture (Stage 3): [`docs/architecture/README.md`](docs/architecture/README.md). Components are `CMP-nn`; principle P-1: port calls happen in `application`, decisions in pure `domain` code.
- Modules (Stage 5): [`docs/architecture/module_reference.md`](docs/architecture/module_reference.md): who calls what, data in/out, status. Its import column is checked by `tests/architecture/test_module_reference.py`; update the row with the code. Walking skeleton: `python scripts/run_walking_skeleton.py`.
- Contracts (Stage 4): [`docs/architecture/contracts.md`](docs/architecture/contracts.md) ([ADR-0017](docs/adr/0017-contract-modelling-with-pydantic.md)). Every contract field declares a privacy class; event and run records may hold no `content` field (tested). After changing a contract, regenerate the field reference: `python tests/architecture/contracts_docgen.py`.
- **Where a new file goes and what it may import:** [`docs/architecture/repository_structure.md`](docs/architecture/repository_structure.md) ([ADR-0009](docs/adr/0009-repository-structure-and-dependency-rules.md)). Layer rules are enforced by `tests/architecture/test_import_rules.py`. Candidate strategies stay in `experiments/` until promoted.
- Sample EDA: `experiments/sample_eda/`, `docs/sample_eda/`, `reports/sample_eda/`.
- Project brief: [`docs/brief/project-draft.pdf`](docs/brief/project-draft.pdf). Master prompt: [`metis_claude_code_master_prompt.md`](metis_claude_code_master_prompt.md).

## Data and privacy
- `data/sample_data/raw/` is **read-only**. Never modify it; write derived data elsewhere.
- Never put raw message content, instructions, RAG context, or attachments into docs, commits, logs, test fixtures, or exported tables. Use hashed or opaque IDs and derived features. Synthetic fixtures must be clearly labelled synthetic.
- Category names are opaque strata. Do not interpret them or tune to one category.
- **The sample EDA is exploratory only** ([ADR-0008](docs/adr/0008-sample-eda-is-exploratory.md)):
  - Its numbers (including the master prompt's "Key EDA facts") are provisional signals to re-verify on the full dataset. Designs may be informed by them but must not depend on their exact values.
  - Never import, copy, or build on `experiments/sample_eda/eda_helpers.py`. Read it only for reference; re-implement needed logic properly, with tests.
  - Don't shape contracts or data interfaces around sample quirks.
  - The full-dataset EDA lives separately from the sample EDA, which is preliminary.

## Git
- **Never run `git commit`, `git push`, or any command that rewrites git history** (e.g. `rebase`, `reset`, `commit --amend`, `push --force`, `filter-branch`). The user reviews and commits all changes.
- At the end of each stage, list the changed files and suggest a commit message, but do not commit.

## How to work
- Work stage by stage. At the end of each stage, give the 6-part report (changes, decisions, assumptions, questions, next stage, exit criteria). Update `progress.md` and then **stop** for review.
- Inspect before deciding. Don't delete, move, or restructure existing work (especially EDA, data, and reports) without approval.
- Label assumptions as current, future, or speculative, and design elements as decided, provisional, or open.
- Never fabricate prices, model capabilities, tokenizer behaviour, API signatures, or data facts. Cite the source and the check date, and mark the fact for re-verification.
- Keep the design simple and replaceable. Prices, catalogues, thresholds, and strategies are configuration, not code.
- Tests run offline with no API keys. Network tests are opt-in.
- Tooling ([ADR-0001](docs/adr/0001-python-tooling.md)): Python 3.13 in `.venv`, created from a real Python 3.13 (`/opt/homebrew/bin/python3.13`), **not from conda base**. Install: `.venv/bin/pip install --require-hashes -r requirements-dev.lock && .venv/bin/pip install -e . --no-deps`. Dependencies live in `pyproject.toml`; regenerate the locks with pip-tools on purpose. **ruff** for lint and format (not black). Run tests with `.venv/bin/python -m pytest`.
- No real model calls by default. Use mocks or recorded responses. Live calls are opt-in under a spending cap ([ADR-0003](docs/adr/0003-offline-by-default-model-calls.md)). Baselines are configuration ([ADR-0002](docs/adr/0002-configurable-baselines.md)).
