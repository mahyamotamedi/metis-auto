## Sprint Day 3, Pipeline C: small classifier routing, threshold rule and logistic mode (2026-11-03)

Sprint task R-C3, branch `route-small-classifier` (from `main` at 355d5f2, #32). **Awaiting review.** `git fetch`: nothing newer on `origin/main`; R-A3 (Pipeline A) is not on `main`. Traceability: FR-ROUTE-01..05, FR-REQ-06, H-5, X7 (routing benchmark, docs/full_eda/experiment_plan.md; this is its no-label cost part), routing plan R1/R2, Review Focus 3 and 5, ADR-0036, ADR-0038, ADR-0041, ADR-0045, ADR-XXXX (small-classifier-routing) ([draft](../../adr/draft-small-classifier-routing.md)). Experiment: [EXP-ROUTE-012](../../../experiments/routing/exp-route-012-small-classifier/README.md).

- **Owner decisions (2026-11-03), ADR draft points 1 to 5:** two modes in one version (`rules` for the real-data run; `logistic`, numpy, trained only on declared labels, synthetic only for now); pre-generation features only; cheapest eligible candidate, strictly cheaper, never upward, fees unchanged; candidates with `hidden_reasoning_billed_as_output` excluded from the primary result, included in a labelled lower-bound secondary; `as_logged` priced at the routed model's implied rates (missing rate = unknown).
- **Agent's reading, provisional (ADR draft point 6):** the incumbent is each baseline's own model for the row, and the strict "cheaper" test is made in that baseline's units. Also: the reasoning rule follows the catalogue, which marks **mimo-v2.5** as well as gpt-5-nano and deepseek-v4-flash, so the primary candidates are gpt-4.1-nano and gpt-4o-mini. X7 is cited as the EDA experiment plan's routing benchmark (docs/full_eda/experiment_plan.md), not the context plan's own X-numbers.
- **Thresholds frozen (tune only):** `max_u_chars` 200 (EDA rule, claim `route.simple_rule_share`); `max_input_tokens` 16,000, chosen by the least-aggressive criterion over {500 … 32,000}. Unstable: the five session-grouped folds chose 8,000 to 32,000, and the saving still rises at the grid ceiling.
- **New:** `experiments/routing/exp-route-012-small-classifier/{version.py,README.md}`, `scripts/small_classifier_levers.py`, `tests/unit/experiments/test_exp_route_012_small_classifier.py` (12 tests, synthetic), `reports/routing/exp-route-012/tune_checks.json`, `docs/adr/draft-small-classifier-routing.md`. **Changed:** `experiments/README.md`, `experiments/routing/README.md` (list entries), `docs/project/progress.md` (index). No `src` change; `baselines_full.py` and `routing_base.py` unchanged.
- **TDD:** the 12 tests failed on import, then against a stub (`NotImplementedError`), then all passed.

### Results (tune split, LLM rows; aggregates; cost simulation, quality not proven)

209,331 LLM rows. Simple: 0.771 of LLM rows. Primary moves 81,122 (0.388), all to gpt-4.1-nano; secondary moves 160,360 (gpt-5-nano 137,911, mimo-v2.5 22,449).

| Baseline | primary saving share [95%] | secondary |
|---|---|---|
| `todays_models` (router's own effect) | 0.272 [0.203, 0.343] (61.25 of 225.44 USD) | 0.306 |
| `as_logged` | 0.179 [0.130, 0.234]; 25,816 rows unknown (no implied cached rate for gpt-4.1-nano) | 0.175 |
| `premium_gpt_5_5` | 0.377 | 0.380 |
| `best_single_cheap` (gpt-5-nano) | 0 | 0.012 |

Concentration: top bot 0.378, top 5 bots 0.748, top tenant 0.764 of the `todays_models` saving; the largest tenant has 0.456 of LLM requests (above 0.35, flagged). Traffic-weighted 0.128. R-B3 (0.70% on `todays_models`) is not directly comparable: interim eligibility and a run before the replay price table. EDA upper bound `route.sim_save.simple_rule` 0.142 is on a different basis.

Dry run of the writer on the tune split into a scratch folder: 8 results, `n_saving_unknown` as above, all slices present; not kept.

### Open
- Owner review of ADR draft point 6 (incumbent per baseline) and of the mimo-v2.5 exclusion.
- `max_input_tokens` depends on the grid ceiling; the owner may prefer 8,000 (the over-8k boundary, chosen by two of five folds).
- `as_logged` rests on thin implied rates (gpt-4.1-nano 447 billed items).
- The logistic mode waits for P-3 labels; the routing decision rule cannot pass without them.
- Report-split LeverResults not written: the owner runs `scripts/small_classifier_levers.py` on a clean tree after the commit.
