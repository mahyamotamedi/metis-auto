# ADR-0046: The small classifier routes simple requests by a pre-generation threshold rule, excludes reasoning-billed candidates, and prices the move per baseline

- Status: **decided** by the project owner, 2026-11-03 (Pipeline C, sprint task R-C3), points 1 to 5. Point 6 (incumbent per baseline) is the agent's reading of point 5, **provisional** until the owner reviews it. The `max_input_tokens` value is **provisional** (tune-only choice, unstable across folds).
- Date: 2026-11-03
- Relates to: [ADR-0045](0045-routing-base-eligibility-and-failover.md) (routing base: eligibility, candidate cost), [ADR-0036](0036-replay-scope-split-and-baselines.md) (split, baselines, units), [ADR-0038](0038-context-token-saving-conversion.md) (implied-rate pricing pattern), [ADR-0041](0041-replay-pricing-for-logged-models.md) (replay prices); FR-ROUTE-01, FR-ROUTE-02, FR-ROUTE-03, FR-ROUTE-04, FR-ROUTE-05, FR-REQ-06, H-5; Q-44, A-66; sprint plan R-C3, "Routing without quality labels", Review Focus 3 and 5.
- Code: `experiments/routing/exp-route-012-small-classifier/version.py`, `scripts/small_classifier_levers.py`. Tests: `tests/unit/experiments/test_exp_route_012_small_classifier.py`.

## Context
No quality labels exist (P-1..P-3 have not run), so a routing version can only simulate cost. The plan gives Pipeline C a threshold classifier on the EDA's transparent rule features ("short, no RAG, no attachments, no tools, no JSON", EDA §4.4), but three of those features describe the logged answer (`a_tool_n_calls`, `a_is_json`, and the EDA also tested `a_input_n_items`), which a router cannot know before generation (FR-REQ-06). Three candidates (gpt-5-nano, deepseek-v4-flash, mimo-v2.5) carry the catalogue capability `hidden_reasoning_billed_as_output`: their list-price cost on logged tokens ignores hidden reasoning, which a live check found far above the routing placeholder on long prompts (Q-44, A-66). The four baselines use two kinds of unit (ADR-0036), and `as_logged` has no list price per row.

## Decision
1. **Two modes in one version** (`SmallClassifier(mode, ...)`, FR-ROUTE-03). `"rules"`: simple = `u_n_chars <= max_u_chars` and `a_rag_n_queries == 0` and `u_att_n == 0` (unknown = not simple) and `bot_n_functions == 0` and effective input `<= max_input_tokens`; `max_u_chars` = 200 from the EDA's rule; `max_input_tokens` chosen on the tune split only by the *least aggressive* criterion (fewest requests moved among grid settings within 1 point of the best `todays_models` saving) and frozen before the report run (16,000). `"logistic"`: numpy logistic regression on the same features, trained only from labels with a declared source (`benchmark:` or `synthetic:`; `None` refuses), never from logged answers or cost; session- and family-grouped nested cross-validation; fewer labels than `min_n` = insufficient. No scikit-learn. Built and tested on synthetic labels only.
2. **Pre-generation features only** (FR-REQ-06): user message length and language, turn, history size, RAG presence, attachments, configured functions, bot instruction size, effective input tokens. Answer length, JSON, finish reason, tool calls, output tokens and cost are refused by code.
3. **Routing** (FR-ROUTE-01, FR-ROUTE-05, ADR-0045): a simple request goes to the cheapest candidate that `routing_base` says is eligible, only if it is another model and strictly cheaper than the incumbent on that request; never upward; everything else keeps its incumbent; fees never change. Every row records target, number of eligible candidates and a reason (FR-ROUTE-02).
4. **Reasoning cost:** candidates with `hidden_reasoning_billed_as_output` in the catalogue are **excluded** from the primary result (`route.small_classifier.rules`), which drives the LeverResults. The secondary result (`route.small_classifier.rules.with_reasoning_models`) includes them and is labelled "lower bound on candidate cost, hidden reasoning not counted". The rule reads the catalogue, so mimo-v2.5 is excluded too (the owner's note named gpt-5-nano and deepseek-v4-flash).
5. **Pricing:** repriced baselines through `routing_base.candidate_costs` and `baselines_full.repriced_row_costs` (tokens assumed model-independent: labelled). `as_logged`: recorded `token_cost` minus the routed model's cost at its implied rates (input, cached and output per 1M, `implied_unit_rates.csv`, recorded units); a routed model without a needed rate makes the saving unknown, never 0; rows not moved save exactly 0. Results are cost simulations, `correctness_state` `unmeasured`, assumption "quality not proven: no labels (P-1..P-3 not run)", with slices all, llm_only, over_8k, traffic_weighted, per bot (ranks), per tenant (ranks, flag above 0.35).
6. **Incumbent per baseline (agent, provisional):** in each baseline the incumbent is that baseline's model for the row (logged model for `todays_models` and `as_logged`, the premium model, the best single cheap model), and the strict "cheaper" test is made in that baseline's units. So `todays_models` moves exactly the rows the version moves (the router's own effect), every baseline's saving is >= 0 row by row, and `as_logged` may move a different set (recorded rates differ from list prices).

## Alternatives considered
- **The EDA's screen as is** (answer-derived tests included): look-ahead into the logged answer (FR-REQ-06). Rejected.
- **One routing decision, priced against every baseline** (R-B3's reading): against `premium_gpt_5_5` the saving then holds the baseline's own difference from today's models, and against `best_single_cheap` it can be negative; the result is no longer the lever's effect in that baseline. Rejected for point 6, which the owner may overturn.
- **Keep reasoning candidates at list price as the main result:** understates their cost on long prompts (Q-44). Kept only as the labelled lower bound.
- **Add an expected-reasoning surcharge** (A-66 placeholders): placeholders, not measurements; would put a guessed number into a saving. Deferred to measured effective cost.
- **scikit-learn:** a new dependency and an ADR for a ten-feature logistic regression. Not needed.
- **Choose `max_input_tokens` by the largest saving:** without labels it always picks the most aggressive setting. Rejected.

## Consequences
- Primary candidates today are gpt-4.1-nano and gpt-4o-mini; on the tune split every primary move goes to gpt-4.1-nano, and against `best_single_cheap` (gpt-5-nano) the primary saving is 0.
- `as_logged` leaves 25,816 tune LLM rows unknown (gpt-4.1-nano has no implied cached rate), and its implied rates rest on few billed items (gpt-4.1-nano 447): provisional.
- The `max_input_tokens` choice depends on the grid ceiling (the saving still rises at 32,000); per-fold choices were 8,000 to 32,000.
- The saving is concentrated (top tenant about three quarters of it on the tune split; that tenant is above the 0.35 request cap): per-tenant and traffic-weighted rows must be shown beside any headline.
- With P-3 labels, the logistic mode trains on them through `nested_cv` and the routing decision rule (within 10 points, lower 95% bound) can be applied; until then no routing result can pass it.
- Overhead (FR-ROUTE-04) is not measured; `overhead_ms_*` stay `None`.
- Guarding tests: `test_labels_only_from_declared_source`, `test_session_grouped_nested_cv`, `test_small_n_insufficient_or_wide_interval`, `test_quality_not_proven_in_assumptions_without_labels`, `test_never_routes_upward`, `test_fee_block_unchanged_by_routing`, `test_uses_routing_base_eligibility`, `test_reasoning_models_excluded_in_primary`, `test_answer_derived_features_refused`, `test_unknown_routed_rate_is_unknown_saving`, `test_least_aggressive_threshold`, `test_write_levers_on_synthetic`.

## Amendment 1 (2026-11-03): strict content rules

- Status: points 1 to 6 **decided** by the project owner, 2026-11-03 (Pipeline C). Point 7 (how history is computed) is the agent's reading, **provisional**.
- Relates to: FR-REQ-06, FR-ROUTE-01..03, H-5; A-78 (rule labels are heuristic), ADR-0028 (labels are never ground truth); K-2/K-3 (Persian word-list review). Code: `version.py` (`turn_flags`, `flags_table`, `intent_columns`, modes `strict` and `strict_unknown_blocked`), `scripts/derive_turn_intent_flags.py`, `scripts/small_classifier_levers.py --strict`.

**Context.** The `rules` mode moves a request on size and features alone. A short coding, math or factual question can be short and still need a stronger model, and a later turn of such a conversation inherits that need. No quality labels exist, so the owner chose a stricter, conservative rule from the existing local labels.

**Decision.**
1. **Derived table:** `scripts/derive_turn_intent_flags.py` reads the raw USER messages in memory only, applies `prompt_labels.primary_category` (with its secondary tags) and the domain code detector to each, and writes only `message_id`, `primary_category`, `blocked_by_category`, `has_code`, `label_state` to git-ignored `data/derived/routing/turn_intent_flags.parquet`. No text is stored or printed. Empty or unreadable text gives `label_state` `unknown`.
2. **Blocked message:** its primary category or any secondary tag is `coding_intent_debugging`, `reasoning_math` or `factual_question`, or the code detector fires.
3. **Sticky history:** a request is not simple if its own user message is blocked or any earlier user message of the same session is blocked. Only earlier turns; never look ahead (FR-REQ-06).
4. **Unknown:** the primary variant does not block `unknown_uncertain` or `label_state` `unknown`; a sensitivity variant blocks them too. A request whose own label is unknown stays on its incumbent in the sensitivity variant.
5. **Everything else is R-C3:** the same frozen thresholds (not re-tuned), routing base eligibility, reasoning-billed candidates excluded, never upward, fees unchanged, the same per-baseline pricing (points 3 to 6). Implemented as two modes of the same version; the `rules` results do not change.
6. **Version ids** `route.small_classifier.strict` and `route.small_classifier.strict_unknown_blocked`; cost simulations, `correctness_state` `unmeasured`, assumptions "quality not proven" and "intent labels heuristic, unreviewed (A-78); Persian word lists pending review (K-2/K-3)".
7. **History computation (agent, provisional):** earlier = strictly earlier by (`turn`, `a_order`) within `session_id` (requests tied on that key never see each other); computed on the whole scoped table before the split and period filter. A request without a user message, or a message without a flags row, has an unknown label. User messages skipped by pairing (`n_skipped_user`) have no request row, so the history rule does not see them (2.5% of tune LLM rows have one).

**Alternatives considered.**
- *Own message only, no history:* misses follow-ups ("and the second one?") of a blocked conversation. Rejected by the owner (point 3).
- *Block `unknown_uncertain` in the primary:* 46% of tune user messages have no rule match; blocking them makes the primary nearly empty. Kept as the sensitivity variant.
- *A copy of the version for the strict rule:* two copies of the routing and pricing code drift. Rejected (point 5).
- *Recompute flags inside the replay from raw text:* would read raw text in every replay. Rejected: one local derived table without text.

**Consequences.**
- Tune split (LLM rows, `todays_models`, primary candidates): moved share 0.388 → 0.108 (`strict`) → 0.034 (`strict_unknown_blocked`); saving share 0.272 → 0.069 [0.048, 0.097] → 0.011 [0.009, 0.013]. History alone makes 0.314 of LLM rows not simple.
- Most blocks come from `factual_question` (0.266 of user messages as primary), whose rule matches a trailing question mark and common question words: the strict result depends on unreviewed word lists (A-78, K-2/K-3).
- The flags table must be derived locally before `--strict`; it holds no text and is git-ignored.
- Guarding tests: `test_coding_message_blocks_routing`, `test_math_and_factual_block_routing`, `test_code_detector_blocks_routing`, `test_blocked_earlier_turn_blocks_later_turns`, `test_later_blocked_turn_does_not_affect_earlier_turns`, `test_unknown_not_blocked_in_primary_blocked_in_sensitivity`, `test_rules_mode_results_unchanged`, `test_flags_table_has_no_text_column`, `test_write_strict_levers_on_synthetic`, `test_strict_checks_on_synthetic`.
