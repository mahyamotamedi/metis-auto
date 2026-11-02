# EXP-CACHE-002: popular-question cache (nightly curated set)

- **Hypothesis:** H-8 (a curated first-turn cache captures a useful share of requests; EDA §5, `docs/full_eda/full_eda_report.md`). Final plan task R-A1.
- **Design basis:** [ADR-0016](../../../docs/adr/0016-curated-cache-and-traffic-source-scope.md) Part 1 (**proposed, to be tested**; no serving change). Hits are candidate hits ([ADR-0006](../../../docs/adr/0006-evaluation-metric-definitions.md) point 2); scope is measured, not decided ([ADR-0007](../../../docs/adr/0007-cache-sharing-scope.md)); key components follow [ADR-0011](../../../docs/adr/0011-cache-key-and-lookup-design.md).
- **Traceability:** H-8, X1 (hit correctness, `docs/full_eda/experiment_plan.md`), FR-XCACHE-02 (key), FR-XCACHE-04 (validity), FR-XCACHE-05 (scope), ADR-0006, ADR-0007, ADR-0016, [ADR-0034](../../../docs/adr/0034-cache-guard-key-encoding-and-check-order.md) (guard key encoding), ADR-0031 (full-data replay path), ADR-0032 (result format), TODO-07, Q-06.
- **Evidence class:** *simulation* on logged requests. `correctness_state` is `unmeasured` until the K-1 review.
- **Code:** [`version.py`](version.py), class `PopularQuestionCache(window_days, min_count, min_sessions, variant)`, a `levers.StepVersion` of step `cache`. It is loaded only through `wiring.experiments.load_candidate` (scripts and tests); `metis_auto` never imports it. Tests: `tests/unit/experiments/test_popular_question.py` (all frames [SYNTHETIC]).
- **Status (2026-11-02):** phase 1 of 3, synthetic tests only. No real-data run yet: phase 2 waits for B's `CacheGuard` and C's scope step.

## Design

| Element | Rule | State |
|---|---|---|
| Key | `bot_id` + `bot_ins_h_exact` + `u_h_norm`. `u_h_norm` is `fingerprint(normalize_safe(text))` (`analysis/ingest.py`, checked 2026-11-02). | decided |
| Instruction part | `bot_ins_h_exact` is a hash of the **bot snapshot**, one value per bot, so it never splits a bot's traffic; it is there for ADR-0011 conformance and is a no-op on this data. A per-period instruction history does not exist in the export. | provisional |
| Nightly set | For each naive day *d* of `u_timestamp`: keys with ≥ `min_count` eligible occurrences in ≥ `min_sessions` distinct sessions on days *d − window_days … d − 1*. No look-ahead, no same-day admission. `1 ≤ window_days ≤ 180`. | decided |
| Parameters | Arguments, not read from `sprint.toml`; the plan's values are 90, 3, 2 and are passed by the caller. | decided |
| Guard key | ADR-0034: a guarded key is `"<key_version>\|<body>"`, built with `analysis.cache_guard.versioned_key`, and the guard refuses any other key (`key_version`). **Gap (phase 2):** `keys()` builds the body only, with no version prefix, so B's guard would refuse every key. Needs a `key_version` source, for example a constructor argument (owner's call). | open |
| Hit | Eligible, key in day *d*'s set, and `ctx.guard.allows(key, bot)` when a guard is given. | decided |
| Shadow check | Plan S-5: every cache version reports the shadow-check result. `CacheGuard.shadow_sample(keys, rate, seed)` has no default rate; the caller passes the rate from `sprint.toml` (Q-B9). The sample is per key, so the rate is a share of distinct keys. | open (phase 2) |
| Stored answer | Mode of `a_h_norm` over the window's occurrences; ties go to the latest `a_timestamp`, then the smallest hash. | provisional |
| Agreement | `pq_answer_agrees`: the hit's own logged answer hash equals the stored one. A diagnostic, never a correctness claim (ADR-0016, `logged_match`). | decided |
| Effect | Copy with the same index; hit rows get `served_from_cache = True` and zero known `block_fees` and `block_token_cost` (unknown stays unknown). Added columns: `pq_eligible`, `pq_admitted_keys_day` (count), `pq_answer_agrees`. No key, hash or text in the output. | decided |

### Variants (same code, `variant=` argument)

- **`first_turn` (headline):** `lever_id = cache.popular_question.first_turn`. Only requests with no logged history may be admitted or hit (ADR-0016 Part 1 point 3). In `requests`, `n_prior_msgs` at an AI row counts every earlier USER/AI message **including the request's own question** (`history_columns`, checked on a synthetic session), so "no history" is `n_prior_msgs == 1` (decided by the owner, 2026-11-02; the EDA's H-8 figures use `turn == 0`, which also counts sessions with two user messages before the first answer).
- **`all_turns` (upper bound):** `lever_id = cache.popular_question.all_turns`. Any turn, history ignored. Labelled "upper bound, unsafe for follow-up questions" in its assumptions.

### Eligibility funnel (`funnel(req)`, a count per step)

The EDA exact-cache steps, in the EDA's order (`reports/full_eda/tables/exact_cache_funnel.csv`): `has_user_text`, `answer_text_and_STOP`, `no_attachments`, `no_tools`, `no_actions`, `timestamps_valid`. Then:

- `key_known`: `bot_id`, `u_h_norm` and `a_h_norm` present;
- `llm_request`: workflow rows out (`combine` already skips them);
- `no_memory`: `bot_memory_enabled` is False; True **and unknown** are out (ADR-0011 point 2, unknown never matches);
- `no_rag`: `a_rag_n_queries == 0` with `a_rag_state` in `null`/`empty`/`ok`; a request that ran retrieval, or whose RAG field is malformed, is out (EDA §5: unsafe without a state-aware key);
- `first_turn` (headline variant only).

## Assumptions

- *Current:* hits are **candidate** hits. Cost saved is the **recorded cost of avoided calls**, before lookup overhead and before the build cost (regeneration or judging) that ADR-0016 says must be charged. Units are the unstated recorded units.
- *Current:* every bot has one owner account, and the EDA shows bot+text `global` equal to `same_user_id` (`exact_cache_variants.csv`), so real end-user identity is unknown and **cross-user reuse is not measured**. ADR-0016 allows `global` scope only for `embedded_bot` traffic with instructions present, and inferred traffic labels are analysis-only, so this result is **measured potential, not a serving decision**.
- *Current:* no time-sensitivity detector exists (TODO-07); time-dependent questions can be admitted.
- *Current:* days are naive calendar days (Q-06).
- *Current:* the instruction key part is a snapshot; instruction changes over time are invisible.
- *Future:* serving a selected logged answer to other sessions needs a privacy review first (ADR-0016 decision 4); regenerated answers are preferred.
- *Speculative:* the answer mode is a reasonable stand-in for a curated answer.

## EDA reference numbers (comparison targets)

From `reports/full_eda/tables/exact_cache_variants.csv` (dynamic cold-cache replay, all months, 326,491 eligible requests):

| Variant | Candidate hits / eligible | 95% CI |
|---|---|---|
| bot+text, global | 27.97% | 27.4% to 28.5% |
| bot+full_history, global | 8.28% | 8.0% to 8.5% |

**Why this version should come out lower:** it is a nightly set with frequency limits (≥ 3 occurrences in ≥ 2 sessions in the previous 90 days), not a dynamic cache that can hit on the second occurrence; nothing asked today is served today; memory and RAG requests are out; the headline variant keeps first turns only; and the result is read on the report period (August to October 2026) only.

## Phases

1. **(this)** tests and implementation on [SYNTHETIC] frames; guard and scope replaced by stand-ins in tests.
2. Real-data run after the 18:00 merge, with B's guard (versioned keys, shadow-check result) and C's scope; write the local K-1 review sheet (30 items, uncommitted).
3. Read the reviewed sheet; `correctness_state` becomes `sampled:<n>`.
