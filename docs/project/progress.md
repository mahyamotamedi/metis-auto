# Project Progress

Single source of truth for stage status across sessions. Stage definitions: master prompt §5 ([`metis_claude_code_master_prompt.md`](../../metis_claude_code_master_prompt.md)). Decision records: [`docs/adr/`](../adr/).

| Stage | Title | Status | Exit criteria met? |
|---|---|---|---|
| 0 | Orientation & inventory | done (answers recorded) | Yes |
| 1 | Requirements, quality attributes, scope | done | Yes |
| 2 | Repository structure proposal | done | Yes |
| 3 | Architecture & system design | done (approved by the instruction to continue, 2026-10-17) | Yes |
| 4 | Internal contracts | **awaiting review** (Q-24 answered 2026-10-18) | Yes, except the configuration diagram (`Settings` deferred to Stage 6) |
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
