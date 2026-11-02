## Stage 4 — Internal contracts (2026-10-17)

**Outputs:**
- `src/metis_auto/contracts/`: 16 modules defining 86 pydantic models (17 of them event payloads) and 44 enumerations.
  - `_base`: `ContractModel`, privacy classes, `Component[T]` (tri-state), IDs, fingerprints, UTC vs naive time, `Versions`;
  - `privacy`: a static walker over privacy classes;
  - one module per area: request, tokens, accounting, measurement, features, reference data, routing, caching, context, model I/O, attempts, response, events, replay, evaluation.
- [contracts.md](../../architecture/contracts.md): conventions, catalogue (purpose, producer, consumers, persistence, privacy, status, traces), versioning, sample tolerance (§4), the reserved `traffic_source` (§5), changes from the Stage 3 vocabulary (§6), arrow coverage (§7), and open items O-1…O-9.
- [contracts_reference.md](../../architecture/contracts_reference.md): field tables **generated** from the code by `tests/architecture/contracts_docgen.py`. A test fails if the file is stale.
- [ADR-0017](../../adr/0017-contract-modelling-with-pydantic.md): pydantic v2; frozen; extra fields forbidden; a privacy class on every field.
- [ADR-0015 amendment 1](../../adr/0015-keyed-content-fingerprints.md#amendment-1-2026-10-17-stage-4-the-algorithm): HMAC-SHA-256 with purpose separation and canonical JSON; `fp1:` + 64 hex; key ID `kid1:`; test vectors computed independently with OpenSSL.
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

**Exit criteria:** "Every arrow in the Stage 3 diagrams is labelled with a contract." **Met for every data-flow diagram**, with two documented non-contract flows in the data-flow view (operator logs, derived files) and object injection in the evaluation view. **Not met for the configuration diagram:** its `Settings` arrows wait for Stage 6, which fixes the config format (configuration.md §4). Decision flowcharts label branch conditions; their entry and exit nodes name contracts ([contracts.md §7](../../architecture/contracts.md#7-every-arrow-is-labelled-with-a-contract-exit-criterion)).

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
- [contracts.md](../../architecture/contracts.md): §2.3, the null row in §4, and O-4 in §8.
- Register: A-36 decided, Q-24 answered, Q-25 added.

**Checked:** the Q-25 counts against the sample on 2026-10-18 (counts only): 27 of 442 bot messages have all three fields null, in 2 sessions; the other 415 have all three. Tests: 256/256 pass offline, with warnings as errors. ruff is clean on the changed files.

**Carried into later stages:**
- **Stage 5:** the request builder maps empty values to `absent`.
- **Stage 8:** cache experiments report the measurement-only "unknown as wildcard" key variant alongside the serving variant.
- **Stage 9:** the sample loader maps empty values to `absent`, and the joint instructions/model/provider nulls to `unknown` (`not_in_log`). If the owner's answer to Q-25 says those flows truly had no instructions, that case becomes `absent`.

**Follow-up (2026-10-18), answers to the two questions on the empty rule:**
- An empty mapping is `absent` too. `_is_empty` now covers mappings, so `structured_input` = `{}` is rejected as present.
- `Request.message` stays required. An empty or whitespace-only message needs attachments `present`; otherwise the `Request` validator rejects it (A-39). This is an online-phase rule: the sample has no empty user messages (451 text-only, 14 text plus attachments, counted 2026-10-18).
- 8 new tests. 264/264 pass offline, with warnings as errors. `contracts_reference.md` regenerated; [contracts.md](../../architecture/contracts.md) §2.3 and the register updated.

**Stage 4 status:** approved (the instruction to continue with Stage 5, 2026-10-18).
