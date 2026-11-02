## Research note — evaluation framework (2026-10-30)

Proposal, provisional: [`docs/experiments/evaluation_framework.md`](../../experiments/evaluation_framework.md) (baselines, cost/output-token estimation, shared sampling run, latency, replay, statistics, logging fields, pitfalls). One-pass literature search; items marked *[verify]* need re-checking. No stage status changed; nothing committed. Needs owner approval before any live sampling (ADR-0018, Q-29).

### Stage E0 — Persian-aware text handling for evaluation (2026-10-30)

Implemented ([ADR-0025](../../adr/0025-persian-folding-treatments-and-evaluation-groups.md), [evaluation framework §0](../../experiments/evaluation_framework.md), prompt in [evaluation_implementation_prompt.md](../../experiments/evaluation_implementation_prompt.md)); **awaiting review**, nothing committed. No production routing or caching behavior changed; serving stays `literal`.
- `domain/caching/normalise.py`: versioned `PERSIAN_TREATMENTS` (`persian_fold_v1`, `..._zwnj_space_v1`, `..._marks_v1`), opt-in by name in the cache-candidate harness; `TREATMENTS` and its test unchanged. Harness edited minimally (`SHORT` map, accepted names).
- New `evaluation/grouping` (keyed `dup_group` fingerprints, leakage-safe splits) and `evaluation/lengths` (bucket-versus-token report).
- Characterization tests of `detect_language` and `length_bucket` (no code change); module_reference rows, caching_plan C1b note, `evaluation/__init__` docstring.
- Windows baseline: failures in `test_domain_detectors.py`, `test_domain_routing_demo.py`, three `tests/architecture` tests and collection errors for ledger-importing tests are platform issues that predate E0 (`fcntl`, POSIX paths); not fixed.
- Open (not decided here): ZWNJ/diacritic/tatweel policy for serving, Latin case folding, code points versus graphemes, A-43 language thresholds, judge and later-stage decisions.

### Stage E1 — Baselines and comparison metrics (2026-10-30)

Implemented in `src/metis_auto/evaluation/comparison/` (pure, offline, no live calls); **awaiting review**, nothing committed. Spec: [evaluation framework §1, §0.1, §6](../../experiments/evaluation_framework.md).
- Baselines as request → model assignments: fixed model (premium, cheapest), as-logged (unmapped left out, coverage reported), oracle (best quality with a noise margin, or cheapest within δ of a reference; refuses unvalidated quality), random-mix expected value; `BaselineSpec`.
- Metrics: Pareto front, quality at matched cost, cost at matched quality, CPT, PGR/APGR (near-zero-gap guard), oracle headroom, paired effects and non-inferiority with a seeded session-cluster bootstrap, Holm step-down, Persian-primary language slicing, claim-gated ranking.
- Every threshold (`min_n`, `min_gap`, δ, noise margin, bootstrap size, level, seed) is an argument; unset gives `not_evaluated` or `insufficient` with a reason. Every number carries provenance.
- Not done: wiring baselines and these metrics into config, the runner, or `EvaluationResult` contracts (no contract changes); the AIQ metric; RouteLLM's exact APGR grid is *[verify]*.
- Windows baseline failures unchanged (33 failed, 3 collection errors, all pre-existing platform issues).

### Stage E2 — Cost scenarios, price age, output-token estimators; premium switch to gpt-5.5 (2026-10-30)

Implemented in `src/metis_auto/evaluation/costing/`; **awaiting review**, nothing committed. No live calls; serving, routing and caching unchanged. Details and the config field table: [e2_scenario_config.md](../../experiments/e2_scenario_config.md); decision: [ADR-0026](../../adr/0026-premium-baseline-gpt-5-5.md).
- **Premium switch (owner, 2026-10-30):** `gpt-5.5` is the premium baseline; new price file `prices-metis-2026-10-18-g55.toml` (the old one is untouched), catalogue entry (disabled, limits unknown), tokenizer note, tests and demo UI labels updated. The Windows-blocked `tests/integration/test_settings_wiring.py` pin was edited but could not be run here.
- **E2 code:** `ScenarioConfig` (nothing defaulted; unset → `not_evaluated` with a reason), scenario engine over `cost_of`, input-only cost, cost line, break-even, cost quantiles with the arithmetic floor, price-table age with consequences, estimators A/B/C and a paired comparison. Standard-library only; no new dependency.
- **Not set anywhere:** reasoning-length scenarios, cache scenarios, `max_age_days`. Price table age: 12 days on 2026-10-30 (checked 2026-10-18), `effective_from` unknown.
- Not done: nothing fitted on data (none exists here); `BaselineSpec` is still not wired to `baselines.toml`; E2 does not touch the runner.

### Stage E3 — Full-prompt input cost tooling (2026-10-30)

Implemented in `src/metis_auto/evaluation/inputs/`, `scripts/input_cost_report.py`, `tests/unit/evaluation/test_evaluation_price_tiers.py`, `test_evaluation_inputs.py`; **awaiting review**, nothing committed. No live calls; serving, routing and caching unchanged; no schema or contract changes. Output: `reports/cost/input_cost_full_prompt-2026-10-30.json` (aggregates only) and a section in `reports/cost/README.md`.
- Per-case, per-model component token counts with each tokenizer (reusing `MeasurementService`), Persian-first slices, input-only uncached cost lower bounds through the E2 engine and price table, long-tier case counts, exact-versus-chars/4 ranking flips (Grok excluded as approximation), instruction-reuse counts, bucket-versus-token reports, and the compression break-even cached fraction (needs no hit rate).
- Long-tier review: tier is chosen by input tokens and prices input, cached input and output together; boundaries 270,000 / 270,001 / 276,480 / 276,481 tested for `gpt-5.5` and `gpt-5.4`. Open: whether the provider's "context" includes output tokens, and the 270,000 versus 276,480 reading.
- Still unset: reasoning-length and cache scenarios, `max_age_days`, `min_n`. Cached-cost scenarios are not computed.

### Stage E4 — Shared sampling-run harness, fakes only (2026-10-30)

Implemented in `src/metis_auto/evaluation/sampling/`, `scripts/sampling_plan.py`; **awaiting review**, nothing committed. **No run was made, no live call, no key use**; serving, routing and caching unchanged; no contract or schema changes. Details: [e4_sampling_run.md](../../experiments/e4_sampling_run.md).
- Sampler (floor, language quota, proportional remainder with exact tie-breaking, pooling, seeded selection; weights stored apart from allocation; unmet quotas and budget overrun reported), call plan, run estimates (lower bound, assumed, ceiling), live guard (approval, sample-conversation approval, cap), per-call worst-case cap check, optional stop rules, content-free call records, E1/E2 tables and the Persian-first comparison.
- Edited existing code: `evaluation/inputs/composition.py` gained an `attachments` stratum. (An earlier `record_sources` option on `RecordingModelClient` was removed by the closing-audit fixes below.)
- Fix found in testing: apportionment ties used float remainders; now exact fractions.
- Not done / open: time to first token and the effort setting are not in the `ModelClient` port (TTFT recorded as not reported; effort carried by a per-(model, effort) client factory); every config value is unset; the pilot budget and approval are not given; quality scores come from E5.

### Stage E5 — Quality judging plumbing, pluggable judge (2026-10-30)

Implemented in `src/metis_auto/evaluation/judging/`; **awaiting review**, nothing committed. No judge model chosen, no live call, no human ratings; no contract or schema changes. Details: [e5_judging.md](../../experiments/e5_judging.md).
- Pairwise judging with both orderings, tie option, swap consistency, relative scores, stated exclusions for image turns and missing answers, judge cost as evaluation cost; calibration export and rating import; agreement (accuracy or kappa, config); position, swap and verbosity diagnostics; the Persian gate with per-language `quality_validated` tables; instruction-language comparison with no winner; re-simulation design stub; image-call exclusion for the E4 run plan.
- Existing code edited: `evaluation/sampling/runner.py` (`partition_image_calls`).
- Every gate and calibration value is unset: all scores are `unvalidated` until someone configures them and supplies ratings.

### Stage E6 — Reporting, logging fields, docs (2026-10-30)

Implemented in `src/metis_auto/evaluation/reporting/`, optional contract fields, docs and a guide; **awaiting review**, nothing committed. No live call; serving, routing and caching unchanged. Details: [e6_logging_and_status.md](../../experiments/e6_logging_and_status.md); guide: [offline_evaluation.md](../../guides/offline_evaluation.md).
- Report: header (price table version and age, source, provenance, judge), paired effects versus the reference per language slice (Persian first; values withheld below the minimum n; unvalidated quality flagged and blocked from the delta flag), descriptive per-model table, coverage with allocation and weighting apart, scenario table, open items. Tested end to end with fake clients and a fake judge.
- Contracts (all optional, operational, no content; reference regenerated): `ModelInvocation.effort`, `ModelResponse.time_to_first_token_ms`, `AttemptRecord.effort` and `.time_to_first_token_ms`, `CacheLookupResult.key_schema_version` and `.entry_age_ms`. Nothing populates them yet; the E4 harness reads effort and time to first token through them.
- Still open: queue time, cache verification result, user quality signals, caller or app id (Q-21); spec section 9 mapped in the E6 doc.
- Not done: `BaselineSpec` wiring, `EvaluationResult` mapping, any real run.

### E0–E6 closing-audit fixes (2026-10-30)

Three fixes from the audit; nothing committed. (1) **Provenance:** `RecordingModelClient` is back to live-only (identical to HEAD apart from a new `client_source` marker on each written record); `ReplayModelClient.recorded_from` now skips any record not made live and counts it (`skipped_non_live`), so fake or simulated answers can never be replayed as `recorded` and read as `measured`; regression tests added. (2) **Sample-conversation approval:** `execute(...)` no longer defaults `uses_sample_conversations`; it must be passed as `True` or `False`, anything else raises `TypeError` before any call; every call site now passes it explicitly; tests added. (3) **Contract wording:** the four optional E6 fields (`AttemptRecord.effort`, `.time_to_first_token_ms`, `CacheLookupResult.key_schema_version`, `.entry_age_ms`) now say that no production code populates them; reference regenerated. Not changed: the `state` value naming, any E1 API, the Windows fixes, the two E501 lines.


### Merge-review fixes (2026-10-31)

Applied after the pre-merge review of `evaluation-framework-e0-e6`; nothing committed. (1) **Lint:** the two Windows-commit architecture tests reformatted (`ruff check` and `ruff format --check` clean). (2) **ADR index:** ADR-0025 and ADR-0026 rows in `docs/README.md`. (3) **Register:** A-74…A-77, Q-45, TODO-15 (open `gpt-5.5` items); Q-05 marked superseded. (4) **Stale premium references:** demo quickstart, `token_accounting.md` examples and `config/README.md` now say `gpt-5.5`; the brief keeps its historical text with a superseded note. (5) **Nits:** `tiktoken_backend.py` docstring lists gpt-5.5; the grouping test strings are tagged `[SYNTHETIC]`. Not changed: the gpt-4.1-nano 404 and the mimo-v2.5 retirement (TODO-13), which this branch does not touch.
