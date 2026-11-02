## Stage 8 — Experiment framework and first cache baseline (2026-10-18)

### Owner answers recorded first
| Item | Status | Answer and what was done |
|---|---|---|
| Q-29 | answered | The Metis dashboard limit for the key is **10 USD**. `budget.lifetime_cap = "10"` in `config/defaults.toml`; the 20 USD ceiling stays the project maximum. [ADR-0018 amendment 1](../../adr/0018-live-calls-for-development-under-a-lifetime-budget.md#amendment-1-2026-10-18-lifetime-cap-10-usd-q-29); guides, `local.example.toml`, README, `CLAUDE.md`, configuration.md, and the loader test updated. |
| Q-36 | open (owner action) | The owner will compare the dashboard charges with the ledger. |
| Q-35 | answered | Keep `mimo-v2.5`; re-check the Metis pricing page after 2026-10-21 and switch then, configuration only (TODO-13). |

### Outputs
1. **Pulled forward from Stage 9** (rules from their docstrings and contracts.md §4; nothing from the EDA helpers):
   - `data_access/sample/loader.py`: `SampleDataSource` (roles, opaque refs injected from the keyed fingerprinter, empty → absent, null → unknown `not_in_log`, a missing key → unknown `key_missing` or absent by option (A-61), attachments → modality, naive times, a retrieved-context plateau detected from the data → `possibly_truncated`).
   - `data_access/replay_cases/builder.py`: the latest-preceding-user pairing, flags, exclusions, no look-ahead, answer-side components from the first answer, `answers_disagree` flags.
   - Contracts (schema 0.3 → 0.4): `PairingFlag.UNANSWERED` (15 trailing unanswered user messages in the sample had no flag) and `LoggedMessage.quality_flags`. `contracts_reference.md` regenerated.
2. **Experiment framework** ([framework.md](../../experiments/framework.md), [ADR-0022](../../adr/0022-experiment-runner-and-run-tracking.md): own runner rather than MLflow; MLflow 3.17.1 and its file store's "maintenance mode" checked 2026-10-18):
   - `settings`: `ExperimentSettings` (id, kind, source, seed, hypotheses, baselines with `as_logged` required, declared metrics, composition, `[experiment.data]`, `[experiment.strategy]`); EXP-ID regex; the loader refuses `experiment.strategy` outside an experiment file.
   - `evaluation/runner` (`ExperimentRunner`, `RunSetup`; two kinds: `pipeline_replay`, `cache_candidates`), `evaluation/runner/compare.py` (the comparison format), `evaluation/metrics/aggregate.py` (metrics from events, strata, Wilson intervals), `wiring/experiments.py` (candidate loading from `experiments/` only, manifest with git commit and data hash, counterfactual clients), `scripts/run_experiment.py`. `build_pipeline` accepts an injected candidate.
3. **Replay client and label mapping:** `ReplayModelClient.logged` and `.recorded_from` (`data/recorded/`, keyed by model + in-memory digest of the exact input); `config/reference/label-mapping-sample-v1.toml` (exact IDs, two DeepSeek aliases, unmapped reasons) read into `settings.LabelMapping`; `evaluation/baselines/as_logged.py` (as-logged cost and the premium estimate per case).
4. **Exact-cache baseline, EXP-CACHE-001** (`evaluation/cache_candidates`: `CandidateHarness`, `CandidateIndex`, `ExactKeyIndex`, `WildcardIndex`; `domain/caching/normalise.py`): 30 key variants × 2 scopes in one pass, two loader assumptions. Results in `runs/` and, feature-only, [reports/caching/exp-cache-001/](../../../reports/caching/exp-cache-001/README.md).
5. **Plans:** [caching_plan.md](../../experiments/caching_plan.md), [routing_plan.md](../../experiments/routing_plan.md), [context_plan.md](../../experiments/context_plan.md).
6. **Overhead re-measured** with the sample's request sizes: `scripts/measure_overhead.py --sizes-from-sample` ([reports/cost/README.md](../../../reports/cost/README.md)).

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
- [ADR-0022](../../adr/0022-experiment-runner-and-run-tracking.md); ADR-0018 amendment 1. Defaults chosen and stated: a missing sample key is `unknown` by default (contracts.md §4), with the `absent` run reported beside it; the logged model label stands in for the target group in the replay `full` key; "cross-session" is reported as an upper bound (no user reference); the lexical answer-match signal is labelled as not correctness; as-logged costs use today's prices.
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
- **EXP-CACHE-001 re-run.** Primary: `exp-cache-001-20261019T054606Z-e8d1f0` (`cfg1:eb7571b5b01f8ed6`). Alternative: `exp-cache-001-20261019T054608Z-8d6712` (`cfg1:449dc7a39553cf47`). The 2026-10-18 report folders were replaced; they were never committed. The counts equal the earlier runs; only which run is primary changed. [Report](../../../reports/caching/exp-cache-001/README.md) rewritten with the primary numbers first:
  - full key: 0 candidate hits (404 eligible);
  - `msg_instr` strict: 9 global hits (1.9 %);
  - `msg_only`: 47 (10.1 %).
- Docs: the register (A-61, Q-37, Q-38, Q-39); contracts.md §4 (the missing-key row); framework.md; caching_plan.md C1; routing_plan.md §7 (both baselines); status lines of the three plans; GLOSSARY (retrieved context); module_reference (loader row).
- **Like-for-like ratio checked:** on the same 244 priced cases the premium estimate is 9.0× the as-logged cost (1.58 vs 0.175 USD). The ~36× figure compares different case sets. Now in the report, the routing plan, and Q-38.

**Validation:** 540 passed, 1 skipped, offline; ruff clean; links resolve; sample data unchanged; no live call.
