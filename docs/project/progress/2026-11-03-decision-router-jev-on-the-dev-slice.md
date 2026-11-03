## Decision router: Jev on the 150 real dev-slice records (2026-11-03)

Branch `route-jev-dev-slice` (from `main` at ee8c353). **Awaiting review.** Owner decision after Metis's written OK (Q-55). Traceability: FR-ROUTE-01..05, H-1, QA-PRIV, QA-COST, ADR-0047, ADR-0018, ADR-0041.

- **Built:** Jev as a hosted backend of the shadow evaluation (`--backend jev`): plan first with no call, `router.real_data_approved` and live only for that run, spend guard and ledger, run cap 0.05 USD; a cost view of the same logged tokens on today's, the rules' and Jev's model (`evaluation/router_eval/costs.py`); gpt-4.1-nano and mimo-v2.5 disabled in memory; per-request skip reasons, a skip breakdown, a net-of-Jev-cost view and a content-free differences CSV (`reports/routing/dev_slice_v1/jev_vs_rules_differences.csv`).
- **Run 1 (owner's machine):** 124 Jev calls, 0.00448 USD, all `jev-1.14.0`. Saving over today's models 57.7% / 57.4%, **of which the rules alone give 56.7%; Jev adds about 2%** (2.35% / 1.87%; tune 0.6%, check 6.7%). 16 of 142 differ, all toward tier 0. Net of Jev's own calls: +0.3% / −0.2%.
- **Plain statement:** a cost simulation on logged tokens; **quality is unproven; the saving over the rules is not significant on this sample.** Serving unchanged.
- **Skips:** 26 = 18 gate fast rules + 8 where the rules found no eligible model (the same 8 are unpriced). The reason for the 8 was not recorded in run 1; run 2 records it.
- **Decisions and assumptions:** Q-55 read conservatively (Jev through Metis only; chat-model APIs, gate 2, still closed). Tokens assumed model-independent. Tier 0 is gpt-5-nano only (A-123). Registered as A-126.
- **Tests:** 2172 passed / 38 skipped here (the two tokenizer-asset tests that fail on `main` in this workspace were deselected). New: `tests/integration/test_router_jev_slice.py` (4), `tests/unit/evaluation/test_router_eval_costs.py` (5).
- **Open:** run 2 for the differences CSV and skip reasons (about 0.0045 USD); L3 labels for the 150 requests or the paid benchmark; a bootstrap interval for the 2%; TODO-17 (the team disables the two gone models in the catalogue).
