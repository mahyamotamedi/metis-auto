## Sprint Day 3, Pipeline C: routing base, eligibility, failover and candidate cost replay (2026-11-03)

Sprint task R-0, taken over from Parham with his agreement (owner, 2026-11-03), branch `routing-base-eligibility-failover` (from `main` at 37262d4, #30). **Awaiting review.** Before starting: `analysis/routing_base.py` was on no branch, local or remote. Traceability: FR-ROUTE-01, FR-ROUTE-05, FR-FAIL-01..04, A-48, Review Focus 3, ADR-0036, ADR-0041, ADR-0045 ([draft](../../adr/0045-routing-base-eligibility-and-failover.md)).

- **Owner decisions (2026-11-03), ADR draft points 1 to 6:** B's interim rules promoted unchanged in meaning; no verified vision model, so image requests stay on their incumbent; `sprint.toml [routing] avoid_long_context_tier = true` (the only sprint.toml change); unknown is never eligible; API `eligible_models` (plan shape), vectorised `eligibility_frame`, `failover`; free `candidate_costs` by `baselines_full`'s token rule.
- **Agent's reading, provisional (ADR draft point 7):** an unknown attachment count is excluded (decision 4 and the R-C1 rule). This is the one difference in meaning from B's interim file. `failover` takes `retiring` as a required keyword, an addition to the plan's `failover(model)`.
- **New:** `src/metis_auto/analysis/routing_base.py`, `tests/unit/analysis/test_routing_base.py` (13 tests, synthetic, plus one that loads the committed config), `scripts/routing_base_report.py`, `reports/routing/routing-base/tune_eligibility.json`, `docs/adr/0045-routing-base-eligibility-and-failover.md`. **Changed:** `baselines_full.py` (additive `model_row_costs`; behaviour unchanged) and one test in `test_baselines_full.py`, `config/evaluation/sprint.toml` (one key), `docs/architecture/module_reference.md` (new row; `baselines_full` row names the helper).
- **TDD:** the 13 tests failed against a stub (`NotImplementedError`; the config test on the missing key), and the helper test failed on import. Then all passed.
- **Out of scope:** per-candidate Persian tokenisation (plan R-0 "also tokenize"). This is a follow-up.

### Results (tune split, LLM rows; aggregates; `reports/routing/routing-base/tune_eligibility.json`)

209,331 LLM rows (`split_by_session == "tune"` inside the tune period, the rows R-B3 scores). Catalogue `cat-metis-replay-2026-11-02`, prices `prices-metis-2026-10-18-logged`, 5 models with cached tokens reported separately. **202,610 (96.79%)** have at least one eligible candidate. When none is eligible, the first failing reason is: attachments 2,676; functions 2,277; unknown attachment count 1,262; unknown tokens 506.

| Candidate | Eligible rows | Share | Own extra exclusions | Cost on its eligible rows (price-file USD) |
|---|---:|---:|---|---:|
| gpt-5-nano | 202,610 | 0.9679 | none | 46.64 |
| gpt-4.1-nano | 202,599 | 0.9678 | over output limit 11 | 74.49 |
| gpt-4o-mini | 202,577 | 0.9677 | over output limit 17, over window 16 | 113.49 |
| deepseek-v4-flash | 202,610 | 0.9679 | none | 110.09 |
| mimo-v2.5 | 202,610 | 0.9679 | none | 89.17 |

These are *simulation* figures: logged tokens, assumed model-independent, quality not measured. The long-context rule and the retiring replacement are inert today: no candidate has a tiered price, and `grok-4-1-fast` (the only retiring model) is not a candidate. `eligibility_frame` runs in about 0.02 s on these rows.

**Against B's README (EXP-ROUTE-011, commit 5a68fb6):** the row count (209,331) and unknown tokens (506) match exactly. B's README gives no per-candidate eligible count. Its `no_eligible_candidate` (7,502 / 1,862 / 880 at k = 5 / 15 / 50) is not comparable, for three reasons: it counts only the 88,971 rows the router scored (incumbent priced in the older test price file, bot sufficient), it applies eligibility only to the models the k neighbours ran (so it falls as k grows), and B ran before the replay price file. Under B's meaning (unknown attachments = none), 203,772 rows have a candidate: 1,162 more than here, none fewer. That is the whole difference.

### Switch-over notes
- **Pipeline B (R-B3):** in `scripts/run_pipeline_b_day3.py` (`_factory`), inject `metis_auto.analysis.routing_base.eligible_models` instead of `interim_eligible_models`. Pass `sprint["routing"]` as `rules` (it carries `candidates`, `candidates_jev`, `retiring` as tables, and the now-required `avoid_long_context_tier`). The row keys stay as they are (`input_tokens` effective, `output_tokens`, `u_att_n`, `bot_n_functions`). Then drop `LABEL` from the assumptions, delete `eligibility_interim.py` and its references, and re-run `rb3`. Expect slightly fewer eligible rows (unknown attachment count now excluded). Optionally swap `candidate_costs` for `routing_base.candidate_costs` or `baselines_full.model_row_costs`, which apply the same rule.
- **Pipeline A (R-A3) and Parham (J-3):** `eligibility_frame(req, ctx, rules=sprint["routing"], cached_separately=cached_reported_separately(req))` gives one bool column per candidate and `first_failing_reason`. `candidate_costs(req, ctx, candidates, rules=..., cached_separately=...)` gives per-row price-file cost (NaN = not eligible), equal to `baselines_full`'s repricing. `failover(model, catalogue, retiring=sprint["routing"]["retiring"])` gives the chain (its tier-up step is escalation, FR-FAIL-02). J-3: add JEV to `candidates_jev`. JEV needs a catalogue row with known limits, enabled, and priced, or it is never eligible (FR-ROUTE-05).

### Open
- Owner review of ADR draft point 7 (unknown attachment count excluded; 1,162 tune LLM rows).
- Per-candidate Persian tokenisation (plan R-0 "also tokenize"); until then fit and cost use logged tokens.
- `tier` and `equivalence_group` are placeholders (A-48): the failover chain is only as good as they are.
