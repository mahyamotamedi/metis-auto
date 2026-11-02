## Sprint Day 3, Pipeline C: small classifier, strict content rules (2026-11-03)

Branch `route-small-classifier-strict` (from `main` at 70338d0, #33: R-C3). **Awaiting review.** `git fetch`: `origin/main` head is 70338d0. Traceability: FR-REQ-06, FR-ROUTE-01..03, H-5, A-78, ADR-0028, ADR-0046 and its [Amendment 1](../../adr/0046-small-classifier-routing.md). Experiment: [EXP-ROUTE-012](../../../experiments/routing/exp-route-012-small-classifier/README.md).

- **Owner decisions (2026-11-03), Amendment 1 points 1 to 6:** a local flags table from the raw USER messages (text in memory only; `message_id`, `primary_category`, `blocked_by_category`, `has_code`, `label_state`; git-ignored); a message is blocked by a coding, math or factual label (primary or secondary) or detected code; sticky history (own or any earlier user message of the session, never later); unknown labels not blocked in `route.small_classifier.strict`, blocked in `route.small_classifier.strict_unknown_blocked`; everything else exactly R-C3 (frozen thresholds not re-tuned).
- **Agent's reading, provisional (point 7):** earlier = strictly earlier by (`turn`, `a_order`), ties never see each other; history computed on the whole scoped table before the split filter; no user message or no flags row = unknown label; pairing-skipped user messages are not seen (2.5% of tune LLM rows have one).
- **New:** `scripts/derive_turn_intent_flags.py`, `reports/routing/exp-route-012/strict_tune_checks.json`. **Changed:** `experiments/routing/exp-route-012-small-classifier/{version.py,README.md}` (modes `strict`, `strict_unknown_blocked`; `turn_flags`, `flags_table`, `intent_columns`), `scripts/small_classifier_levers.py` (`--strict`, `--flags`, `strict_checks`), `tests/unit/experiments/test_exp_route_012_small_classifier.py` (+10 tests, synthetic), `docs/adr/0046-small-classifier-routing.md` (Amendment 1), `experiments/routing/README.md`, `docs/project/progress.md` (index). No `src` change; `prompt_labels.py` and `detectors.py` unchanged.
- **TDD:** the 9 requested tests (and the writer test) were written first; 9 failed (`flags_table`, `intent_columns` missing). The `rules` digests in `test_rules_mode_results_unchanged` were recorded from the unchanged R-C3 code before any change, and still match.
- **Local derived table:** 355,965 user messages, ~18 s; `label_state` unknown 0; blocked 100,618 (category 99,926, code 1,437).

### Results (tune split, LLM rows; aggregates; cost simulation, quality not proven, labels heuristic)

209,331 LLM rows, 208,055 user messages. Primary categories: unknown_uncertain 0.461, factual_question 0.266, conversational_support 0.089, others below 0.05 (coding 0.016, math 0.018). Blocked messages 0.356 (category 0.355, code 0.0036). History only: 0.314 of LLM rows not simple (0.407 of rules-simple rows).

| Version | moved share | `todays_models` saving share [95%] | top tenant share |
|---|---|---|---|
| `rules` (R-C3) | 0.388 | 0.272 [0.204, 0.341] | 0.764 |
| `strict` | 0.108 | 0.069 [0.048, 0.097] | 0.664 |
| `strict_unknown_blocked` | 0.034 | 0.011 [0.009, 0.013] | 0.417 |

Writer dry run on tune (scratch, not kept): 8 results; `strict` `as_logged` 0.049 (5,645 unknown), premium 0.083, best single cheap 0.

### Open
- The strict result rests on unreviewed word lists: `factual_question` alone is 0.266 of user messages (trailing `?` and common question words). K-2/K-3 review and A-78.
- Owner review of point 7 (history ordering and unknown handling of missing user messages).
- Report-split LeverResults not written: the owner runs `scripts/small_classifier_levers.py --strict` after committing, on a clean tree.
