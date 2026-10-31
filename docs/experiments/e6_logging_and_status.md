# E6: logging fields, the report, and where the evaluation framework stands

Status: **provisional** (Stage E6, 2026-10-30). Spec: [evaluation_framework.md](evaluation_framework.md) (§7 logging, §9 next steps). Stage notes: [E2](e2_scenario_config.md), [E4](e4_sampling_run.md), [E5](e5_judging.md). **Nothing here has been run on real data: none exists in this checkout. No live call was made. No scenario, cache, gate or budget value is configured.**

## 1. Logging fields: spec §7 against the contracts

Fields were added only where a field was missing, all optional (default `None`), operational privacy class, no content. The contract reference was regenerated (`python tests/architecture/contracts_docgen.py`). **Adding a field populates nothing**: the live adapter and the pipeline do not yet fill the new ones.

| Spec §7 field | Where it lives | Status |
|---|---|---|
| request, session, case, attempt IDs; UTC timestamp; span durations; versions in force | `Event` envelope | present |
| component state, size, fingerprint; language, lengths, feature flags | `RequestReceived.components`, `RequestFeatures` | present |
| caller or app id (hashed) | `RequestReceived.traffic_source` | **reserved (Q-21)**: a data-owner decision |
| routing: policy and version, eligible set, exclusions, reason code | `RoutingDecision` | present |
| chosen **effort** | `ModelInvocation.effort`, `AttemptRecord.effort` | **added in E6** (not yet applied by the live adapter) |
| cache lookup: tier, outcome, similarity, threshold, variant, scope, invalid or ineligible reason | `CacheLookupResult` | present |
| cache key schema version, matched entry age | `CacheLookupResult.key_schema_version`, `.entry_age_ms` | **added in E6** (not yet filled) |
| cache "verified result" | none | **open**: needs a verification step in the cache design first |
| provider, model, returned model version, finish reason | `AttemptRecord`, `ModelResponse.provider_model_version` | present |
| tokens: input, output, reasoning, cached, cache write | `TokenUsage` | present |
| truncated flag | derivable from `finish_reason == length` | present (derived) |
| total latency | `ModelResponse.provider_latency_ms`, `AttemptRecord.duration_ms` | present |
| **time to first token** | `ModelResponse.time_to_first_token_ms`, `AttemptRecord.time_to_first_token_ms` | **added in E6** (no adapter measures it yet; needs streaming) |
| time in queue | none | **open**: not observable through the provider API in general |
| retries, failures, fallbacks, escalations | `AttemptRecord`, `RetryScheduled`, `FailoverTriggered`, `EscalationTriggered` | present |
| cost, price table version, token fidelity | `Cost` | present |
| overhead cost (router, embedder, judge as detector) | spans and `Cost` basis | present |
| judge score (async) | `JudgeScore`, `EvaluationScored` | present |
| user quality signals (thumbs, regenerate, edit, rephrase) | none | **open**: the product must offer them first (data owner, Q-04/Q-06/Q-09) |

For the **full dataset** the data owner must still supply (framework §7): token counts and costs if known, latency, request IDs for pairing, retry and fallback labels, any quality or satisfaction field, timezone and clock source.

## 2. The comparison report

`evaluation/reporting` assembles E1 to E5 into one feature-only report (`build_comparison_report`, `to_plain`, `to_markdown`; the caller writes `reports/<area>/<id>/report.json` and `report.md`). It has the header (price table version, its age and max-age status, counterfactual source, provenance, judge), paired **effects** versus the reference (quality difference and cost ratio with intervals, the δ non-inferiority flag, Persian first, other languages separate, `all` labelled "dominated_by_persian"), a **descriptive per-model table**, **coverage** (the plan, allocation and weighting side by side, quotas, run and judge exclusions), the **scenario sensitivity** table, **open items**, and caveats. A slice below the configured minimum n, or any slice with the minimum unset, shows no value, only the reason. Quality in a slice whose judge gate has not passed is marked `unvalidated` and cannot reach the non-inferiority flag. It is tested end to end with fake clients and a fake judge; no real report exists.

## 3. Spec §9 next steps: done or open

| §9 item | Status | Why |
|---|---|---|
| 1. Decide δ (Q-13), the judge, calibrate against human ratings | **open** | owner decisions; no ratings exist; the plumbing is built (E5) |
| 2. Persian tokenizer comparison offline | **done** | E3 and `reports/cost/`; provisional (sample) |
| 3. Owner approval and budget for the pilot | **open** | needs your approval and the Metis cap (Q-29); not requested here |
| 4. Scenario output and a price-table age check | **done as modules** (E2, E6 report) | not wired into `scripts/run_experiment.py`; that integration was not requested |
| 5. Logging fields in the contracts | **done in part** (§1) | added what was missing and observable; four items stay open for stated reasons |
| 6. Re-verify every *[verify]* item | **open** | not re-checked: AIQ definition, RouteLLM's APGR grid, provider cache terms, `gpt-5.5` price and limits, current leaderboard figures |
| 7. Unresolved methodological decisions | **open** | minimum n, quotas and floor, classifier thresholds, gate statistic and threshold, calibration size, length-bucket boundaries and unit, match-key choices, judge model, δ, Persian-capable embedder, whether normalisation may enter the production cache key (own ADR) |

## 4. Not done in E6

`BaselineSpec` is still not wired to `config/reference/baselines.toml`, and `EvaluationResult` was not changed (the report is its own structure; mapping it into `EvaluationResult` metrics is open). No new EXP-ID was created, so the experiment plans are unchanged. No dashboard.
