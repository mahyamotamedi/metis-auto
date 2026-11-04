# ADR-0064: The decision router enters the full-data comparison in its rules-only mode, with R-C3's per-baseline accounting

- Status: **provisional** (sprint task J-3 remapped, 2026-11-03). Cost simulation; quality not proven.
- Date: 2026-11-03
- Relates to: [ADR-0047](0047-system-one-decision-router.md) points 4 and 12 and its owner results (A-118, A-121, A-125), [ADR-0045](0045-routing-base-eligibility-and-failover.md), [ADR-0046](0046-small-classifier-routing.md) points 4 to 6, [ADR-0051](0051-per-bot-reassignment.md); FR-ROUTE-01, FR-ROUTE-03, FR-REQ-06, H-5; Rule zero of the sprint-final task (no hosted call, no spend).
- Code: `experiments/routing/exp-route-013-decision-router/rules_only.py`, `version.py` (`route_target`, `route_target_cost`), `scripts/decision_router_levers.py`.

## Context
THX-01 runs in 4 to 12 s on the owner's CPU, so it cannot be replayed on about 300,000 requests; Jev is a hosted, paid call and may not see dataset text (Q-53, Q-55). On the 150-record dev slice THX-01 changed no decision (agreement 1.0, A-121) and Jev scored 72% on 100 synthetic requests (A-125), which is not evidence on real traffic. The inline mode, by the owner's rule, is rules only.

## Decision
1. **The full-data result is the router with `router.mode = "off"`.** The tier is the real domain policy's `decide_tier` with no decision result: gate (greeting, code, coding intent, attachment, long message), then the rule-based fallback, then the safe tier. The script refuses unless the router is off, no dataset text is approved for hosted use, unpriced router calls are off and live calls are disabled, and loads settings without `.env`. No backend module is imported (tested).
2. **Flags from a local, in-memory pass.** `has_code`, `has_coding_intent` and `is_greeting` are computed from the raw user text by the configured detectors and stored, without text, in a git-ignored table. A missing or blank text gives no tier (the incumbent stays).
3. **Tier to model:** the decided tier's cheapest candidate that the routing base allows (primary set, reasoning-billed models excluded); a move needs a strictly cheaper target in the baseline's units; never upward. Accounting per baseline reuses R-C3's `baseline_frames` unchanged (ADR-0046 points 5 and 6).
4. **Labels in every result:** quality not proven; rules-only; THX-01 changed no decision on the dev slice; Jev's 72% is not evidence on real traffic. Results: `route.decision_router.rules_only.<baseline>` (report split, one run) and `.tune.<baseline>`.

## Consequences
- The safe tier (1) takes about 96% of requests and its only primary candidate is `gpt-4o-mini`, so the saving is mostly a move to that model. It says nothing about its quality.
- Catalogue tiers are placeholders (A-48), so the result is as good as the tier map.
- Guarding tests: `tests/unit/experiments/test_exp_route_013_rules_only.py` (`test_gate_and_rules_give_the_documented_tiers`, `test_no_router_backend_is_needed_or_called`, `test_hosted_router_must_be_off`, `test_tiers_match_the_domain_policy_for_every_distinct_row`), `tests/unit/experiments/test_decision_router_levers.py` (`test_never_routes_upward_and_fees_unchanged`, `test_no_text_id_or_hash_reaches_the_files`, `test_tune_and_report_results_do_not_overwrite_each_other`), `tests/unit/experiments/test_exp_route_013_decision_router.py`.
