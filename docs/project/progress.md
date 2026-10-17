# Project Progress

Single source of truth for stage status across sessions. Stage definitions: master prompt §5 ([`metis_claude_code_master_prompt.md`](../../metis_claude_code_master_prompt.md)). Decision records: [`docs/adr/`](../adr/).

| Stage | Title | Status | Exit criteria met? |
|---|---|---|---|
| 0 | Orientation & inventory | done (answers recorded) | Yes |
| 1 | Requirements, quality attributes, scope | done | Yes |
| 2 | Repository structure proposal | done | Yes |
| 3 | Architecture & system design | **awaiting review** | Yes (pending your confirmation) |
| 4 | Internal contracts | not started | — |
| 5 | Skeletons & wiring | not started | — |
| 6 | Configuration, environment, containers | not started | — |
| 7 | Token & cost accounting utility | not started | — |
| 8 | Experiment framework & exact-cache baseline | not started | — |
| 9 | Data layer plan | not started | — |
| 10 | Architecture review & roadmap | not started | — |

---

## Stage 0 — Orientation & inventory (2026-10-14)

**Outputs:**
- [context.md](context.md) — problem, brief summary, repository inventory, data shape, facts/hypotheses/unknowns, brief↔data conflicts, evaluation weaknesses.
- [assumptions_and_questions.md](assumptions_and_questions.md) — the register.
- this file.
- [`CLAUDE.md`](../../CLAUDE.md) — durable agent rules.

**Repo operations:**
- Local `main` was fast-forwarded to `origin/main` (`5a9421a`).
- `sys-des` was rebased onto it, because it had been cut from a stale `main` without the EDA.
- Tests: 3/3 pass.
- Data hash is unchanged.

**Open questions raised:** Q-01 … Q-11. The most pressing are Q-03 (gitignore), Q-05 (premium baseline), Q-07 (tooling), and Q-08 (live calls).

**Tooling proposal:** superseded by [ADR-0001](../adr/0001-python-tooling.md). See the follow-up below.

**Exit criteria:** "I can read one document and understand the problem, the data's real shape and limits, and what is unknown." That document is [context.md](context.md). Met, pending review.

### Stage 0 follow-up — answers to open questions (2026-10-14)

**Recorded:** answers in the [register](assumptions_and_questions.md).

| Question | Status |
|---|---|
| Q-01 | answered |
| Q-02 | answered |
| Q-03 | answered |
| Q-07 | answered |
| Q-08 | partly answered |
| Q-05 | open |
| Q-10 | open |
| Q-11 | open |
| Q-12 | new, open |
| Q-04, Q-06, Q-09 | open; grouped as "questions for the data owner", with unverified working assumptions A-06, A-14, A-15, A-16 |

**Decision records:**
- [ADR-0001](../adr/0001-python-tooling.md) — Python tooling: 3.13, venv + pip, pyproject, pip-tools lock (provisional), ruff, pytest.
- [ADR-0002](../adr/0002-configurable-baselines.md) — configurable premium placeholder plus mandatory as-logged baseline.
- [ADR-0003](../adr/0003-offline-by-default-model-calls.md) — offline by default; live calls opt-in with a spending cap; `.env.example` key guidance in Stage 6.
- [ADR-0004](../adr/0004-repository-hygiene.md) — repository hygiene.

**Repo changes:**
- `.gitignore`: removed the `AGENTS.md` and `docs/agents/` lines.
- `.idea/` and `.vscode/` untracked (`git rm --cached`; local files kept).
- Brief copied to `docs/brief/project-draft.pdf`.
- Master prompt renamed to `metis_claude_code_master_prompt.md`.

**Carried into later stages:**
- Stage 2: proposed home for `docs/agents/` content and the master prompt.
- Stage 6: `.env.example` with commented provider-key entries and insertion instructions; spending-cap config.
- Stage 5/6: create `pyproject.toml` and the lockfiles. TODO-08: install a standalone Python 3.13.

**Stage 0 status:** approved; Stage 1 started 2026-10-14.

---

## Stage 1 — Requirements, quality attributes, scope (2026-10-14)

**Outputs:**
- [requirements.md](requirements.md):
  - goals G-1…G-7
  - functional requirements in 14 areas (`FR-REQ`, `FEAT`, `ROUTE`, `XCACHE`, `SCACHE`, `CTX`, `CASC`, `FAIL`, `ACCT`, `OBS`, `EVAL`, `DATA`, `API`, `FIN`)
  - 8 quality attributes with measurement methods
  - non-goals NG-01…NG-13
  - brief→data-support map BR-01…BR-18
  - the traceability rule and matrix
- [ADR-0005](../adr/0005-current-phase-scope.md): current-phase scope. Offline foundation, an in-process API, and brief Action 3 deferred (its data enablers stay in scope). **Provisional** pending Q-17.
- [ADR-0006](../adr/0006-evaluation-metric-definitions.md): the brief's four metrics made defensible:
  - quality is split into agreement, judge, and non-inferiority;
  - hit rate is always paired with hit correctness;
  - cost carries its fidelity and price version;
  - latency is split into overhead (offline) and model/end-to-end (live only).
- [`GLOSSARY.md`](../../GLOSSARY.md): the domain terms settled in this stage.
- Register: assumptions A-18…A-22 and questions Q-13…Q-17.
- [`CLAUDE.md`](../../CLAUDE.md) and [context.md](context.md): pointers added.

**Open questions raised:**
- Q-13 (quality margin δ)
- Q-14 (latency budget)
- Q-15 (future gateway API compatibility)
- Q-16 (cache sharing scope)
- Q-17 (confirm the Action 3 deferral)

None of these blocks Stage 2.

**Exit criteria:** "Every later design element can be traced to a requirement or an experiment." **Met, pending review.** Every requirement has an ID and a source, the traceability rule is in requirements.md §7, and hypotheses H-1…H-7 cover the experimental elements (experiment IDs come in Stage 8).

**Stage 1 status:** awaiting your approval to start Stage 2.

### Stage 1 follow-up — answers to Q-13…Q-17 (2026-10-14)

| Question | Status | Answer |
|---|---|---|
| Q-17 | answered | Action 3 deferred. The event design must still carry everything a dashboard needs. |
| Q-16 | partly answered | Serving default `session`; scope configurable (`session` / `user` / `global`); cross-session and cross-user candidates measured separately; final policy open. |
| Q-13 | answered (provisional) | Judge score drops ≤ 3% overall and ≤ 5% per stratum. LLM judge calibrated against human ratings is primary; agreement is secondary. |
| Q-14 | answered (provisional) | Overhead ≤ 100 ms at p95. |
| Q-15 | open | Separate external-API adapter layer; provisional default OpenAI-compatible chat-completions style. |

**Decision records:**
- ADR-0005 is now decided.
- ADR-0006 gains the provisional thresholds.
- New: [ADR-0007](../adr/0007-cache-sharing-scope.md) (cache sharing scope).

**Interpretations to confirm:**
- In Q-13, the percentages are relative to the baseline mean.
- In Q-14, the overhead covers all of Metis's pre-model work (features, embeddings, cache lookup, routing, context building).

### Stage 1 follow-up — sample EDA is exploratory (2026-10-14)

**Decision:** [ADR-0008](../adr/0008-sample-eda-is-exploratory.md).
- Sample-EDA numbers are provisional signals.
- The EDA helpers are reference-only and must not be reused.
- No sample-shaped contracts.
- The full-dataset EDA gets its own home.

**Updated:**
- `CLAUDE.md`: new durable rule.
- context.md: §4 and §5.1 reframed as sample signals; helper row changed.
- requirements.md: source note; BR-01; FR-REQ-03 and FR-DATA-03 changed; new FR-DATA-06…08; the §6 caveat.
- Register: A-01 revised, A-08 split into principle and share, new A-23 and A-24.
- Sample EDA marked preliminary: banners on `docs/sample_eda/*.md`, and READMEs in `experiments/sample_eda/` and `reports/sample_eda/`. No content changed.

**Carried into later stages:**
- **Stage 2:** propose a dedicated full-dataset EDA home (notebooks, analysis code, reports, outputs), separate from the sample EDA. Add a dependency rule that nothing outside the sample EDA imports from `experiments/sample_eda/`.
- **Stage 9:** the onboarding checklist starts with a proper full EDA that re-checks every sample signal (`F-n`, the master prompt's EDA list) and Q-04, Q-06, and Q-09.

**Stage 1 status:** approved (the instruction to continue with Stage 2, 2026-10-14). Stage 2 started 2026-10-14.

---

## Stage 2 — Repository structure (2026-10-14)

**Working rule added:** `CLAUDE.md` § Git. Agents never commit, push, or rewrite history; each stage ends with a list of changed files and a suggested commit message.

**Outputs:**
- [repository_structure.md](../architecture/repository_structure.md):
  - top-level layout;
  - ten package layers, each with a purpose, what belongs, what doesn't, and traces;
  - dependency rules with a Mermaid view;
  - test, config, experiment, report, data, and docs conventions;
  - the **promotion process**;
  - a "where does my file go" table.
- [ADR-0009](../adr/0009-repository-structure-and-dependency-rules.md): structure and dependency rules. It resolves the ADR-0004 carry-overs (master prompt and `docs/agents/` both stay) and the ADR-0008 full-EDA home.
- `src/metis_auto/` + 10 sub-packages: each `__init__.py` holds only a docstring (responsibility, import rights, traces).
- `tests/architecture/test_import_rules.py`: a stdlib `ast` check of the layer rules and the "nothing imports sample-EDA helpers" rule (notebooks included), with self-tests on synthetic trees.
- README stubs: `config/`, `experiments/` and its five new areas (`routing`, `caching`, `context`, `cost`, `evaluation`), `experiments/full_eda/`, and `reports/`.
- [docs/README.md](../README.md): docs index (MP§6).
- Updated:
  - `.gitignore`: `data/full_data/`, `data/derived/`, `data/recorded/`, `runs/`;
  - `README.md` structure section;
  - `CLAUDE.md` pointers;
  - `GLOSSARY.md`: Port, Adapter, Composition root, Promotion;
  - [requirements.md](requirements.md) §7: the "Stage 2 home" column filled in;
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

---

## Stage 3 — Architecture & system design (2026-10-14)

**Outputs** (index: [architecture/README.md](../architecture/README.md)):
- [overview.md](../architecture/overview.md):
  - principles P-1…P-8; the central one is P-1, "measure in `application`, decide in `domain`";
  - the high-level architecture;
  - a component catalogue (CMP-01…26, plus deferred F1…F4), each with home, responsibility, inputs, outputs, dependencies, status, and traces;
  - component interaction;
  - the provisional contract vocabulary for Stage 4;
  - fit with the repository structure.
- Flow documents:
  - [request_lifecycle.md](../architecture/request_lifecycle.md): lifecycle and data flow, with the privacy boundary;
  - [routing.md](../architecture/routing.md);
  - [caching.md](../architecture/caching.md);
  - [context_construction.md](../architecture/context_construction.md);
  - [attempts.md](../architecture/attempts.md): escalation, failover, retries, and the detector catalogue;
  - [evaluation.md](../architecture/evaluation.md);
  - [configuration.md](../architecture/configuration.md);
  - [observability.md](../architecture/observability.md);
  - [providers.md](../architecture/providers.md);
  - [deployment_and_data.md](../architecture/deployment_and_data.md).
- 11 new Mermaid diagrams. Each states the question it answers, and every arrow carries a provisional contract name or a call.
- Decision records:
  - [ADR-0010](../adr/0010-request-pipeline-shape.md): pipeline shape;
  - [ADR-0011](../adr/0011-cache-key-and-lookup-design.md): cache key and lookup;
  - [ADR-0012](../adr/0012-event-stream-as-measurement-record.md): the event stream as the measurement record;
  - [ADR-0013](../adr/0013-unified-attempt-model.md): unified attempt model;
  - [ADR-0014](../adr/0014-counterfactual-answers-via-model-client.md): counterfactual answers via `ModelClient`;
  - [ADR-0015](../adr/0015-keyed-content-fingerprints.md): keyed fingerprints (provisional).
- Updated:
  - [repository_structure.md](../architecture/repository_structure.md): sub-package names (S3-1), the ports list, and a note on the pending S3-2;
  - [docs/README.md](../README.md);
  - [requirements.md](requirements.md) §7: the "Stage 3 view" column now links to the documents;
  - register: A-25 is now decided; new A-28…A-33, Q-19, Q-20; TODO-06 and TODO-07 notes;
  - `GLOSSARY.md`: 10 terms;
  - `CLAUDE.md`: architecture pointer.

**Structure changes (ADR-0009):**
- No new layer, and no change to the import rules or the import test.
- S3-1 (sub-package names, which were provisional) was applied to the docs: `domain/escalation` → `domain/attempts`; `application/{pipeline, measurement, events}`; and so on.
- S3-2 (`domain` imports only `contracts`) is **proposed, not applied** (Q-19).

**Validation:**
- All 12 Mermaid blocks in `docs/architecture/` (11 new plus the Stage 2 one) parse with Mermaid 11.4.1, run under Node with jsdom in a scratch directory outside the repo. Parsing checks syntax; visual layout was not inspected.
- All relative links and section anchors in the changed docs resolve.
- Every `CMP-nn` used is defined.
- Tests: 8/8 pass offline (no code changed).
- The raw-data hash is unchanged.

**Open questions raised:**
- Q-19 (approve S3-2).
- Q-20 (confirm keyed fingerprints and who holds the key).

**Carried into later stages:**
- **Stage 4:** fix fields and names for the §5 contract vocabulary, and rename diagram labels to match. Privacy class per field, plus a test that event payloads carry no content classes. Retrieval document IDs and scores as an optional request field (FR-OBS-04). `counterfactual_source` and coverage on results.
- **Stage 5:** sub-packages per S3-1; one orchestrator with one method per stage; fault- and quality-injecting fakes; seeded `IdSource` and `Clock`.
- **Stage 6:** config format and precedence mechanism; the "live needs two keys" rule; the fingerprint key in `.env.example`.
- **Stage 7:** the catalogue and price schema (fields in providers.md §4).
- **Stage 8:** strategy loading; detector experiments; counterfactual source per plan; multi-variant cache-key measurement.

**Exit criteria:** "Every component has an owner responsibility, inputs, outputs, and dependencies; the diagrams and text agree." **Met, pending review.** See overview §3 for the catalogue. Diagram/text agreement was checked by hand for event names, stage order, eligibility rules, error classes, and the overflow rule. One drift was found and fixed: the re-route wording in the lifecycle doc.
