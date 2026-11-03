## Sprint Day 3, Pipeline A: R-A3 per-bot reassignment on R-0, accounted per ADR-0046 (2026-11-03)

Plan: [`2026-11-01-final-plan.md`](../../superpowers/plans/2026-11-01-final-plan.md), task R-A3 and L-1. Branch `per-bot-reassignment-day3`, fast-forwarded to `origin/main` d692423 (R-0 #31, R-C3 / ADR-0046, #35). **Awaiting review.** **Cost simulation; quality not proven; no bot is declared moved.**

- **Version** ([`exp-route-001`](../../../experiments/routing/exp-route-001-per-bot-reassignment/README.md), v2): `PerBotReassignment(candidates, *, constraints, rules, cached_separately, costs)`. Fitted on tune rows (split and period, as R-C3). Per bot, the target is the cheapest candidate R-0 allows on every priced tune request; the bot is reassigned per baseline only if the target is cheaper than that baseline's own model in its units (ADR-0046 point 6, provisional). A request moves only if eligible and strictly cheaper (each row >= 0). `baseline_frames` does the accounting; `as_logged` uses implied recorded rates, unknown never 0.
- **R-0 switch-over:** `routing_base.eligible_models` and `candidate_costs` injected; `sprint.toml [routing]` as rules, `candidates_jev` dropped; B's interim function and label are no longer used. **ADR-0046:** point 4 (reasoning-billed candidates excluded from the primary result; secondary `route.per_bot.with_reasoning_models`), point 5 (`as_logged`), point 6 (provisional, followed).
- **Decision record:** [ADR-XXXX (per-bot-reassignment)](../../adr/draft-per-bot-reassignment.md), a draft (the merger numbers it with `scripts/adr_finalize.py`; CI stays red until then). Points 1 to 5 and 7 decided by the owner, point 6 provisional with ADR-0046 (Q-B21).
- **Runner:** `scripts/run_per_bot_reassignment.py {run,eda}`. **L-1:** `route.per_bot[.with_reasoning_models]` targets in `scripts/measure_lever_overhead.py`. **Index rows:** `module_reference.md` (version and script; L-1 row), `experiments/routing/README.md`.
- **Tests** (each new behaviour failed first; the one-model cost-equality test pins a refactor and passed before and after it; the plain-rules test follows a failed run): `test_per_bot_reassignment.py` (20: the plan's four; R-0 rules on [SYNTHETIC] rows; R-0 path equal to the row-by-row path; JEV list dropped; reasoning-billed from the catalogue; each baseline's own effect; no negative row saving in any baseline; `as_logged` unknown and zero; **same `todays_models` and `as_logged` saving as R-C3 on a [SYNTHETIC] frame**; one-model cost equal to the shared rule; only needed targets priced; identity, insufficient, unpriced, cache hits, unseen bot, J-3 argument). `test_run_per_bot_reassignment.py` (13: EDA reproduction, four baselines in their own units, saving definitions, saving by target, point-6 assumptions, rank labels, R-0 loaders, plain manifest rules, rate loader). `test_measure_lever_overhead.py` (+2 cases).
- **Runs:** the first v2 run stopped at manifest building (a TOML date in `[[routing.retiring]]`, now `plain_rules`, tested) after applying the version to the report split, writing nothing; the second wrote the results. L-1 then failed (101.2 / 117.1 ms p95) because `apply` priced every candidate. It now prices only the targets present with `model_row_costs` (same math, tested equal), p95 54.2 / 51.5 ms; results not re-run.

### Before and after, per baseline (report split, 20,750 LLM requests)

Old = this morning: interim eligibility, five candidates, saving = baseline minus routed pipeline cost. New = R-0, ADR-0046 points 4 to 6.

| Baseline | Result | Cost known | Unknown | Baseline total | Saving | Share (95% CI) |
|---|---|---|---|---|---|---|
| `todays_models` | old | 20,707 | 0 | 242.62 | 179.63 | 74.04% (72.42 to 75.57) |
| | **new primary** | 20,707 | 0 | 242.62 | 15.24 | **6.28%** (5.03 to 7.49) |
| | new with reasoning | 20,707 | 0 | 242.62 | 17.27 | 7.12% (5.69 to 8.51) |
| `premium_gpt_5_5` | old | 20,707 | 0 | 3,737.33 | 3,674.35 | 98.31% (98.21 to 98.41) |
| | new primary | 20,744 | 0 | 3,737.89 | 305.52 | 8.17% (6.47 to 9.90) |
| | new with reasoning | 20,744 | 0 | 3,737.89 | 307.56 | 8.23% (6.51 to 9.97) |
| `best_single_cheap` | old | 20,707 | 0 | 39.74 | −23.24 | −58.48% (−68.44 to −49.09) |
| | new primary | 20,744 | 0 | 39.75 | 0 | 0% |
| | new with reasoning | 20,744 | 0 | 39.75 | 0.0009 | 0.002% |
| `as_logged` (recorded) | old | — | — | — | — | not computed |
| | **new primary** | 20,629 | **115** | 145.82 | 5.83 | **4.00%** (3.65 to 4.41) |
| | new with reasoning | 20,744 | 0 | 146.50 | 5.64 | 3.85% (3.44 to 4.23) |

- **Reasoning-billed models:** +0.84 points under the new rules; all of the old 74.0% went to them (170 bots to `gpt-5-nano`, 20 to `mimo-v2.5`).
- **Why 74.0% became 6 to 7%** (`todays_models` definition unchanged): R-0 refuses unknown attachment counts (0.6% of tune LLM rows; the interim rules did not), and the declared bot rule needs the target eligible on every priced tune request. The five costliest report bots (81% of cost) now have no target, though their report requests are eligible (the 3rd bot by tune volume fails on 4 of 8,110 rows).
- **Against the EDA:** `as_logged` 4.00% of recorded cost (rule group alone 0.88% of it) against 41.6% and 14.2%. Same unit and pricing method; population, target, eligibility and decision unit differ (README).
- Per-bot table (top 10, new primary): ranks 1 to 5, 8, 9 keep `gemini-2.5-flash` (no eligible target); 6, 7, 10 go to `gpt-4.1-nano` in `todays_models`, premium and `as_logged`. Full table in the README.

### Q-B21, for the team and the owner

ADR-0046 point 6 (routing saving = the lever's own effect in each baseline) is provisional. R-A3 now follows it; R-B3 uses the older reading (baseline minus routed pipeline; ADR-0048 point 6, merged in #37, names both meanings and leaves the choice for I-2). Confirm point 6, so that B aligns and the routing decision rule (beat per-bot reassignment outside the CI) compares like with like.

### Proposals (text only; no file of another owner was edited)

1. **For C (`sprint.toml`):** for the cost replay, add the priced Gemini flash-lite models and the second DeepSeek model to `[routing] candidates` (`gemini-2.5-flash-lite`, `gemini-3.1-flash-lite`, `deepseek-v4.1-flash`); the EDA's own target was `gemini-2.5-flash-lite`. Useful only with proposal 2.
2. **For the team (R-0):** separate **"priced for replay"** from **"callable"**. ADR-0045 keeps "enabled" as a requirement and the replay catalogue's Gemini rows are `enabled = false` without limits, so R-0 can never choose them. **Left open.**

### Open questions

- **Bot rule under R-0: decided by the owner (2026-11-03), keep the strict rule** (the target must be eligible on every priced tune request; unknown attachment counts count as ineligible). Results unchanged.
- Unknown attachment counts: is `u_att_n` missing a data gap (no user message) or a real unknown? R-0 treats it as unknown = ineligible (FR-ROUTE-05).
- `as_logged` rests on implied rates with few billed items for `gpt-4.1-nano` (447) and no cached rate (115 unknown requests).
