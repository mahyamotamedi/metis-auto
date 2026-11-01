# ADR-0028: The 300-request evaluation dataset golden-v1

- Status: structure **decided**; quotas and rules **provisional** (`config/evaluation/golden_v1.toml`, status proposed); the dataset itself is **`annotated_provisional`** until human review completes.
- Date: 2026-11-01
- Relates to: ADR-0006, ADR-0008, ADR-0013, ADR-0014, ADR-0022, ADR-0025, ADR-0027; [session_config_report.md §8](../full_eda/session_config_report.md); [evaluation framework §4](../experiments/evaluation_framework.md)

## Context
The EDA proposed 300 candidates (`golden-candidate-0.1`), never approved, with rule labels that leave 44.4% of requests unknown. Routing experiments need a set with separate facets, explicit availability of each input, and no answer leakage. This set is a balanced challenge set: **no aggregate on it equals production performance**, and its labels are not ground truth.

## Decision
1. **Unit:** one target USER message with a clean-paired AI answer, plus earlier context in the session. Eligible: `pair_flag = clean`, non-empty target and answer, `finish_reason = STOP`, non-null timestamps. Exclusions are counted by reason.
2. **Inputs are components with an availability stage:** `request_arrival`, `configuration_snapshot` (may postdate the request), `retrieval_order_unknown`. Two views, `routing_input_pre_retrieval_v1` and `routing_input_post_retrieval_v1`, because whether retrieval precedes routing is unknown. Earlier AI turns' chunks are stored but in neither profile, because resending is unknown.
3. **The reference is separate** (`eval.record_reference`): answer, model and provider labels (`reference_model_source = bot_config_snapshot`, since the served model per message is unknown), billing. The views also refuse the answer message by id, so a bad component cannot leak it (tested).
4. **Facets stay separate:** primary intent; secondary labels; complexity; length; position; bot class; language; cohort.
5. **Selection:** an exact primary-intent × cohort table from the existing `joint_quotas`; inside each cell a greedy pass toward the other margins and coverage minimums, then same-cell swaps; one record per session; one per exact or near-duplicate family; a per-bot cap; ranked reserves.
6. **Complexity is human-only.** Selection uses a rule *proxy* to oversample likely hard requests, reported as `complexity_proxy`. No rule writes a `complexity` label.
7. **Annotation:** rules propose, humans decide, at least 20% double-annotated. `llm_assisted` is recognised and refused without recorded owner approval. It was not used.
8. **Team reproducibility:** selection never depends on platform, locale, hash randomisation or row order. A content-free fingerprint is committed. Labels travel as an ID-and-label file.

## Decisions the design left open, made here
- **Cohort cap.** The design caps a cohort at 66 and gives "Remaining accounts" a quota of 75. The cap protects against one account dominating, and that cohort pools 127 accounts, so it applies to single-account cohorts only. Configurable.
- **`short_uncertain` language.** 11.9% of requests have too few letters to classify and the language quotas have no such group. For quota purposes they follow their dominant script (`language_groups` in config). The original label is kept on `eval.request`.
- **Near-duplicate family.** The EDA's measure was estimated word-bigram Jaccard ≥ 0.8 over sampled first turns. Here: an order-insensitive token family over the whole pool, plus exact bigram Jaccard ≥ 0.8 across the selected records and reserves, reselecting until none remain.
- **Family hashes.** ADR-0025 point 4 keys duplicate-group IDs. These are plain blake2b analysis hashes because a shared key would have to travel between teammates. They stay in the local database, are never exported, and selection depends only on the grouping, not the values. This is a narrow, deliberate exception to ADR-0025.
- **`pure_greeting`** is a coverage target, because a floor alone was missed (3 of 10 in the first build).
- **Quotas on proxies.** Rule labels stand in for reviewed labels at selection. `plan-swaps` lists records whose reviewed intent leaves their cell with a reserve to replace them. Swapping happens after review, at most three rounds.

## Alternatives considered
- **Round robin inside cells (the EDA's method).** Simple, but cannot steer several overlapping margins. Replaced by deficit-weighted greedy with swaps, still seeded.
- **Cartesian stratification.** Too many empty cells. Rejected.
- **LLM labelling now.** Conflicts with the no-live-calls rule and the licence without approval. Rejected.
- **Overwriting the EDA proposal.** Kept as a baseline; overlap is reported (V-09).

## Consequences
- The set cannot test caching by itself: it holds no deliberate duplicate pairs.
- Rule labels may be wrong, so quotas are met on rules only until review. Reviewed counts may differ.
- A change to the config changes the fingerprint, by design.
- Open: reviewers; agreement thresholds (unset, report only); what happens to the old proposal once this is validated.
