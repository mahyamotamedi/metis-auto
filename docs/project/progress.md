# Project Progress

Single source of truth for stage status across sessions. Stage definitions: master prompt §5 ([`metis_claude_code_master_prompt.md`](../../metis_claude_code_master_prompt.md)). Decision records: [`docs/adr/`](../adr/).

| Stage | Title | Status | Exit criteria met? |
|---|---|---|---|
| 0 | Orientation & inventory | done (answers recorded) | Yes |
| 1 | Requirements, quality attributes, scope | done | Yes |
| 2 | Repository structure proposal | done | Yes |
| 3 | Architecture & system design | done (approved by the instruction to continue, 2026-10-17) | Yes |
| 4 | Internal contracts | done (approved by the instruction to continue, 2026-10-18) | Yes (the configuration diagram was labelled in Stage 6) |
| 5 | Skeletons & wiring | done (approved by the instruction to continue with Stage 6, 2026-10-18) | Yes |
| 6 | Configuration, environment, containers | done (approved by the instruction to continue with Stage 7, 2026-10-18) | Yes: native and container |
| 7 | Token & cost accounting utility (+ brief §12 items) | done (approved by the instruction to continue with Stage 8, 2026-10-18) | Yes |
| 7.5 | Live adapter and wrapper check (**new**, small; [brief](live_testing_and_demo_brief.md) §12) | done (approved by the instruction to continue with Stage 8, 2026-10-18) | Yes |
| 8 | Experiment framework & exact-cache baseline (+ sample loader, pairing, case builder pulled forward from Stage 9) | **awaiting review** (2026-10-18; follow-up 2026-10-19: Q-37, Q-38) | **Yes** (see below) |
| Demo | Demo milestone (**new**, after Stage 8; brief §12; includes the required teammate quickstart): **A** backend, **B** UI | **A: awaiting review** (2026-10-19); B: not started | A: **yes** (see below); B: — |
| 9 | Data layer plan | not started | — |
| 10 | Architecture review & roadmap | not started | — |

**Planned steps added 2026-10-18 from the [owner's brief](live_testing_and_demo_brief.md) §12** (not started; scope as the brief states it):
- **Stage 7 additions:** ~~tokenizers for the six catalogue models; price schema with cached input, cache writes, and context-length tiers; the premium-baseline estimate (brief §5); `scripts/measure_overhead.py` (brief §11)~~ **done in Stage 7**, plus the savings decomposition (brief §6) as pure functions, ahead of the Demo milestone.
- **Stage 7.5 (new, small):** one live OpenAI-compatible adapter (base URL per family; SDK auto-retries off; normalised errors; provider-reported usage, finish reason, cached tokens, and model); the tiny live wrapper check (brief §3), results recorded with dates; a `scripts/chat.py` CLI. Prerequisites: TODO-10 (context windows), the spend-guard TODO for uncomputable actual costs, Q-29.
- **Stage 8 additions:** ~~the sample loader, pairing heuristic, and replay-case builder pulled forward from Stage 9; the sticky-routing experiment plan (brief §7)~~ **done in Stage 8.**
- **Demo milestone (after Stage 8):** rule-based plus sticky routing v1; the LLMLingua-2 strategy as a labelled experimental toggle (heavy dependencies in an optional extra); demo cache scope and seed; showing the savings decomposition (computed since Stage 7, `AccountingService.decompose`); a Streamlit UI as a thin wrapper over `wiring` (brief §10).
  - **Required deliverable (owner, 2026-10-18; brief §10, §12 amended):** [`docs/guides/demo_quickstart.md`](../guides/demo_quickstart.md), the teammate quickstart. Drafted on 2026-10-18 for everything that exists today (setup, fake and real-model modes, `.env` and the key, `config/local.toml`, the budget and the per-computer ledger, `chat.py` and the cost panel, troubleshooting). **To complete in the Demo milestone:** the UI start command, its toggles, and a screenshot (§7), and the compression row. The milestone is not done until the guide is followed end to end on a fresh clone.
- **Stage 10 roadmap:** the Gemini adapter; a tokenizer-fetch step in the `dev` Docker image (Stage 7).

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

### Stage 3 follow-up — caching proposal recorded (2026-10-17)

**Recorded:** a proposal, not a decision. [ADR-0016](../adr/0016-curated-cache-and-traffic-source-scope.md), status **proposed**:
- Part 1: a curated shared cache, rebuilt periodically.
- Part 2: cache scope chosen per request from the traffic source.

**Serving defaults are unchanged:** `session` scope and the full key (ADR-0007, ADR-0011).

**Register:**
- A-34 and A-35: the proposal's premises, recorded as **unverified**. The repository's EDA documents don't state them.
- Q-21: accept the proposal? With two sub-decisions: the scope representation (S-b recommended) and reserving the field in Stage 4.
- Data-owner questions Q-22 (is the traffic source identifiable?) and Q-23 (do the categories correspond to traffic types?).
- Hypothesis H-8 added to [context.md §5.2](context.md).

**Carried into later stages:**
- **Stage 8:** the caching plan lists the curated-cache candidate (also noted in `experiments/caching/README.md`): a replay simulation of daily rebuilds (build *d−1*, serve *d*), compared with the session-scoped dynamic cache and no cache, measuring hit rate with hit correctness, storage, and cost saved net of build cost, per traffic source.
- **Stage 9:** the full-EDA checklist includes the popularity distribution per instruction group, within-session vs cross-session repeats, and Q-22/Q-23.
- **Stage 4:** reserve `traffic_source` only if Q-21(b) is answered yes.

**Tensions flagged in the ADR:**
- A shared "instruction group" scope reverses an alternative that ADR-0007 rejected (option S-b avoids this).
- There is no time-sensitivity detector yet (TODO-07).
- The builder needs content for admitted groups, which no online source provides today.
- Serving a selected logged answer to other sessions has privacy implications.

### Stage 3 follow-up — answers to Q-19…Q-21 (2026-10-17)

| Question | Status | Answer |
|---|---|---|
| Q-19 | answered | S3-2 approved: `domain` imports only `contracts`. |
| Q-20 | answered | ADR-0015 confirmed (now decided). The algorithm is chosen in Stage 4; tests use a synthetic key. Still open: who holds and distributes the real key. |
| Q-21 | answered | ADR-0016 is "proposed — to be tested". Scope S-b, only combined with the traffic-source rule; direct users never get `global`. Regenerated answers preferred. Four prerequisites before any serving. Mechanics only on the sample. Reserve `traffic_source` in Stage 4. |

**Changes:**
- `tests/architecture/test_import_rules.py`: `domain` allows only `contracts`, plus a new self-test that `domain → ports` is flagged.
- `src/metis_auto/domain/__init__.py`: docstring.
- [repository_structure.md](../architecture/repository_structure.md) §3.1 diagram and table, §2, §3.4, and §10.
- [ADR-0009](../adr/0009-repository-structure-and-dependency-rules.md): amendment 1.
- [ADR-0010](../adr/0010-request-pipeline-shape.md) consequence updated.
- [ADR-0015](../adr/0015-keyed-content-fingerprints.md) is now decided.
- [ADR-0016](../adr/0016-curated-cache-and-traffic-source-scope.md) records the owner's decisions.
- [overview.md](../architecture/overview.md): S3-2 marked approved, P-7 status, `traffic_source` on `Request`.
- [caching.md](../architecture/caching.md) §6, the register, the docs index, and `experiments/caching/README.md`.

**Tests:** 9/9 pass offline (8 before, plus the new self-test). No `src` module imports `ports` from `domain`; the packages are still empty.

**Carried into Stage 4:**
- an optional `traffic_source` on the request (three states, plus provenance);
- the fingerprint algorithm and the synthetic test key.

**Stage 3 status:** approved (the instruction to continue with Stage 4, 2026-10-17). Stage 4 started 2026-10-17.

---

## Stage 4 — Internal contracts (2026-10-17)

**Outputs:**
- `src/metis_auto/contracts/`: 16 modules defining 86 pydantic models (17 of them event payloads) and 44 enumerations.
  - `_base`: `ContractModel`, privacy classes, `Component[T]` (tri-state), IDs, fingerprints, UTC vs naive time, `Versions`;
  - `privacy`: a static walker over privacy classes;
  - one module per area: request, tokens, accounting, measurement, features, reference data, routing, caching, context, model I/O, attempts, response, events, replay, evaluation.
- [contracts.md](../architecture/contracts.md): conventions, catalogue (purpose, producer, consumers, persistence, privacy, status, traces), versioning, sample tolerance (§4), the reserved `traffic_source` (§5), changes from the Stage 3 vocabulary (§6), arrow coverage (§7), and open items O-1…O-9.
- [contracts_reference.md](../architecture/contracts_reference.md): field tables **generated** from the code by `tests/architecture/contracts_docgen.py`. A test fails if the file is stale.
- [ADR-0017](../adr/0017-contract-modelling-with-pydantic.md): pydantic v2; frozen; extra fields forbidden; a privacy class on every field.
- [ADR-0015 amendment 1](../adr/0015-keyed-content-fingerprints.md#amendment-1-2026-10-17-stage-4-the-algorithm): HMAC-SHA-256 with purpose separation and canonical JSON; `fp1:` + 64 hex; key ID `kid1:`; test vectors computed independently with OpenSSL.
- Tests:
  - `tests/unit/contracts/`: privacy, validation, and serialisation (240 tests);
  - `tests/architecture/test_contracts_reference.py`;
  - `tests/fixtures/synthetic/contract_examples.py`: one synthetic example per contract, every string marked `[SYNTHETIC]`, plus the fingerprint reference implementation;
  - `tests/conftest.py`: `sys.path` until `pyproject.toml` exists (TODO, Stage 5).
- Updated:
  - diagrams: Stage 4 names, and labels added to the high-level view (overview, request_lifecycle, evaluation, deployment_and_data, configuration, context_construction);
  - overview §5 (now points to contracts.md), observability §3/§5, providers §1 (`ModelNoAnswer`), evaluation §3 (`multiple_bots` → `multiple_answers`);
  - repository_structure §3.3 (pydantic) and §4 (tests);
  - architecture README, docs index, requirements (FR-REQ-02, §7 header), GLOSSARY (5 terms), `CLAUDE.md` (contracts pointer);
  - register: A-05 decided; A-36…A-38 new; Q-24 new. Also fixed a pre-existing blank line that cut Q-19…Q-21 off from their table.

**Key decisions:**
- Every optional `Request` component defaults to `unknown` (A-36, Q-24).
- The pipeline mints `request_id`; `Request` has no dataset IDs (A-05).
- `ModelResult` gains `ModelNoAnswer`.
- Sample quirks reach only replay contracts, as optional or tri-state fields and flags (contracts.md §4).
- `traffic_source` is reserved: recorded and stratified, with no serving effect.

**Validation:**
- 250/250 tests pass offline, with warnings as errors: 3 EDA, 7 architecture (import rules unchanged and passing; `contracts` imports nothing internal), 240 contracts. Run with Anaconda Python 3.13.5 and pydantic 2.10.3, since the project venv doesn't exist yet (TODO-08).
- ruff 0.17.1 (in a scratch venv, not the repo): format and `E,F,I,UP,B` pass on all new Python files. Pre-existing files are untouched.
- All 12 Mermaid blocks parse with Mermaid 11.4.1 (Node, jsdom, scratch directory outside the repo), and the checker was shown to reject a broken block.
- All relative links and anchors in changed docs resolve.
- Raw sample data unchanged vs HEAD (sha256 `e0f56a2f…49e1`).

**Open questions raised:** Q-24 (default-unknown components and "empty → absent").

**Carried into later stages:**
- **Stage 5:**
  - port signatures using these contracts;
  - fingerprinting in `application/measurement`, reproducing the test vectors;
  - the request builder follows A-36;
  - the event recorder uses `contracts.privacy`;
  - measure validation overhead (A-38);
  - `pyproject.toml` with `pydantic>=2.10,<3`; remove the `conftest.py` path lines.
- **Stage 6:** the `Settings` contract (O-1), and labels for the configuration diagram.
- **Stage 7:** final catalogue, price, and label-mapping schema (O-3).
- **Stage 8:** judge input (O-6), core feature set (O-5).
- **Stage 9:** sample loader per contracts.md §4.

**Exit criteria:** "Every arrow in the Stage 3 diagrams is labelled with a contract." **Met for every data-flow diagram**, with two documented non-contract flows in the data-flow view (operator logs, derived files) and object injection in the evaluation view. **Not met for the configuration diagram:** its `Settings` arrows wait for Stage 6, which fixes the config format (configuration.md §4). Decision flowcharts label branch conditions; their entry and exit nodes name contracts ([contracts.md §7](../architecture/contracts.md#7-every-arrow-is-labelled-with-a-contract-exit-criterion)).

### Stage 4 follow-up — answers to Q-24; Q-25 added (2026-10-18)

| Question | Status | Answer |
|---|---|---|
| Q-24 | answered | Confirmed. A-36 is decided: components default to `unknown`; producers state `absent`; the future gateway adapter maps omitted wire fields to `absent`. O-4 is decided: an empty or whitespace-only string, or an empty list, is `absent`, never present-with-empty-value. |
| Q-25 | new, open (data owner) | Instructions, model, and provider are null together on 27 bot messages in 2 sessions. Logging gap or something else? Working assumption: a logging gap, so `unknown`. |

**Changes:**
- `contracts/_base.py`: `Component` rejects a present value that is an empty or whitespace-only string or an empty sequence.
- `contracts/request.py`: `RetrievedContext.items` needs at least one item (the same rule one level down).
- `tests/unit/contracts/test_contracts_validation.py`: 6 new tests.
- `contracts_reference.md` regenerated.
- [contracts.md](../architecture/contracts.md): §2.3, the null row in §4, and O-4 in §8.
- Register: A-36 decided, Q-24 answered, Q-25 added.

**Checked:** the Q-25 counts against the sample on 2026-10-18 (counts only): 27 of 442 bot messages have all three fields null, in 2 sessions; the other 415 have all three. Tests: 256/256 pass offline, with warnings as errors. ruff is clean on the changed files.

**Carried into later stages:**
- **Stage 5:** the request builder maps empty values to `absent`.
- **Stage 8:** cache experiments report the measurement-only "unknown as wildcard" key variant alongside the serving variant.
- **Stage 9:** the sample loader maps empty values to `absent`, and the joint instructions/model/provider nulls to `unknown` (`not_in_log`). If the owner's answer to Q-25 says those flows truly had no instructions, that case becomes `absent`.

**Follow-up (2026-10-18), answers to the two questions on the empty rule:**
- An empty mapping is `absent` too. `_is_empty` now covers mappings, so `structured_input` = `{}` is rejected as present.
- `Request.message` stays required. An empty or whitespace-only message needs attachments `present`; otherwise the `Request` validator rejects it (A-39). This is an online-phase rule: the sample has no empty user messages (451 text-only, 14 text plus attachments, counted 2026-10-18).
- 8 new tests. 264/264 pass offline, with warnings as errors. `contracts_reference.md` regenerated; [contracts.md](../architecture/contracts.md) §2.3 and the register updated.

**Stage 4 status:** approved (the instruction to continue with Stage 5, 2026-10-18).

---

## Stage 5 — Skeletons & wiring (2026-10-18)

### TODO-08 resolved first
- Homebrew Python 3.13.16 (`/opt/homebrew/bin/python3.13`, not conda). `.venv` created from it.
- `pyproject.toml`: `src` layout; runtime dependency `pydantic>=2.10,<3`; extras `dev` (pytest, ruff, pip-tools) and `eda` (numpy, pandas, for the frozen sample-EDA tests only); pytest config (warnings as errors, `network` marker); ruff config (`E,F,I,UP,B`, 88 columns; the frozen sample EDA excluded).
- Lockfiles with hashes (pip-tools 7.6.2): `requirements.lock` (runtime: pydantic 2.14.1) and `requirements-dev.lock` (adds pytest 9.1.1, ruff 0.17.1, numpy 2.5.4, pandas 3.0.6). Installed with `--require-hashes`, then `pip install -e . --no-deps`.
- **Full suite in the venv on the committed Stage 4 state: 264/264 pass** (warnings as errors). That also closes O-9: the contract tests pass under the locked pydantic 2.14.1.

### Outputs (four passes: interfaces → skeletons → connect → validate)
1. **Interfaces.** `ports/`: `ModelClient`, `CacheStore`, `VectorIndex`, `Tokenizer`, `Embedder`, `EventSink`, `Judge`, `DataSource`, `Clock`, `IdSource`, `SpendLedger` (`typing.Protocol`, runtime-checkable). Domain swap points: `RoutingPolicy`, `ContextStrategy`, `Detector`.
2. **Skeletons and reference implementations** (sub-packages per S3-1):
   - `domain`: features (sizes, states, instruction group; language and code detection TODO), routing (shared eligibility filter, `fixed_model`), caching (scope, eligibility, key draft, TTL/status validity, store rules; exact tier only), context (`pass_through`, overflow rule; trim TODO), attempts (the ADR-0013 state machine; truncation and empty-output detectors), accounting (token sums, cost from usage and prices, totals, pre-call estimate; "not computed" never zero).
   - `application`: `Fingerprinter` (moved from the test fixtures; reproduces the OpenSSL test vectors), `MeasurementService`, `EventRecorder` (start-up privacy check), `SpendGuard`, `PipelineConfig`, and `RequestPipeline` with one method per lifecycle stage.
   - `adapters`: fake, fault-injecting, quality-injecting, proxy clients; replay and recording clients (skeletons); in-memory cache store and vector index; chars÷4 approximation tokenizer (labelled); fake embedder; in-memory and JSON Lines sinks; fake judge; system and fake clocks; UUID and sequential ID sources; spend ledger.
   - `data_access` (sample loader, synthetic generator, replay-case builder) and `evaluation` (as-logged baseline, metrics, runner): signatures and docstrings only, `NotImplementedError` with the stage that owns them (9 and 8). `evaluation/replay` runs cases through a given pipeline.
3. **Wiring.** `wiring/pipeline.py`: `build_pipeline` and the registries of promoted components (routing policies, context strategies, detectors); refuses a live client without a spending cap. `wiring/walking_skeleton.py`: synthetic placeholder catalogue (three models, two tiers, one failover group), prices with no amounts, demo requests. Entry point: `scripts/run_walking_skeleton.py`.
4. **Validation.** [module_reference.md](../architecture/module_reference.md): every module's responsibility, callers, imports, data in and out, config, kind, and status; the stage-to-method map; swap points. `tests/architecture/test_module_reference.py` checks every module has one row and its cross-package imports match the code.

**Contract changes** (fields were provisional until Stage 5; schema `0.1` → `0.2`):
- `CacheKeyDraft`: the cache policy holds no fingerprint key (ADR-0015), so it returns a draft that the measurement service seals into a `CacheKey`.
- `RequestFeatures.known_input_tokens`: a whole-request estimate for the routing context-fit check; a lower bound when components are unknown.
- `contracts_reference.md` regenerated; contracts.md §2.8, §3.3, §6, §8 updated; `CacheKeyDraft` added to the content-free privacy checks and the synthetic examples.

**Tests:** `tests/conftest.py` lost its `sys.path` lines (editable install) and gained `--run-network`. New: unit tests for application (6), domain (28), adapters (20); integration smoke tests (7): miss → exact hit → ineligible, content-free events, retry then failover with fault injection, escalation on a truncated answer, no eligible model as an error response, live client refused without a cap, replay of a synthetic case to JSON Lines; architecture (3, module reference).

**Other docs:** request_lifecycle sequence (`request_received` after measurement; key draft sealed by CMP-02), overview component interaction (`CacheKeyDraft`), caching §1, configuration §3 rule 7 (the fingerprint key goes to CMP-02), repository_structure §1/§2/§3.4/§4, observability and deployment status lines, ADR-0001 (setup update), ADR-0015 (vectors reproduced), ADR-0017 (version locked, point 7 checked), architecture README, docs index, GLOSSARY (walking skeleton, cache key draft, swap point), `CLAUDE.md` (setup and module reference), `README.md` (setup), `.gitignore` (`*.egg-info/`, `build/`).

### Validation
- **Smoke test passes offline:** `tests/integration/test_walking_skeleton.py`, 7/7, no network, no keys. `scripts/run_walking_skeleton.py` runs and prints content-free metadata.
- **Full suite: 332/332 pass** in the venv, warnings as errors: 3 EDA, 10 architecture, 258 contracts, 6 application, 28 domain, 20 adapters, 7 integration.
- ruff lint and format clean on the whole repository (sample EDA excluded by config). One pre-existing file changed by formatting: a doubled blank line in `tests/architecture/test_import_rules.py`.
- Import rules pass unchanged; the module reference matches the code (mechanical check).
- All 12 Mermaid blocks parse with Mermaid 11.4.1 (Node 24, jsdom, scratch directory outside the repo); a broken block is rejected.
- All relative links and anchors in the changed docs resolve.
- Raw sample data unchanged (sha256 `e0f56a2f…49e1`).
- **Overhead (A-38):** 2,000 walking-skeleton requests with the system clock: pipeline overhead p50 0.07 ms, p95 0.10 ms; whole request with the fake model p95 0.22 ms. Apple M4, CPython 3.13.16. Indicative only (A-22): synthetic requests are tiny. `model_construct` not needed (O-7).

### Drift found and fixed
- The lifecycle sequence showed `request_received` before measurement and the cache policy returning a `CacheKey`; both changed (A-45, `CacheKeyDraft`).
- configuration.md said secrets go only to adapters; the fingerprint key goes to the measurement service (ADR-0015 amendment 1).

### Known gaps (TODO markers in code, owning stage named)
Semantic tier, normalisation treatments, re-route and trim on context overflow, savings per baseline, model-based measurements, language and code detectors (Stage 8); replay and recording clients, runner, metrics, as-logged baseline (Stage 8); data loaders and case builder (Stage 9); `Settings` and config files (Stage 6); exact tokenizers and the price schema (Stage 7).

**Assumptions added:** A-40 (counted usage; errors without usage → "not computed"), A-41 (overflow recorded as an attempt), A-42 (synthetic catalogue in code until Stage 6), A-43 (policy defaults are placeholders), A-44 (random key per script run), A-45 (`request_received` timing). A-38 measured; A-26 note.

**Open questions raised:** Q-26 (cost of failed attempts with no usage), Q-27 (synthetic catalogue in code until Stage 6), Q-28 (EDA extra in the dev lock).

**Carried into later stages:**
- **Stage 6:** `Settings` and the config file format; move the synthetic catalogue and placeholder prices to `config/`; fingerprint key from the environment; config hash into `Versions`; Docker using `requirements.lock`; re-check TODO-09.
- **Stage 7:** exact tokenizers behind `Tokenizer`; the price schema in `domain/accounting/cost.py` (cached input, reasoning, effective dates).
- **Stage 8:** semantic tier; key normalisation treatments; overflow trim and re-route; replay client; runner, metrics, baselines; more detectors; savings; re-measure overhead with realistic sizes.
- **Stage 9:** sample loader, synthetic generator, replay-case builder (skeletons exist with their rules in the docstrings).

**Exit criteria:** "The smoke test passes offline, and the module reference matches the code (verify mechanically where practical)." **Met:** the smoke tests pass offline with fakes and no keys; `test_module_reference.py` verifies that every module is listed and its imports match.

### Stage 5 follow-up — answers to Q-26…Q-28 (2026-10-18)

| Question | Status | Answer |
|---|---|---|
| Q-26 | answered | Keep "not computed" for failed attempts that report no usage (A-40, now decided). Revisit when a live adapter shows what the provider reports on errors. |
| Q-27 | answered | The synthetic catalogue and empty price table stay in code (`wiring/walking_skeleton.py`) until Stage 6 moves them to `config/` (A-42, decided until Stage 6). |
| Q-28 | answered | `requirements-dev.lock` keeps the `eda` extra; `requirements.lock` stays pydantic-only. |

**Changes:** register (Q-26…Q-28 answered; A-40 and A-42 status) and this file. No code changed.

**Stage 5 status:** approved (the instruction to continue with Stage 6, 2026-10-18).

---

## Stage 6 — Configuration, environment, containers (2026-10-18)

### Owner brief brought into the project first
- [live_testing_and_demo_brief.md](live_testing_and_demo_brief.md): byte-identical copy of the owner's brief (sha256 `8e7293a4…7c`), linked from the docs index.
- [metis_pricing_2026-10-18.csv](../references/metis_pricing_2026-10-18.csv): byte-identical copy of the price extract (sha256 `15197ad9…4178`). **Defect found:** its structured columns are wrong for context-tiered models (`gpt-5.4`); the `raw` column is right, and the price file uses it (A-47).
- [metis_wrapper_api.md](../references/metis_wrapper_api.md): endpoints and notes from the saved OpenAI, DeepSeek, Gemini, and overview (Grok) pages, with the save date and canonical URLs. The API-keys page was not opened.
- Decisions recorded: **Q-08 answered** and **Q-12 answered** ([ADR-0018](../adr/0018-live-calls-for-development-under-a-lifetime-budget.md), amending ADR-0003); **Q-05 partly answered** (`gpt-5.4`, never called, for development and the demo); A-13 decided; Stage 7.5 and the Demo milestone added above.

### Outputs
- **Settings** (`src/metis_auto/settings/`, [ADR-0019](../adr/0019-configuration-format-layers-and-secrets.md); closes contracts.md O-1):
  - `model.py`: `Settings` (frozen; `paths`, `logging`, `live`, `budget`, `reference`, `experiment`, `embedding`, `database`, `dev`, opaque `pipeline`), `Secrets` (pydantic secret types), endpoint and baseline tables, `PendingPriceRow`, `ReferenceData`, `LoadedSettings`;
  - `loader.py`: six layers by precedence; layer rules (ceiling only in defaults; no `live`/`budget`/`paths`/`dev` in experiment files; no secret-like keys anywhere; unknown keys rejected); `.env` reader; `METIS__<SECTION>__<KEY>` overrides; secrets; config hash `cfg1:…`;
  - `reference.py`: TOML reference files → `ModelCatalogue`, `PriceTable`, endpoints, baselines; cross-file checks; tiered price rows kept aside.
- **Config files** (`config/`): `defaults.toml`; `reference/catalogue-metis-test.toml` (5 test models + `gpt-5.4` disabled; placeholder tiers and groups, A-48; limits unknown, A-51); `reference/prices-metis-2026-10-18.toml` (with source and check date); `reference/endpoints-metis.toml` (OpenAI, DeepSeek, Grok enabled; Gemini deferred); `reference/baselines.toml`; the synthetic skeleton catalogue and empty prices moved from code (Q-27, A-42 closed); `profiles/walking_skeleton.toml`; `local.example.toml`; README.
- **Spend ledger** (`adapters/system/ledger.py`): `FileSpendLedger`, persistent and cumulative (append-only JSON Lines under `data/spend/`, file lock); `remaining()` = the tighter of lifetime cap (all runs) and per-run cap (this run); warnings at 50 % and 80 %; fails closed on a damaged file. Defaults: lifetime **20 USD** (= the ceiling), per run **1 USD** (A-49).
- **Wiring** (`wiring/from_settings.py`): `pipeline_config` (policy types validate `[pipeline.*]`), `fingerprint_key` (`METIS_FINGERPRINT_KEY` or a random per-process key, A-44), `spend_ledger`, `live_permission` (experiment asks for `live` + `live.enabled` + both caps + `METIS_API_KEY`), `build_pipeline_from_settings`. `build_pipeline` now records the config hash in `Versions` (the Stage 5 TODO). The walking skeleton loads its profile from `config/`.
- **Scripts:** `run_walking_skeleton.py` uses settings (prints the config hash and layers); new `show_budget.py` (spend vs caps and why live calls are blocked; no calls).
- **Environment:** `.env` created with only `METIS_API_KEY=` (empty) and a comment; the owner pastes the key. `.env.example` lists every variable (secrets, locations, live and budget, reference data, pipeline/cache, embeddings, database, experiment, logging, dev flags) with comments and placeholders only. `.gitignore`: `.env.*` (except `.env.example`), `config/local.toml`, `data/spend/`.
- **Docker:** `Dockerfile` (targets `runtime`: `requirements.lock` + package, runs the walking skeleton; `dev`: `requirements-dev.lock` + repo, runs pytest), `.dockerignore` (no `.env`, no gitignored data), `compose.yaml` (service `app`, `.env` optional at run time, `runs/` and `data/spend/` bind-mounted so the ledger is shared; optional `postgres` behind the `db` profile).
- **Docs:** [configuration.md](../architecture/configuration.md) (mechanism, diagram labelled), [local development guide](../guides/local_development.md), ADR-0018, ADR-0019, ADR-0003 amended, contracts.md (O-1, §7), overview (CMP-19/20/26), module_reference (settings section, ledger and wiring rows), repository_structure (§1, §5, §8, §9), deployment_and_data, architecture README, docs index, README, GLOSSARY (5 terms), `CLAUDE.md` (two durable rules: never touch `.env`; live-call budget), register.
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
- **Defect fixed (from Stage 5):** the documented install failed on a fresh venv, because `requirements-dev.lock` did not pin `setuptools` (needed by pip-tools) and `--require-hashes` refused it. The dev lock was recompiled with `--allow-unsafe`, keeping every pin; the only change is hashed pins for `pip` and `setuptools` ([ADR-0001 update](../adr/0001-python-tooling.md)).
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

**Changes:** `Dockerfile` (base image pinned by digest; update instructions), [the guide](../guides/local_development.md) §6 (PATH tip, digest note, verified result), the register (TODO-11 resolved), deployment_and_data.md (status), and this file (status table, roadmap line, this section). The bind mounts created empty, git-ignored `runs/` and `data/spend/` on the host. No code changed.

---

## Stage 7 — Token & cost accounting (2026-10-18)

### Small fix first
- `.gitattributes`: `docs/references/*.csv -text`, so the byte-identical CRLF price extract is stored as-is. Checked: index and working tree both CRLF, sha256 unchanged (`15197ad9…4178`).

### Research (sources and dates in [token_accounting.md §2](../architecture/token_accounting.md#2-tokenizers-supported-models-methods-fidelity); all checked 2026-10-18)
- **OpenAI** (gpt-5-nano, gpt-4.1-nano, gpt-4o-mini, gpt-5.4): tiktoken 0.14.0 maps all four to `o200k_base`; exact local. gpt-5.4 rests on tiktoken's `gpt-5` family mapping; OpenAI's model page names no tokenizer (A-53, Q-31).
- **DeepSeek** (deepseek-v4-flash): the model's own `tokenizer.json` on Hugging Face (MIT, pinned revision); exact local (A-54). Its chat template comes from the repository's `encoding/README.md`.
- **Grok** (grok-4-1-fast): no public tokenizer. Grok-2's is a different model; a tokenize-text endpoint is unverified and not in the wrapper docs. **Labelled chars/4 approximation.**
- **gpt-5.4 long context:** OpenAI's page says ">272K input tokens … 2x input and 1.5x output for the full session"; Metis says "≤ 270K". The conservative reading is chosen (§ below).
- **Reasoning:** OpenAI's reasoning guide confirms hidden reasoning tokens are billed as output and not visible.

### Outputs
- **Contracts** (schema `0.2` → `0.3`): `TokenUsage` (cache writes, TTL variant, template overhead, consistency checks); `Cost` (`price_tier`, `caveats`); `PriceEntry` (context tier fields, uncertain bound, `cache_ttl`; overlap check in `PriceTable`); `TokenType.CACHE_WRITE`; new `ChatTemplate`, `AccountedUsage`, `SavingsDecomposition` (validates the exact sum), `TermValue`, `DecompositionTerm`, `CostCaveat`. `contracts_reference.md` regenerated.
- **Domain** (`domain/accounting/`): `cost.py` rewritten (uncached / cached / cache-write / output prices, tier by input tokens over the whole call, caveats, `provider_cache_discount`, overhead in the pre-call estimate); new `overhead.py`, `baseline.py` (brief §5), `savings.py` (brief §6, plus the explicit `extra_cost` remainder).
- **Application:** new `application/accounting/service.py` (`AccountingService.account`, `.premium_estimate`, `.decompose`); `MeasurementService` gains chat templates, `overhead_for`, and overhead in `counted_usage`; `request_roles`. The pipeline adds framing overhead to counted usage and to the spend guard's estimate.
- **Adapters:** `tiktoken_backend.py`, `hf_backend.py`, `assets.py` (sha256 check; no download ever).
- **Settings and wiring:** `TokenizerTable`, `TokenizerSpec`, `TokenizerAsset`; `paths.tokenizer_assets`; `[reference] tokenizers`; the reader handles tiers and cache-write variants, rejects unknown price keys, and checks every `tokenizer_ref`. Stage 6's `PendingPriceRow` is removed. `wiring/tokenizers.py` builds the backends with a labelled fallback. `build_pipeline_from_settings` injects tokenizers and templates; new `build_accounting_service`.
- **Config:** new `reference/tokenizers.toml`; prices `-s7` (gpt-5.4 tiers; no amount changed); catalogue `-s7` (tokenizer refs; verified `hidden_reasoning_billed_as_output` on gpt-5-nano and gpt-5.4).
- **Dependencies:** extra `tokenizers` (tiktoken 0.14.0, tokenizers 0.23.2), in the dev lock only; existing pins unchanged; `constraints-min-age.txt` keeps new packages ≥ 2 weeks old (ADR-0001 update).
- **Scripts:** `fetch_tokenizer_assets.py` (the one network step; `--check`); `measure_overhead.py` (brief §11); `estimate_sample_tokens.py` (optional item; aggregates only).
- **Reports:** [reports/cost/](../../reports/cost/README.md): overhead runs (7 JSON files) and `sample_token_estimates.json`.
- **Docs:** [token_accounting.md](../architecture/token_accounting.md) (new); [ADR-0020](../adr/0020-token-and-cost-accounting.md); ADR-0001 and ADR-0019 updates; contracts.md, providers.md, configuration.md, overview (CMP-12), module_reference (12 rows), architecture README, docs index, local development guide, README, config README, GLOSSARY (8 terms), `CLAUDE.md` (one pointer and rule), register.
- **Tests (+55 test cases, 4 updated):** `tests/unit/adapters/test_adapters_tokenizers.py` (Persian, English, mixed, code: pinned counts per tokenizer; counts differ by tokenizer; chars/4 off by script; the asset and fallback rules), `tests/unit/domain/test_domain_accounting_stage7.py` (tiers at 270,000 / 270,001 / 276,480 / 276,481; cached input; cache-write variants; caveats; provider-cache discount; templates; pre-call estimate; premium estimate; decomposition miss, hit, unknown, session, invalid sum), `tests/integration/test_accounting.py` (pipeline miss and hit decomposed exactly; the service on the Metis catalogue), settings tests for tiers, cache-write variants, overlap, unknown keys, and tokenizer refs; contract examples and privacy list extended.

### Key results
- **chars/4 is only an approximation, and its error depends on the script** (synthetic texts, pinned): Persian −17 % vs o200k and −35 % vs DeepSeek; code about −30 %; English +6 to +10 %. On the sample's text fields (estimates, ADR-0008): Arabic-script −20 to −29 % (o200k) and −33 to −40 % (DeepSeek); DeepSeek needs 13–21 % more tokens than o200k for Arabic-script text.
- **Overhead (A-38 re-measured):** p95 ≤ 0.17 ms per miss with exact tokenizers on short synthetic requests; with 40,000-char synthetic instructions, 0.96 ms (o200k) and 7.06 ms (DeepSeek). All far inside 100 ms. Counting long instructions dominates ([reports/cost/README.md](../../reports/cost/README.md)).
- **gpt-5.4 is priced** (A-52 resolved): standard tier ≤ 270,000 input tokens, long tier above; 270,001–276,480 flagged.

### Validation
- **Full suite: 447/447 pass** offline in the venv, warnings as errors (392 before + 55). With the tokenizer files moved away: 439 pass, 8 skip, each saying why. With the optional libraries hidden: every exact ref falls back to the labelled approximation.
- ruff check and format clean on the whole repository.
- Import rules pass unchanged (tokenizer libraries only in `adapters/tokenizers`); module reference matches the code.
- No Mermaid diagram changed.
- Raw sample data unchanged (sha256 `e0f56a2f…49e1`); `estimate_sample_tokens.py` only reads it.
- No live call, no `.env` access. Network use: PyPI and Hugging Face metadata, OpenAI, DeepSeek, and xAI documentation pages, and downloads of the two public tokenizer files.

### Decisions and drift
- [ADR-0020](../adr/0020-token-and-cost-accounting.md). Defaults chosen and stated: strict fidelity (framing makes counted inputs `approximation`); 270,000 conservative reading; `extra_cost` term so the decomposition sums exactly; Grok on chars/4 rather than Grok-2's tokenizer; tokenizer files fetched and pinned, not vendored; label mapping moved to Stage 8.
- Drift fixed: configuration.md, providers.md, contracts.md, and ADR-0019 described pending tiered rows and a provisional price schema.

**Assumptions added:** A-53…A-56. A-38 re-measured; A-52 resolved. **Questions:** Q-31. **TODOs:** TODO-12 (Stage 7.5 checks); TODO-02 updated.

**Carried into later stages:**
- **Stage 7.5:** TODO-12, comparing local counts with provider-reported usage (framing, DeepSeek, Grok's error, cached and reasoning reporting, DeepSeek and Grok hidden reasoning); A-55 (message layout) when the adapter is written; then tokenizer and catalogue configuration only.
- **Stage 8:** label mapping and the as-logged baseline; savings per baseline in `ResponseMetadata`; a per-fingerprint token-count cache if realistic sizes need it; structured-input counting.
- **Demo milestone:** show `AccountingService.decompose` per message and `sum_decompositions` per session, with the baseline caveats.
- **Stage 10 roadmap:** a tokenizer-fetch step in the `dev` image.

**Exit criteria:** "Tests pass offline; adding a new model or price requires only configuration or a small adapter." **Met.** 447/447 offline (the tokenizer files are fetched once at setup, like packages; without them the exact tests skip, never download). A model or price is catalogue, price, and tokenizer-table rows (token_accounting.md §4); a new tokenizer format is one adapter plus one enum value.

### Stage 7 follow-up — answer to Q-31 (2026-10-18)

| Question | Status | Answer |
|---|---|---|
| Q-31 | answered | Accepted: tiktoken's `gpt-5` family mapping (`o200k_base`) counts `gpt-5.4` as `exact_local`, with the source recorded (A-53, now decided). The premium cost stays labelled an estimate. |

**Changes:** register (Q-31 answered, A-53 decided), ADR-0020 (status and decision point 1), token_accounting.md (§2 row, §9 open items), docs index (ADR-0020 row), and this file. No code or configuration changed: `config/reference/tokenizers.toml` already applied this default.


---

## Stage 7.5 — Live adapter and wrapper check (2026-10-18)

### Research first (TODO-10; sources and dates in the catalogue, checked 2026-10-18)
- **Limits** for five of six models: gpt-5-nano 400,000 / 128,000; gpt-4.1-nano 1,047,576 / 32,768; gpt-4o-mini 128,000 / 16,384; gpt-5.4 1,050,000 / 128,000 (OpenAI model pages); deepseek-v4-flash 1,000,000 / 384,000 (DeepSeek pricing page, "1M" and "384K" read conservatively).
- **grok-4-1-fast: limits unknown.** xAI's model list no longer has it, its pages return 404, and OpenRouter doesn't list it; third-party aggregators conflict. It is excluded from routing except by an explicit diagnostic switch (Q-32).
- **DeepSeek** serves the legacy `deepseek-v4-flash` with DeepSeek-V4.1-Flash-1017 (released 2026-10-17), thinking on by default. V4.1's tokenizer has the same vocabulary and merges as the pinned V4 file (diffed 2026-10-18; only special tokens differ).

### Outputs
- **Adapter** `adapters/providers/openai_compat.py`: one live `ModelClient` for OpenAI, DeepSeek, and Grok (base URL and generation-limit field per family from `endpoints-metis.toml`); openai SDK 3.24.0 in the new extra `live` (dev lock only; `httpx2`, `jiter`, `sniffio`, `truststore` 0.10.4 held back by the age rule); `max_retries=0` (A-33 verified); A-55 message layout; nine error classes; finish reason; usage with cached and reasoning tokens and the field used; reported model; SDK loggers held at WARNING (their DEBUG output holds request bodies).
- **Recording decorator** implemented (`data/recorded/live-<run>.jsonl`, git-ignored; failures logged, never raised).
- **Spend guard TODO resolved:** an uncomputable actual cost charges the pre-call estimate and stops live calls for the run.
- **Domain knobs:** `[pipeline.context] max_output_tokens_cap` (4,096 in defaults) and the diagnostic `pipeline.routing.eligibility.allow_unknown_context_window` (never in defaults).
- **Wiring:** `wiring/live.py` (`build_live_client`, `live_overrides`), `wiring/chat.py` (`ChatSession`, content-free `TurnReport`), `wiring/wrapper_check.py` (`plan`, `run`); `AccountingService.pre_call_estimate`; `RequestPipeline.live_stopped`.
- **Scripts:** `scripts/chat.py` (live or `--fake`; `/model`, `/models`, `/reset`, `/budget`), `scripts/live_wrapper_check.py` (plan by default; `--run` asks).
- **Config:** catalogue `-s75` (limits; DeepSeek reasoning capability), endpoints `-s75` (`max_tokens_param`), tokenizers `-s75` (DeepSeek V4.1 thinking-mode template; evidence notes), defaults (output cap).
- **Docs:** [ADR-0021](../adr/0021-live-openai-compatible-adapter.md); [live check results](../references/metis_wrapper_live_check.md) and the raw JSON; providers.md §3.1 (mapping table); token_accounting.md; metis_wrapper_api.md; module_reference (6 rows); guide §5.1 (enabling live calls); docs index; ADR-0020 update; `CLAUDE.md` pointer; `config/local.example.toml`; register.
- **Tests (+55 test cases):** adapter over mocked HTTP (`httpx2.MockTransport`: request shape, routes, auth, layout, limit fields, usage variants, finish reasons, 13 HTTP error cases, timeout and connection, one request per call), recording, spend guard, domain knobs, settings and reference, live wiring end to end (ledger, recording, history, stop on uncomputable cost, the check over mocked HTTP), an architecture test (the SDK only in the adapter), and one opt-in `network` test (skipped by default).

### The live wrapper check (owner-approved, 2026-10-18 12:19 UTC)
Five tiny synthetic calls, one per test model. Pre-call upper bound 0.0096 USD; **charged 0.000188 USD** (ledger: 5 charges). Every call succeeded, with finish reason `stop`.
- **OpenAI framing exact** for gpt-4.1-nano and gpt-4o-mini (44 = 44); overcounts gpt-5-nano by 1. gpt-5-nano billed 256 reasoning tokens for a one-word answer.
- **DeepSeek: served as `deepseek-flash`** (V4.1) in thinking mode (30 reasoning tokens billed as output). The V4.1 thinking-mode framing reproduces the reported 65 input tokens exactly; template and capability updated (configuration only).
- **Grok:** accepted and reported as `grok-4-1-fast`; no cached or reasoning fields; 98 reported vs 29 counted input tokens (Q-33).
- Cached-token fields are present (all 0) for OpenAI and DeepSeek; a real cache hit was not exercised (Q-33).

### Validation
- **Full suite: 499 passed, 1 skipped** (the opt-in network test), offline, warnings as errors.
- ruff check and format clean; import rules, the module reference, and the new SDK-import test pass; relative links and anchors in changed docs resolve; raw sample data unchanged (sha256 `e0f56a2f…`).
- `scripts/chat.py --fake` and `scripts/live_wrapper_check.py` (plan) run offline. **`scripts/chat.py` has not been run live**: only over mocked HTTP. The first live chat is yours.
- `.env` was never opened; the key reached only the SDK client, at run time.

### Decisions, assumptions, questions
- Decisions: [ADR-0021](../adr/0021-live-openai-compatible-adapter.md). Defaults chosen and stated: the official SDK rather than plain HTTP; one adapter for all three families; charge the estimate and stop on an uncomputable cost; output cap 4,096; Grok limits left unknown rather than taken from aggregators; the V4 tokenizer file kept for V4.1 (same vocabulary); no provider-specific options sent (DeepSeek thinking left at its default).
- Register: A-33, A-46, A-54, A-55, A-58 decided; A-51 resolved except Grok; A-56 partly verified; A-57 new; TODO-10 resolved except Grok; TODO-12 mostly resolved; **Q-32** (keep, replace, or drop grok-4-1-fast), **Q-33** (a second small probe: Grok overhead and a provider-cache hit), **Q-34** (DeepSeek thinking on or off) new; Q-29 still open (the Metis dashboard limit).

**Carried into later stages:**
- **Stage 8:** replay lookup over `data/recorded/`; per-model generation limits if the cap truncates reasoning models; error mappings checked against real errors when they occur (Q-26).
- **Demo milestone:** `ChatSession` and `TurnReport` are the UI's backend.
- **Stage 10 roadmap:** the Gemini adapter.

**Exit criteria** (brief §12: live adapter, the wrapper check with dated results, `chat.py`): **met.** The adapter is built and tested offline; the check ran once, under budget, and its dated results are in `docs/references/` and the register; `chat.py` works over the real pipeline (fake and mocked-live). The Grok gaps (limits, overhead, reasoning) are recorded as open questions rather than filled in.

### Stage 7.5 follow-up — owner decisions Q-32, Q-33, Q-34 (2026-10-18)

| Item | Status | Answer and what was done |
|---|---|---|
| Q-32 | answered | **mimo-v2.5 replaces grok-4-1-fast** as the fifth test model. Grok stays in the catalogue, **disabled**, with the reason. MiMo: endpoint `https://api.metisai.ir/mimo/v1` (`max_completion_tokens`); prices 0.154 / 0.0031 / 0.308 (pricing page; the Metis MiMo page shows about 10 % less); limits 1,000,000 / 131,072 (model cards; Xiaomi API reference); tokenizer `mimo-v2` **exact_local** (MiMo-V2.5 `tokenizer.json`, MIT, pinned and fetched) and a ChatML template (11 framing tokens for system + user). |
| Q-33 | answered | Probe (b) plus the MiMo tiny check; (a) skipped. `scripts/live_probe.py`: 12 calls, upper bound 0.0085 USD (limit 0.02). **Run 2026-10-18 with the owner's go: 0.001374 USD** (results below). |
| Q-34 | answered | DeepSeek keeps thinking on. New option `[model_options."<model>"] thinking`, allowed by the endpoint file for DeepSeek and MiMo, default unset; the probe tests `disabled` once. |
| Q-29 | open | The owner will check the Metis dashboard. |

**Found during the research (2026-10-18):** Xiaomi auto-routes `mimo-v2.5` to **`mimo-v2.6-flash`** since 2026-10-14 and makes the ID **invalid on 2026-10-21** (A-60, Q-35). The V2.6-Flash tokenizer counts identically (A-59).

**Changes:** config (catalogue, prices, endpoints, tokenizers `-s75`; defaults comment); settings (`ModelRequestOptions`, `ThinkingMode`, `ProviderEndpoint.request_options`); adapter (`request_options` → `extra_body`); `wiring/live.py` (`request_options`); `wiring/wrapper_check.py` (probe; `CHECK_MODELS` now has mimo-v2.5); `scripts/live_probe.py`; tests (+8; 507 pass, 1 skipped); ADR-0021 amendment 1; register; module reference; guide.

**Probe results (2026-10-18 12:46 UTC, [live_check.md §4](../references/metis_wrapper_live_check.md#4-follow-up-probe-2026-10-18-owner-decisions-q-32-q-33-b-q-34)):** 12 of 12 calls succeeded; charged 0.001374 USD; **lifetime total 0.001563 USD of 20**.
- **Provider cache:** hits reported and priced for gpt-4.1-nano and gpt-4o-mini (1,152 cached tokens), deepseek-v4-flash (1,280), and mimo-v2.5 (1,792). Second-call costs dropped 45–95 %. gpt-5-nano did not hit in one pair (best effort). MiMo omits the cached field when nothing is cached. Whether Metis bills the discount: dashboard only (Q-36).
- **mimo-v2.5:** counts exact (47 = 47, 1,807 = 1,807; A-59 decided); hidden reasoning verified (capability added); reported model `mimo-v2.5`, so the V2.6 switch is invisible (A-60).
- **DeepSeek thinking disabled:** works (no reasoning; framing 5 instead of 30 tokens, not yet a template variant). Default unchanged (Q-34).
- **Config from the probe:** catalogue (MiMo reasoning capability), tokenizers (evidence notes). Tests: 507 pass, 1 skipped.
- **Open for the owner:** Q-29 and Q-36 (dashboard limit and charges), Q-35 (mimo-v2.5 ID expiry on 2026-10-21).

### Owner request — teammate quickstart for the Demo milestone (2026-10-18)

- **Recorded** as a required Demo-milestone deliverable: brief §10 and §12 (dated amendment; the brief's sha256 changes from `8e7293a4…` to `5f720a61…`), the planned-steps list above, and the docs index.
- **Drafted now:** [`docs/guides/demo_quickstart.md`](../guides/demo_quickstart.md), sections 1–8 as requested. The demo UI parts are marked *(Demo milestone)*. Every error message in its troubleshooting table was reproduced offline on 2026-10-18 (temporary config files, an empty key variable, mocked HTTP for the budget block; **no live call**), and the fake-mode cache example was run.
- **Linked** from `README.md`, `docs/README.md`, and the local development guide. `config/local.example.toml` stays the in-file reference; it gained a pointer to the guide and a warning against duplicate sections.
- No code changed.


---

## Stage 8 — Experiment framework and first cache baseline (2026-10-18)

### Owner answers recorded first
| Item | Status | Answer and what was done |
|---|---|---|
| Q-29 | answered | The Metis dashboard limit for the key is **10 USD**. `budget.lifetime_cap = "10"` in `config/defaults.toml`; the 20 USD ceiling stays the project maximum. [ADR-0018 amendment 1](../adr/0018-live-calls-for-development-under-a-lifetime-budget.md#amendment-1-2026-10-18-lifetime-cap-10-usd-q-29); guides, `local.example.toml`, README, `CLAUDE.md`, configuration.md, and the loader test updated. |
| Q-36 | open (owner action) | The owner will compare the dashboard charges with the ledger. |
| Q-35 | answered | Keep `mimo-v2.5`; re-check the Metis pricing page after 2026-10-21 and switch then, configuration only (TODO-13). |

### Outputs
1. **Pulled forward from Stage 9** (rules from their docstrings and contracts.md §4; nothing from the EDA helpers):
   - `data_access/sample/loader.py`: `SampleDataSource` (roles, opaque refs injected from the keyed fingerprinter, empty → absent, null → unknown `not_in_log`, a missing key → unknown `key_missing` or absent by option (A-61), attachments → modality, naive times, a retrieved-context plateau detected from the data → `possibly_truncated`).
   - `data_access/replay_cases/builder.py`: the latest-preceding-user pairing, flags, exclusions, no look-ahead, answer-side components from the first answer, `answers_disagree` flags.
   - Contracts (schema 0.3 → 0.4): `PairingFlag.UNANSWERED` (15 trailing unanswered user messages in the sample had no flag) and `LoggedMessage.quality_flags`. `contracts_reference.md` regenerated.
2. **Experiment framework** ([framework.md](../experiments/framework.md), [ADR-0022](../adr/0022-experiment-runner-and-run-tracking.md): own runner rather than MLflow; MLflow 3.17.1 and its file store's "maintenance mode" checked 2026-10-18):
   - `settings`: `ExperimentSettings` (id, kind, source, seed, hypotheses, baselines with `as_logged` required, declared metrics, composition, `[experiment.data]`, `[experiment.strategy]`); EXP-ID regex; the loader refuses `experiment.strategy` outside an experiment file.
   - `evaluation/runner` (`ExperimentRunner`, `RunSetup`; two kinds: `pipeline_replay`, `cache_candidates`), `evaluation/runner/compare.py` (the comparison format), `evaluation/metrics/aggregate.py` (metrics from events, strata, Wilson intervals), `wiring/experiments.py` (candidate loading from `experiments/` only, manifest with git commit and data hash, counterfactual clients), `scripts/run_experiment.py`. `build_pipeline` accepts an injected candidate.
3. **Replay client and label mapping:** `ReplayModelClient.logged` and `.recorded_from` (`data/recorded/`, keyed by model + in-memory digest of the exact input); `config/reference/label-mapping-sample-v1.toml` (exact IDs, two DeepSeek aliases, unmapped reasons) read into `settings.LabelMapping`; `evaluation/baselines/as_logged.py` (as-logged cost and the premium estimate per case).
4. **Exact-cache baseline, EXP-CACHE-001** (`evaluation/cache_candidates`: `CandidateHarness`, `CandidateIndex`, `ExactKeyIndex`, `WildcardIndex`; `domain/caching/normalise.py`): 30 key variants × 2 scopes in one pass, two loader assumptions. Results in `runs/` and, feature-only, [reports/caching/exp-cache-001/](../../reports/caching/exp-cache-001/README.md).
5. **Plans:** [caching_plan.md](../experiments/caching_plan.md), [routing_plan.md](../experiments/routing_plan.md), [context_plan.md](../experiments/context_plan.md).
6. **Overhead re-measured** with the sample's request sizes: `scripts/measure_overhead.py --sizes-from-sample` ([reports/cost/README.md](../../reports/cost/README.md)).

### Key results (sample; provisional signals, ADR-0008)
- **The full serving key yields 0 candidate hits** under both loader assumptions: every repeated message had a different history. Under the conservative loader, no strict variant is even eligible (attachments unknown on every user message).
- Message only: 47 global candidate hits (10.1 %, 95 % CI 7.7–13.2 %), 10 within a session, 37 across sessions; only 4 had an identical logged answer. With instructions: 9 (strict, absent loader). The three normalisation treatments gave identical counts.
- Repeat groups reproduce the EDA's figures independently: 21 groups, 76 messages, 11 crossing sessions.
- As-logged cost 0.1753 USD over the 244 cases whose labels map to priced models; premium estimate 6.40 USD over 434 answered cases (both estimates).
- Overhead with sample sizes: p95 1.37 ms (o200k) and 10.2 ms (DeepSeek), max 57.7 ms. Within 100 ms.

### Validation
- **Full suite: 539 passed, 1 skipped** (the opt-in network test), offline, warnings as errors. New tests: data layer (10), replay client (4), normalisation (4), candidate indexes and variants (5), experiments end to end (7: cache run, routing candidate from a file in two sources plus one comparison table, loading only under `experiments/`, the layer rule, EXP-ID naming and `as_logged`, live refused, logged-match coverage), label mapping (1).
- ruff check and format clean. Import rules unchanged and passing; the module reference matches the code (13 rows added or updated).
- Privacy: events, results, extras, and manifests of the test runs contain no synthetic marker (tested); the committed report files contain no message text (checked for the synthetic marker and Persian script). Run records stay in git-ignored `runs/`.
- Raw sample data unchanged (sha256 `e0f56a2f…49e1`); the loader only reads it.
- No live call; `.env` never opened by me (the settings loader reads it as designed when scripts run, for `METIS_FINGERPRINT_KEY`).

### Decisions, assumptions, questions
- [ADR-0022](../adr/0022-experiment-runner-and-run-tracking.md); ADR-0018 amendment 1. Defaults chosen and stated: a missing sample key is `unknown` by default (contracts.md §4), with the `absent` run reported beside it; the logged model label stands in for the target group in the replay `full` key; "cross-session" is reported as an upper bound (no user reference); the lexical answer-match signal is labelled as not correctness; as-logged costs use today's prices.
- Register: A-04, A-26, A-38 updated; **A-61…A-64** new; **Q-37** (missing-key default), **Q-38** (proposed thresholds in the plans) new; **TODO-13** (MiMo ID).

### Carried into later stages
- **Demo milestone:** rule-based plus sticky routing v1 (the `Turn` producer field, A-64); language and code detectors; LLMLingua-2 as a labelled toggle (context plan X3).
- **Stage 9:** the synthetic generator and full-dataset loader as `experiment.data.dataset` values; event volume (ADR-0022); the onboarding checklist re-runs EXP-CACHE-001 on the full dataset.
- **Later Stage 8-plan items needing the owner:** a judge and labelled pairs (caching C2, routing L1), any live run (estimate first; ADR-0018).

**Exit criteria:** "A new routing or cache strategy can be added by implementing one interface and one config entry, and its results appear in the same comparison format." **Met:** `tests/integration/test_experiments.py` adds a routing policy from a file in an experiment folder (one class implementing `RoutingPolicy`, one `[experiment.strategy]` entry) and runs the built-in cache strategy (`CandidateIndex`), and both runs come out in one `compare.rows` table.

### Stage 8 follow-up — answers to Q-37 and Q-38 (2026-10-19)

| Item | Status | Answer and what was done |
|---|---|---|
| Q-37 | answered | **Missing optional keys (`attachments`, `rag`, `input`) are `absent` by default**, because the export lists them only when present; the `unknown` run stays beside it. Co-occurring nulls (model + provider + instructions) stay `unknown` (`not_in_log`). A-61 decided; new data-owner question **Q-39**, asked with Q-09 and Q-25. |
| Q-38 | answered (provisional) | The plans' thresholds are confirmed as **provisional placeholders**. Change: routing must **also beat as-logged**: ≥ 10 % saving vs as-logged at quality non-inferior to the as-logged answers (within δ), besides the premium criterion. Measured values are reported against every threshold; all revisited with the full dataset. |

**Changes:**
- Code: `missing_key` default `"absent"` in `data_access/sample/loader.py` and `settings.DataSliceSettings`. A new test pins the default and checks that nulls stay `unknown`.
- Config: `experiments/caching/exp-cache-001-exact-baseline/config.toml` (primary `absent`; the alternative via `--set experiment.data.missing_key=unknown`) and its README.
- **EXP-CACHE-001 re-run.** Primary: `exp-cache-001-20261019T054606Z-e8d1f0` (`cfg1:eb7571b5b01f8ed6`). Alternative: `exp-cache-001-20261019T054608Z-8d6712` (`cfg1:449dc7a39553cf47`). The 2026-10-18 report folders were replaced; they were never committed. The counts equal the earlier runs; only which run is primary changed. [Report](../../reports/caching/exp-cache-001/README.md) rewritten with the primary numbers first:
  - full key: 0 candidate hits (404 eligible);
  - `msg_instr` strict: 9 global hits (1.9 %);
  - `msg_only`: 47 (10.1 %).
- Docs: the register (A-61, Q-37, Q-38, Q-39); contracts.md §4 (the missing-key row); framework.md; caching_plan.md C1; routing_plan.md §7 (both baselines); status lines of the three plans; GLOSSARY (retrieved context); module_reference (loader row).
- **Like-for-like ratio checked:** on the same 244 priced cases the premium estimate is 9.0× the as-logged cost (1.58 vs 0.175 USD). The ~36× figure compares different case sets. Now in the report, the routing plan, and Q-38.

**Validation:** 540 passed, 1 skipped, offline; ruff clean; links resolve; sample data unchanged; no live call.


---

## Demo milestone, part A — the backend ("the brain") (2026-10-19)

Owner request of 2026-10-19: Demo A only (no UI; that is Demo B). Decision record: [ADR-0023](../adr/0023-demo-backend-components.md). Every component is a **placeholder demo component** (repository_structure §6.2 steps 2–5, no evidence step); **serving defaults are unchanged** (`fixed_model`, `session` scope, full key, `pass_through`, no compression, providers' default thinking).

### Outputs
1. **Detectors** (`domain/features/detectors.py`, pure, tested on SYNTHETIC Persian, English, and mixed texts): language (fa, en, mixed, other, undetermined), code, length bucket, greeting / small talk (configured Persian + English phrase list). Feature set `fs-0.2.0-demo`; per-turn history features with each answer's producer.
2. **Rule-based routing** (`domain/routing/rule_based.py`): placeholder rules in `[pipeline.routing.rule_based]` → tier → cheapest **effective** cost (expected hidden reasoning billed as output; 0 when thinking is disabled). Nominal price would choose gpt-5-nano; with its reasoning it ranks last in tier 0.
3. **Sticky routing v1** (`domain/routing/sticky.py`), brief §7, modes `sticky_v1` / `per_request` in `[pipeline.routing.sticky]`; stateless reconstruction of the anchor from `Turn.producer`. **A-64 resolved:** `Turn.producer` (tri-state), **contract schema 0.4 → 0.5** (also `TurnFeatures`, `RoutingDecision.anchor_model_id`, `ContextAction.COMPRESSED`, the `context_compressed` event, span `context.compress`, `IneligibleReason.NOT_FIRST_TURN`); `contracts_reference.md` regenerated.
4. **Demo caching:** `scope_rule = "demo_bot_level"` (S-b shape, labelled DEMO) and the **demo seed** (5 first-turn clean sample answers under the message-only `demo_seed_msg_only` key; local only, never sent; off by default; `wiring/demo.py`, `RequestPipeline.seed_demo_entry`).
5. **LLMLingua-2** (EXPERIMENTAL, off by default): `ports.TextCompressor`, `adapters/compressors/llmlingua2.py` (+ labelled fake), `domain/context/compression.py` (history and retrieved only; never instructions by default; never the message), `wiring/compression.py`; extra `compress` with its own lock `requirements-compress.lock`; pinned weights in `config/reference/compressors.toml`, fetched by `scripts/fetch_compressor_assets.py` (2.2 GB, done and verified on this machine). Original LLMLingua not built (ADR-0023 point 7, Q-40).
6. **DeepSeek thinking** per request option: `mode_templates.thinking_disabled` in `tokenizers.toml` (`-2026-10-19-demo`), used per model by wiring; framing 30 → 5 tokens (system + user); routing cost model updated.
7. **`scripts/chat.py` / `wiring/chat.py`:** routing decision and reason, features, cache lookups, served by, model, tokens, cost, premium estimate, full decomposition, compression, overhead, budget, settings; commands `/mode`, `/model`, `/compress on|fake|off`, `/botcache`, `/seed on|off|list`, `/thinking`, `/newuser`, `/instructions`, `/degrade` (offline escalation). Toggles rebuild the pipeline but keep the cache store and the fingerprint key.
8. **Overhead re-measured** ([reports/cost](../../reports/cost/README.md)): detectors p95 0.65 ms; overhead p95 1.9 ms (o200k) / 10.6 ms (DeepSeek) with compression off; **LLMLingua-2 on: p50 0.32 s, p95 3.1 s, max 6.2 s** on CPU; input tokens sent −8.4 % on the sample's sizes (instructions dominate).
9. **Docs:** ADR-0023; routing.md §6 (with a sticky-routing diagram), caching.md §6, context_construction.md §6, contracts.md, token_accounting.md §3.3, module_reference (17 rows), the three plans, live check note, ADR-0016 note, GLOSSARY, CLAUDE.md, README, docs index, local_development guide, `config/local.example.toml`, **demo_quickstart.md** (terminal demo, walkthrough, what Demo B adds).

### Validation
- **Full suite: 636 passed, 3 skipped** (the opt-in network test; the 2 real-LLMLingua-2 tests, which skip without the extra), offline, warnings as errors. New: detectors (45), routing (21), demo cache and compression decisions (7), demo backend end to end over fakes (12: anchoring through producers, escalation raising the anchor, per-request and fixed modes, bot-level cross-user hit with no model call, seed served without a model call and only on first turns, compression accounting and instructions untouched, thinking templates, failed toggle restores settings, producer contract, producer not in the fingerprint, missing sample file), compressor adapters (7), an import test (compression libraries only in their adapter).
- With `requirements-compress.lock` installed (`--require-hashes`; no dev-lock pin changed): **638 passed, 1 skipped**, the real LLMLingua-2 tests included (SYNTHETIC English and Persian texts, ≈ half its tokens kept, about 310 ms each). `chat.py --fake` with `/compress on` and a SYNTHETIC retrieved document: 86 → 42 compressor tokens, 404 ms, a non-zero compression saving. The LLMLingua-2 overhead benchmark ran with the same library versions from a scratch environment while the lock was compiling (pip-compile downloads every torch wheel, 7.6 GB, to hash it).
- ruff clean; import rules and module reference pass; raw sample data unchanged (sha256 `e0f56a2f…49e1`); **no live call**; `.env` never opened by me.

### Decisions, assumptions, questions
- ADR-0023. Register: **A-64 decided**; A-65 (detector placeholders), A-66 (expected reasoning placeholders), A-67 (LLMLingua-2 latency, ZWNJ loss), A-68 (DeepSeek thinking-off layout), A-69 (no attachments in `Turn`), A-70 (greeting in an anchored session); **Q-40** (skip original LLMLingua?), **Q-41** (greeting → cheapest or stay on the anchor?), **Q-42** (mimo-v2.5 after 2026-10-21 in live demos); **TODO-14** (compress lock on Linux).
- Live check of the whole flow: proposed with an upper bound of 0.0021 USD (cap 512); approved and run in the follow-up below.

### Carried into Demo B and later
- **Demo B:** the Streamlit UI over `ChatSession` / `TurnReport`, bot-setup presets (synthetic), cost panel, quickstart §7 completion and the fresh-clone walkthrough.
- **Stage 8 plans:** exp-route-002 / -010 replace the rules and sticky settings with evidence; context X3 ablation (quality, Persian stratum); caching C4/C5 (sticky variants and provider-cache warmth, Q-41).

**Exit criteria (Demo A):** every item of the request is implemented, tested offline with fakes, and usable from the terminal; the overhead benchmark was re-run with LLMLingua-2 on and off and recorded; the quickstart covers the terminal demo and lists Demo B. **Met**, pending review.

### Demo A follow-up — owner answers Q-40, Q-41, Q-42 and the live check (2026-10-19)

| Item | Status | Answer and what was done |
|---|---|---|
| Q-40 | answered | Skip original LLMLingua until a GPU or a small Persian-capable LM is available; documented as a **deferred** arm (context plan X4, ADR-0023 amendment 1). |
| Q-41 | answered | **Greetings in an anchored session stay on the anchor** (`sticky.greeting.stay`); the cheapest model only while unanchored (or if the anchor is ineligible). Done: `domain/routing/sticky.py`, `wiring/chat.py` label, tests (+2 routing cases, the end-to-end test extended), routing.md §6 diagram, routing plan §5, glossary, quickstart walkthrough, ADR-0023 amendment 1; **A-70 decided**. |
| Q-42 | answered | On 2026-10-21 the owner checks the Metis pricing page: switch to the new MiMo ID if listed (configuration only), otherwise `mimo-v2.5` `enabled = false` (routing falls back to the next-cheapest model). Procedure: demo_quickstart.md troubleshooting, "MiMo after 2026-10-21"; TODO-13 updated. |
| Live check | **run** (owner-approved, cap 512) | `scripts/demo_live_check.py` + `wiring/demo_check.py` (plan by default; `--run`). Exact plan first: 9 calls came to 0.002971 USD, above the approval, so two offline-covered steps were dropped → **0.002057 USD for 7 calls**; the run's spend cap was set to 0.0021 USD so the guard enforced it. **Charged 0.000271 USD**; ledger 0.002623 USD of 10. [Results](../references/metis_demo_live_check.md). |

**Live-check findings:** reported input = locally counted input on all 7 calls (framing included, four layouts); **A-68 decided** (DeepSeek thinking-off template verified, also with a history turn: 76 = 76); sticky v1, the anchored greeting, the code re-route, and the bot-level cross-user cache hit behaved as designed on live answers; MiMo billed 14–46 reasoning tokens (placeholder 12, A-66 updated; still cheapest in tier 0) and took 3–13 s per call; LLMLingua-2 on the live path: 86 → 42 tokens in 414 ms. `mimo-v2.5` still accepted on 2026-10-19.

**Changes:** code `domain/routing/sticky.py`, `wiring/chat.py` (`last_trace`, greeting label), new `wiring/demo_check.py`, new `scripts/demo_live_check.py`; config `tokenizers.toml` (`-demo-lc`, evidence only); tests (routing +2, end-to-end extended, mocked-HTTP test of the live check); docs: the live check results (md + JSON), ADR-0023 amendment 1, register, routing.md, routing plan, context plan, glossary, quickstart, docs index, module reference.

### Demo A follow-up — coding intent (2026-10-19)

Owner request: the gap found while testing ("write a python function to add two numbers" has `code no`, so sticky routing stayed on the anchor). ADR-0023 **amendment 2**; register **A-71** (placeholder, A-65 style).

**Changes:**
- **Detector** `detect_coding_intent` in `domain/features/detectors.py` (`CodingIntentConfig`): true when the message has **no code** and either a word template matches ("write ... function", «تابع ... بنویس») or a keyword and a request cue both appear (after removing exclusions such as «کد تخفیف» and "discount code"). The lists are placeholders in `[pipeline.features.coding_intent]` (`config/defaults.toml`), in English and Persian. Feature set `fs-0.3.0-demo`. Cost at most 0.42 ms on a 2,000-character message, 0.003 ms on a short one (configured lists normalised once and cached).
- **Contract schema 0.5 → 0.6:** `RequestFeatures.has_coding_intent`, `TurnFeatures.has_coding_intent`; `contracts_reference.md` regenerated.
- **Rules:** `RuleCondition.has_coding_intent`; placeholder rule `coding_intent` → tier 1 (after `code`).
- **Sticky v1:** a new "very different" reason, `coding_intent_appeared`. It fires only when the intent **appears** against an anchor with neither code nor intent, so a follow-up without it stays.
- **Chat:** the features line shows `coding_intent yes|no`.
- **Tests (+35):**
  - detectors: mechanics, never with code present, empty configuration;
  - 26 SYNTHETIC English, Persian, and mixed cases on the shipped lists, including prose that mentions programming without asking;
  - the stated false positive (a customer's payment error with «چطور»);
  - routing: rule, re-route, follow-up stays, an anchor with code, unknown never satisfies a rule;
  - end to end over fakes: your exact message re-routes to tier 1 and a follow-up stays.
- **Docs:** ADR-0023 amendment 2, register (A-71), routing.md §6 (diagram and text), routing plan §5 and P1, contracts.md §6, module reference, glossary, quickstart (walkthrough step 4, features line), docs index.

**Validation:** 675 passed, 1 skipped (the opt-in network test), offline; ruff clean; no live call.

**Not changed:** a follow-up without the intent stays on the anchor; only appearing counts, by design. Code disappearing still re-routes even when the new message has a coding intent (the rules then send it to tier 1 again).
