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
| 7 | Token & cost accounting utility (+ brief §12 items) | **awaiting review** (2026-10-18) | **Yes** (see below) |
| 7.5 | Live adapter and wrapper check (**new**, small; [brief](live_testing_and_demo_brief.md) §12) | planned | — |
| 8 | Experiment framework & exact-cache baseline | not started | — |
| Demo | Demo milestone (**new**, after Stage 8; brief §12) | planned | — |
| 9 | Data layer plan | not started | — |
| 10 | Architecture review & roadmap | not started | — |

**Planned steps added 2026-10-18 from the [owner's brief](live_testing_and_demo_brief.md) §12** (not started; scope as the brief states it):
- **Stage 7 additions:** ~~tokenizers for the six catalogue models; price schema with cached input, cache writes, and context-length tiers; the premium-baseline estimate (brief §5); `scripts/measure_overhead.py` (brief §11)~~ **done in Stage 7**, plus the savings decomposition (brief §6) as pure functions, ahead of the Demo milestone.
- **Stage 7.5 (new, small):** one live OpenAI-compatible adapter (base URL per family; SDK auto-retries off; normalised errors; provider-reported usage, finish reason, cached tokens, and model); the tiny live wrapper check (brief §3), results recorded with dates; a `scripts/chat.py` CLI. Prerequisites: TODO-10 (context windows), the spend-guard TODO for uncomputable actual costs, Q-29.
- **Stage 8 additions:** the sample loader, pairing heuristic, and replay-case builder pulled forward from Stage 9; the sticky-routing experiment plan (brief §7).
- **Demo milestone (after Stage 8):** rule-based plus sticky routing v1; the LLMLingua-2 strategy as a labelled experimental toggle (heavy dependencies in an optional extra); demo cache scope and seed; showing the savings decomposition (computed since Stage 7, `AccountingService.decompose`); a Streamlit UI as a thin wrapper over `wiring` (brief §10).
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

