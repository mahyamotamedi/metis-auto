## Stage 2 — Repository structure (2026-10-14)

**Working rule added:** `CLAUDE.md` § Git. Agents never commit, push, or rewrite history; each stage ends with a list of changed files and a suggested commit message.

**Outputs:**
- [repository_structure.md](../../architecture/repository_structure.md):
  - top-level layout;
  - ten package layers, each with a purpose, what belongs, what doesn't, and traces;
  - dependency rules with a Mermaid view;
  - test, config, experiment, report, data, and docs conventions;
  - the **promotion process**;
  - a "where does my file go" table.
- [ADR-0009](../../adr/0009-repository-structure-and-dependency-rules.md): structure and dependency rules. It resolves the ADR-0004 carry-overs (master prompt and `docs/agents/` both stay) and the ADR-0008 full-EDA home.
- `src/metis_auto/` + 10 sub-packages: each `__init__.py` holds only a docstring (responsibility, import rights, traces).
- `tests/architecture/test_import_rules.py`: a stdlib `ast` check of the layer rules and the "nothing imports sample-EDA helpers" rule (notebooks included), with self-tests on synthetic trees.
- README stubs: `config/`, `experiments/` and its five new areas (`routing`, `caching`, `context`, `cost`, `evaluation`), `experiments/full_eda/`, and `reports/`.
- [docs/README.md](../../README.md): docs index (MP§6).
- Updated:
  - `.gitignore`: `data/full_data/`, `data/derived/`, `data/recorded/`, `runs/`;
  - `README.md` structure section;
  - `CLAUDE.md` pointers;
  - `GLOSSARY.md`: Port, Adapter, Composition root, Promotion;
  - [requirements.md](../requirements.md) §7: the "Stage 2 home" column filled in;
  - register: A-25…A-27, Q-18, and Q-02/Q-03 notes.

**Not moved or deleted:** nothing. `src/metis_auto/.gitkeep` is now redundant but left in place for you to remove.

**Tests:** 8/8 pass offline (3 existing + 5 new), run with the Anaconda Python 3.13 because the project venv doesn't exist yet (TODO-08). ruff is not installed, so lint has not been run; new code was kept within ruff's default 88-column limit by hand. The raw-data hash is unchanged.

**Open questions raised:** Q-18 (keep the full dataset out of git?). **Answered 2026-10-14: yes.** A-27 is now decided.

**Carried into later stages:**
- **Stage 3:** map every component onto a layer (A-25). Amend ADR-0009 if a component doesn't fit.
- **Stage 5:** create the sub-packages; `pyproject.toml` with the `src` layout; the `network` pytest marker; consider `import-linter` (A-26).
- **Stage 8:** the experiment strategy-loading mechanism, unavailable to production defaults; the `EXP-ID` naming.

**Exit criteria:** "A newcomer can tell where any future file should go and what it may import." Met, pending review: §10 of the structure doc answers *where*, and §3 plus the package docstrings answer *what it may import*. A test enforces the import rules.

**Stage 2 status:** approved (the instruction to continue with Stage 3, 2026-10-14). Stage 3 started 2026-10-14.
