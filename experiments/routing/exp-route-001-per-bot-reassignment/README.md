# exp-route-001: per-bot reassignment + rules (R-A3)

**Status: cost simulation; quality not proven. Eligibility is R-0 (`analysis.routing_base`, ADR-0045). The per-baseline accounting follows ADR-0046 point 6, provisional; owner to confirm (Q-B21).**

Pipeline A's routing version for the sprint (final plan, task R-A3; "Routing without quality labels"). Traces: FR-ROUTE-01, FR-ROUTE-02 (target and reason per request), FR-ROUTE-03 (rule-based policy behind one interface), FR-ROUTE-04 (overhead), FR-ROUTE-05 (eligibility), H-5 (cheap features route; *not measurable* without quality labels, EDA §4.4), X7 (the routing benchmark this would need), Review Focus 1 and 3, ADR-0036, ADR-0045, ADR-0046. H-6 (cascade) is not addressed here. Decision record: [ADR-XXXX (per-bot-reassignment)](../../../docs/adr/draft-per-bot-reassignment.md).

## Hypothesis

Most bots run one model chosen by configuration, not by need. Reassigning a whole bot to the cheapest routing candidate that can take all of its traffic lowers token cost. Without benchmark labels this tests **cost only**. The plan's routing rule (acceptable rate within 10 points of the incumbent) cannot be applied, so no bot is declared moved.

## Rules (declared 2026-11-03; v2 the same day, when R-0 and ADR-0046 reached `main`; also in `config.toml`)

| Element | Rule | State |
|---|---|---|
| Fit rows | `split_by_session` **tune** and `period` tune (March to July 2026), LLM requests, as R-C3 | decided |
| Eligibility and cost | R-0: `routing_base.eligible_models` (`constraints`) and `candidate_costs` (`costs`), injected; `sprint.toml [routing]` as `rules`; `candidates_jev` dropped (J-3 passes its own list) | decided (ADR-0045) |
| Candidate sets | primary `route.per_bot`: `[routing] candidates` without those the catalogue marks `hidden_reasoning_billed_as_output` (today `gpt-4.1-nano`, `gpt-4o-mini` remain); secondary `route.per_bot.with_reasoning_models`: all five, "lower bound on candidate cost, hidden reasoning not counted" | decided (ADR-0046 point 4) |
| Target per bot | the candidate R-0 allows for **every** priced tune request of the bot, with the lowest summed list-price cost (ties alphabetical) | decided (owner, 2026-11-03: keep the strict rule after the finding below) |
| Decision per baseline | a bot is reassigned in a baseline only if the target's tune cost is strictly lower than **that baseline's own model** there, in that baseline's units (`todays_models`/`as_logged`: logged model; premium; best single cheap). A request then moves only if the target is eligible for it, another model and strictly cheaper on it. Never upward; each row's saving is >= 0 | follows ADR-0046 point 6, provisional; owner to confirm (Q-B21) |
| Kept as is | bots under `min_n` (30) tune requests, unpriced incumbents, bots with no eligible target, bots unseen in tune; requests the target cannot take (`row_not_eligible`) or where it is not cheaper (`row_not_cheaper`) | decided |
| Repricing | `baselines_full.token_counts` (cached tokens added back for the logged models that report them separately, Review Focus 3), `model_row_costs` / `repriced_row_costs` (tiers); token counts model-independent | decided |
| `as_logged` | recorded token cost against the target at implied recorded rates (`reports/full_eda/tables/implied_unit_rates.csv`, ADR-0038 pattern); a needed rate that is missing makes the saving unknown (row out of both sides), never 0; rows not moved save exactly 0; fees never change | decided (ADR-0046 point 5) |
| Output | `apply` (the `todays_models` decision) adds `routed_model`, `route_reason`, `route_target`, `route_target_cost`, `route_cost_incumbent`, `route_cost_routed`; recorded blocks unchanged; `baseline_frames` gives each baseline's before/after blocks | decided |

`baseline_frames` gives the same `todays_models` and `as_logged` saving as R-C3's on a [SYNTHETIC] frame where both move the same rows (tested). R-C3's code is not imported outside that test; the R-A3 logic is its own, smaller equivalent.

## Reproducing the EDA simulation first

`python scripts/run_per_bot_reassignment.py eda` re-implements `full_eda_analyze.routing_finance`. It uses billed requests (all months), cached tokens added back as the EDA frame does, every request at one target's implied **recorded** rates, savings clipped at 0, and shares of recorded cost. **Result: 14.1677% (simple rule) and 41.6330% (all billed requests); ledger 14.17677% and 41.63301%.** The EDA's candidate set was one model, `gemini-2.5-flash-lite`. It is priced in the replay catalogue but `enabled = false`, so R-0 never chooses it. Same rule at the sprint's five candidates: 12.2% to 13.6% and 34.5% to 40.4%. These are hypothetical upper bounds.

## Results on the full data (2026-11-03, report split: 73,063 requests, 20,750 LLM)

Fit: 230,762 tune rows; 531 bots. Primary: 86 bots reassigned in `todays_models`, 14 with no cheaper target, 130 without an eligible target, 299 insufficient, 2 unpriced. With reasoning models: 100, 0, 130, 299 and 2.

| Baseline (units) | Result | Cost known / LLM | Unknown | Baseline total | Saving | Share (95% CI) | Requests switched |
|---|---|---|---|---|---|---|---|
| `todays_models` (price-file) | **primary** | 20,707 / 20,750 | 0 | 242.62 | 15.24 | **6.28%** (5.03% to 7.49%) | 3,551 |
| | with reasoning | 20,707 / 20,750 | 0 | 242.62 | 17.27 | 7.12% (5.69% to 8.51%) | 3,714 |
| `premium_gpt_5_5` (price-file, estimate) | primary | 20,744 / 20,750 | 0 | 3,737.89 | 305.52 | 8.17% (6.47% to 9.90%) | 3,714 |
| | with reasoning | 20,744 / 20,750 | 0 | 3,737.89 | 307.56 | 8.23% (6.51% to 9.97%) | 3,714 |
| `best_single_cheap` (`gpt-5-nano`) | primary | 20,744 / 20,750 | 0 | 39.75 | 0 | 0% | 0 |
| | with reasoning | 20,744 / 20,750 | 0 | 39.75 | 0.0009 | 0.002% | 75 |
| `as_logged` (recorded) | **primary** | 20,629 / 20,750 | **115** | 145.82 | 5.83 | **4.00%** (3.65% to 4.41%) | 2,656 |
| | with reasoning | 20,744 / 20,750 | 0 | 146.50 | 5.64 | 3.85% (3.44% to 4.23%) | 2,732 |

The 115 unknown `as_logged` requests have cached tokens and the target `gpt-4.1-nano`, which has no implied cached rate (ADR-0046 consequences). All `todays_models` savings of the primary result go to `gpt-4.1-nano`; with reasoning models, to `gpt-5-nano` (17.27) and `mimo-v2.5` (0.008).

**The three reasoning-billed models** (ADR-0046 point 4). Under these rules they add 0.84 points (7.12% against 6.28% in `todays_models`). Of the earlier 74.0% (interim eligibility, 2026-11-03 morning), all of it came from them: every bot chosen then went to `gpt-5-nano` (170) or `mimo-v2.5` (20).

**Finding: why the earlier 74.0% fell to 6 to 7%.** For `todays_models` the definition did not change (its incumbent was already the logged model). The drop comes from eligibility. R-0 refuses a request whose attachment count is unknown (`attachments_unknown`, 0.6% of tune LLM rows), where the interim rules let it through. The declared bot rule needs the target eligible on **every** priced tune request, so a few such rows rule out a whole bot. The 1st bot by tune volume fails on 2,707 of 80,526 rows (1,936 with attachments, 356 unknown attachments), the 3rd on 4 of 8,110 (all unknown attachments). The five costliest report bots (81% of `todays_models` cost) now have no target, although their report requests are eligible. **Owner decision (2026-11-03): keep the strict rule.** A bot is reassigned only if the target can take all of its priced tune traffic, unknown attachment counts included (FR-ROUTE-05: unverified counts as unsupported).

**Against the EDA** (recorded units both). `as_logged` saves 4.00% of recorded cost over report LLM requests; the EDA rule group alone gives 0.88% of that total (`eda_simple_rule.saving_share_of_all`). The EDA's 41.6% (all billed) and 14.2% (rule group) are hypothetical upper bounds, comparable only in unit and method of pricing (implied recorded rates, never upward). Five things differ: population (all billed requests, all months, against the report split's LLM requests), target (`gemini-2.5-flash-lite`, the cheapest high-volume model, against the bot's cheapest R-0-eligible primary candidate), eligibility (none against R-0), the decision unit (request against bot, fitted on tune), and the rows priced (EDA clips at 0, R-A3 moves only cheaper rows; both give >= 0).

**Slices** (`todays_models`, primary): tenant cap 0.35 gives 4.00% (6,038 requests); unweighted bot mean 7.54% against traffic-weighted 6.28%. No eligible candidate per request (report LLM, share of `todays_models` cost): functions 1,450 (6.34%), attachment (including unknown) 379 (0.24%), both 42 (0.02%), limit 1 (0.19%).

**Per-bot table** (`reports/levers/route.per_bot.bots.csv`; top 10 by `todays_models` cost; price-file cost per request; quality not proven; "reassigned in" lists the baselines whose gate passed):

| Rank | Incumbent | Candidate | Reassigned in | Requests | Before | After | Share of cost |
|---|---|---|---|---|---|---|---|
| bot-01 | gemini-2.5-flash | none (no eligible target) | none | 5,809 | 0.02416 | 0.02416 | 57.8% |
| bot-02 | gemini-2.5-flash | none (no eligible target) | none | 1,559 | 0.01592 | 0.01592 | 10.2% |
| bot-03 | gemini-2.5-flash | none (no eligible target) | none | 1,406 | 0.01069 | 0.01069 | 6.2% |
| bot-04 | gemini-2.5-flash | none (no eligible target) | none | 926 | 0.01174 | 0.01174 | 4.5% |
| bot-05 | gemini-2.5-flash | none (no eligible target) | none | 1,323 | 0.00469 | 0.00469 | 2.6% |
| bot-06 | gemini-2.5-flash | gpt-4.1-nano | todays, premium, as_logged | 401 | 0.01205 | 0.00335 | 2.0% |
| bot-07 | gemini-2.5-flash | gpt-4.1-nano | todays, premium, as_logged | 220 | 0.01895 | 0.00489 | 1.7% |
| bot-08 | gemini-2.5-flash | none (no eligible target) | none | 898 | 0.00444 | 0.00444 | 1.6% |
| bot-09 | gemini-2.5-flash | none (no eligible target) | none | 204 | 0.01892 | 0.01892 | 1.6% |
| bot-10 | gemini-2.5-flash | gpt-4.1-nano | todays, premium, as_logged | 988 | 0.00341 | 0.00063 | 1.4% |

**Overhead** (`scripts/measure_lever_overhead.py`, offline per-request estimate, not a load test, Q-14; 1,000 seeded report-period LLM rows as one-row frames; tune fit before timing): primary p50 34.0 ms, p95 **54.2 ms**; with reasoning models p50 22.0 ms, p95 51.5 ms (AMD Ryzen 7 5800H, CPython 3.13.9, 2026-11-03). Both pass the 100 ms target. A first measurement of this version gave 101.2 / 117.1 ms (fail) while `apply` priced every candidate; it now prices only the targets present and single models with `baselines_full.model_row_costs`. That is the same math, tested equal. The result files were written just before that change and not re-run, so the report split was not read again.

Files: `reports/levers/route.per_bot.{premium_gpt_5_5,as_logged,todays_models,best_single_cheap}.json`, the same for `route.per_bot.with_reasoning_models`, and `route.per_bot[.with_reasoning_models].bots.csv`. Run: `python scripts/run_per_bot_reassignment.py run` (and `eda`).

## Assumptions

- *Current:* quality not proven; cost simulation only. Historical model choice is bot configuration, not a label (EDA §4.4).
- *Current:* token counts are model-independent (tokenizers differ, Persian especially); logged output length unchanged; hidden reasoning not counted (the secondary result is a lower bound on candidate cost).
- *Current:* R-0 verifies no modality or tool capability, so attachments (known or unknown) and bots with functions get no candidate (FR-ROUTE-05).
- *Current:* implied recorded rates rest on few billed items for some models (`gpt-4.1-nano` 447); `as_logged` is provisional.
- *Speculative:* `gpt-4.1-nano` answers these bots acceptably. Untested; X7 / P-1…P-3 would test it.
