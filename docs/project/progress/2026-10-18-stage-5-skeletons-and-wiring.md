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
4. **Validation.** [module_reference.md](../../architecture/module_reference.md): every module's responsibility, callers, imports, data in and out, config, kind, and status; the stage-to-method map; swap points. `tests/architecture/test_module_reference.py` checks every module has one row and its cross-package imports match the code.

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
