## Stage 3 — Architecture & system design (2026-10-14)

**Outputs** (index: [architecture/README.md](../../architecture/README.md)):
- [overview.md](../../architecture/overview.md):
  - principles P-1…P-8; the central one is P-1, "measure in `application`, decide in `domain`";
  - the high-level architecture;
  - a component catalogue (CMP-01…26, plus deferred F1…F4), each with home, responsibility, inputs, outputs, dependencies, status, and traces;
  - component interaction;
  - the provisional contract vocabulary for Stage 4;
  - fit with the repository structure.
- Flow documents:
  - [request_lifecycle.md](../../architecture/request_lifecycle.md): lifecycle and data flow, with the privacy boundary;
  - [routing.md](../../architecture/routing.md);
  - [caching.md](../../architecture/caching.md);
  - [context_construction.md](../../architecture/context_construction.md);
  - [attempts.md](../../architecture/attempts.md): escalation, failover, retries, and the detector catalogue;
  - [evaluation.md](../../architecture/evaluation.md);
  - [configuration.md](../../architecture/configuration.md);
  - [observability.md](../../architecture/observability.md);
  - [providers.md](../../architecture/providers.md);
  - [deployment_and_data.md](../../architecture/deployment_and_data.md).
- 11 new Mermaid diagrams. Each states the question it answers, and every arrow carries a provisional contract name or a call.
- Decision records:
  - [ADR-0010](../../adr/0010-request-pipeline-shape.md): pipeline shape;
  - [ADR-0011](../../adr/0011-cache-key-and-lookup-design.md): cache key and lookup;
  - [ADR-0012](../../adr/0012-event-stream-as-measurement-record.md): the event stream as the measurement record;
  - [ADR-0013](../../adr/0013-unified-attempt-model.md): unified attempt model;
  - [ADR-0014](../../adr/0014-counterfactual-answers-via-model-client.md): counterfactual answers via `ModelClient`;
  - [ADR-0015](../../adr/0015-keyed-content-fingerprints.md): keyed fingerprints (provisional).
- Updated:
  - [repository_structure.md](../../architecture/repository_structure.md): sub-package names (S3-1), the ports list, and a note on the pending S3-2;
  - [docs/README.md](../../README.md);
  - [requirements.md](../requirements.md) §7: the "Stage 3 view" column now links to the documents;
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

**Recorded:** a proposal, not a decision. [ADR-0016](../../adr/0016-curated-cache-and-traffic-source-scope.md), status **proposed**:
- Part 1: a curated shared cache, rebuilt periodically.
- Part 2: cache scope chosen per request from the traffic source.

**Serving defaults are unchanged:** `session` scope and the full key (ADR-0007, ADR-0011).

**Register:**
- A-34 and A-35: the proposal's premises, recorded as **unverified**. The repository's EDA documents don't state them.
- Q-21: accept the proposal? With two sub-decisions: the scope representation (S-b recommended) and reserving the field in Stage 4.
- Data-owner questions Q-22 (is the traffic source identifiable?) and Q-23 (do the categories correspond to traffic types?).
- Hypothesis H-8 added to [context.md §5.2](../context.md).

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
- [repository_structure.md](../../architecture/repository_structure.md) §3.1 diagram and table, §2, §3.4, and §10.
- [ADR-0009](../../adr/0009-repository-structure-and-dependency-rules.md): amendment 1.
- [ADR-0010](../../adr/0010-request-pipeline-shape.md) consequence updated.
- [ADR-0015](../../adr/0015-keyed-content-fingerprints.md) is now decided.
- [ADR-0016](../../adr/0016-curated-cache-and-traffic-source-scope.md) records the owner's decisions.
- [overview.md](../../architecture/overview.md): S3-2 marked approved, P-7 status, `traffic_source` on `Request`.
- [caching.md](../../architecture/caching.md) §6, the register, the docs index, and `experiments/caching/README.md`.

**Tests:** 9/9 pass offline (8 before, plus the new self-test). No `src` module imports `ports` from `domain`; the packages are still empty.

**Carried into Stage 4:**
- an optional `traffic_source` on the request (three states, plus provenance);
- the fingerprint algorithm and the synthetic test key.

**Stage 3 status:** approved (the instruction to continue with Stage 4, 2026-10-17). Stage 4 started 2026-10-17.
