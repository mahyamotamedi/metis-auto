# ADR-0009: Repository structure — layered `src/metis_auto` package, enforced import rules, experiments outside the package

- Status: **decided** (top-level layout and dependency rules). Sub-package names are **provisional** until Stage 3/5. The experiment-loading mechanism is **provisional** until Stage 8.
- Date: 2026-10-14
- Resolves: Stage 2 carry-overs from ADR-0004 (where `docs/agents/` and the master prompt live) and ADR-0008 point 4 (home of the full-dataset EDA)
- Detail: [repository_structure.md](../architecture/repository_structure.md)

## Context
The repo had a flat layout: `data/`, `experiments/sample_eda/`, `reports/sample_eda/`, an empty `src/metis_auto/`, and `tests/`. The master prompt (MP§4) asks for separate layers: experiments, domain logic, application, infrastructure adapters, evaluation, and production code. It also asks for an explicit promotion process so that experimental code can't drift into production.

The requirements add further needs:
- pure, replayable policies (FR-ROUTE-07);
- replaceability by "one interface plus one config entry" (QA-REPL);
- storage independence (FR-DATA-02);
- no reuse of the sample-EDA helpers (FR-DATA-08, ADR-0008).

## Decision
1. **One installable package, `src/metis_auto/`, with ten top-level layers:**
   - `contracts`: data models;
   - `ports`: interfaces;
   - `domain`: pure policies and accounting;
   - `application`: request orchestration;
   - `adapters`: infrastructure implementations;
   - `data_access`: the data layer;
   - `settings`: config loading;
   - `evaluation`: replay, metrics, runner;
   - `analysis`: tested full-EDA code;
   - `wiring`: composition root.
2. **Import rules are a fixed table** (structure doc §3.1). Dependencies point inward, toward `contracts`. Only `wiring` may import concrete `adapters` and `data_access`. `evaluation` receives built pipelines and never imports `wiring`. **A stdlib test enforces the rules** (`tests/architecture/test_import_rules.py`).
3. **Experiments live outside the package** in `experiments/<area>/<EXP-ID>-<slug>/`. The areas are routing, caching, context, cost, evaluation, and full_eda. Experiments may import `metis_auto`; `metis_auto` never imports experiments. Nothing imports `experiments/sample_eda/` except its own existing test.
4. **Promotion process** (structure doc §6.2): evidence vs. both baselines → move into the package under the import rules → offline tests → selectable by one config entry → docs, plus a decision record. Production defaults may name only promoted components.
5. **Full-dataset EDA home** mirrors the sample EDA, but keeps its logic in the package:
   - notebooks in `experiments/full_eda/`;
   - tested analysis code in `src/metis_auto/analysis/`;
   - outputs in `reports/full_eda/`;
   - write-up in `docs/full_eda/`.
6. **Data paths.** `data/full_data/`, `data/derived/`, `data/recorded/`, and `runs/` are gitignored. Keeping the full dataset out of git was confirmed by the owner (Q-18, 2026-10-14). Only `data_access` reads dataset paths.
7. **Nothing existing moves:**
   - `docs/agents/` stays. `AGENTS.md` and the agent-skill conventions it documents reference that path.
   - The master prompt stays at the root. `CLAUDE.md` and the requirements' `MP§` citations link to it, and moving it gains nothing.
   - `tests/test_sample_eda_helpers.py` stays where it is.
8. **Placeholder homes only** for the deferred gateway (`src/metis_auto/gateway/`) and the dashboard (ADR-0005). They are documented but not created.

## Alternatives considered
- **Flat package** (one module per mechanism, no layer split). Simpler at first, but nothing stops a routing policy from importing a provider SDK. FR-ROUTE-07 and QA-REPL would then depend on discipline alone. Rejected.
- **Interfaces next to their consumers** (e.g. a cache-store protocol inside `domain/caching`), with no `ports` package. This is idiomatic Python and has one fewer package. But adapters would then import `domain`, which blurs the "adapters know no business rules" boundary, and the import rules would get harder to state. Rejected for now. It can be revisited if `ports` grows awkward.
- **Candidate strategies inside the package**, flagged experimental (e.g. `domain/routing/experimental/`). Easier to load, but this is exactly the drift MP§4 warns about. Rejected; candidates stay in `experiments/` until promoted.
- **Separate packages per layer** (multiple distributions). Overkill for one team and one deployable. Rejected.
- **`import-linter` now.** It needs `pyproject.toml`, which arrives in Stage 5/6. A stdlib test covers the current rules. Revisit when the rules outgrow the test.
- **Move the master prompt to `docs/brief/`, and `docs/agents/` under `.claude/` or the root.** Neither move solves a problem, and both break existing links. Rejected.

## Consequences
- Every later module has a predetermined home and import rights. Stage 3 component boundaries must map onto these layers, or this ADR is amended.
- `pyproject.toml` (Stage 5/6) must use the `src/` layout and include `metis_auto` and all sub-packages.
- Experiment strategy loading needs a small mechanism in Stage 8 that is unavailable to production defaults.
- The `ports` layer adds one hop of indirection, so each swap point is declared once and explicitly.
- `src/metis_auto/.gitkeep` is now redundant next to `__init__.py`. It is left in place; the owner may remove it.
