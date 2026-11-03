# Jev on the 150 dev-slice records (exp-route-013, 2026-11-03)

- **Question:** if Jev (Metis TypeSafe, `jev-1.14.0`) chose the tier for the 150 real dev-slice requests, how much would the answering models cost compared with today's models and with the rules alone?
- **Permission:** Q-55, answered 2026-11-03 (Metis's written OK, filed by the owner). Read conservatively as covering Jev through the Metis wrapper only; chat-model APIs (paid benchmark gate 2) stay closed.
- **Evidence class:** *cost simulation on logged tokens*. **Quality is not proven.** No labels exist for these 150 requests, so "Jev chose a cheaper model" is not "Jev chose well".
- **Run:** `powershell -ExecutionPolicy Bypass -File experiments\routing\exp-route-013-decision-router\jev_dev_slice\run.ps1` (plan first with no call; run cap 0.05 USD; `live.enabled` and `router.real_data_approved` on for that step only; every call through the spend guard and `data\spend\ledger.jsonl`). Code: `scripts/evaluate_router_slice.py --backend jev`, `wiring/router_eval.py`, `evaluation/router_eval/costs.py`.
- **Output:** `runs/jev_slice/shadow_jev.json` (git-ignored; counts, shares, costs, no text) and `reports/routing/dev_slice_v1/jev_vs_rules_differences.csv` (opaque record IDs, tiers, Jev's probability and confidence, model IDs; no text).

## How the cost is simulated

- Each record keeps its **logged** tokens. Three arms are priced on them with the replay prices of ADR-0041: **today** (the model the record actually used), **rules** (the decision-router policy with the router off) and **router** (Jev's tier, cheapest eligible model of that tier).
- Tokens are assumed model-independent; the logged output length stands in. A second variant, `with_expected_reasoning`, adds the hidden reasoning tokens the sprint assumes for reasoning-billing models.
- gpt-4.1-nano (HTTP 404, deprecated) and mimo-v2.5 (HTTP 400, unsupported) are switched off in memory for this run, so tier 0 is **gpt-5-nano only** (A-123). The catalogue file itself is unchanged (TODO-17).
- The answering totals **do not include Jev's own calls**. The "net" lines below add them.

## Result (run 1, 2026-11-03)

| | |
|---|---|
| Records / answered / skipped | 150 / 124 / 26 |
| Jev calls, version | 124, all `jev-1.14.0` |
| Jev cost | **0.0044806608 USD** (about 0.0000361 per call); ledger left of the 0.05 run cap: 0.0455 |
| Time | 144.6 s for the whole run; decision step p50 0.88 s (over all 150, skipped ones count as 0), p95 1.85 s, max 3.72 s: still never inline |
| Tier mix | rules: tier 0 4.0%, tier 1 90.7%, no model 5.3%. Jev: tier 0 14.7%, tier 1 80.0%, no model 5.3% |
| Agreement with the rules | 88.7% (126 of 142 where both chose); all 16 differences are Jev choosing the lower tier (higher-tier share 0.0, lower-tier share 11.3%) |
| Models | rules: gpt-4o-mini 136, gpt-5-nano 6. Jev: gpt-4o-mini 120, gpt-5-nano 22 |

Answering cost on the 142 priced records (USD):

| Variant | Split | Today | Rules | Router (Jev) | Jev vs rules | Jev vs today |
|---|---|---|---|---|---|---|
| logged tokens | all (142) | 0.5068 | 0.2195 | 0.2143 | **2.35%** | 57.7% |
| | tune (99) | 0.3524 | 0.1555 | 0.1546 | 0.56% | 56.1% |
| | check (43) | 0.1544 | 0.0640 | 0.0598 | 6.70% | 61.3% |
| with expected reasoning | all (142) | 0.5070 | 0.2199 | 0.2158 | **1.87%** | 57.4% |
| | tune (99) | 0.3526 | 0.1556 | 0.1553 | 0.22% | 56.0% |
| | check (43) | 0.1545 | 0.0642 | 0.0605 | 5.86% | 60.9% |

**Net of Jev's own calls** (0.0044807 USD added to the router): saving over the rules is **0.0006870 USD = 0.31%** with logged tokens and **−0.0003690 USD = −0.17%** with the reasoning allowance; against today's models 56.8% and 56.6%, where the rules alone already give 56.7%.

## How to read it

- **Almost all of the 57% saving over today's models is the rules' (56.7%), not Jev's.** Jev adds about **2% (2.35% / 1.87%)** over the rules on 150 requests.
- **Not significant on this sample.** Only 16 of 142 records differ; the split results disagree (0.6% on tune, 6.7% on check); no test or interval was computed, and the whole difference (0.005 USD) is as large as what Jev itself costs (0.0045 USD) on these 150 requests. Treat the gap to the rules as zero until a larger sample says otherwise.
- **Quality is unproven.** All 16 differences send a request to the cheaper tier. If those requests need tier 1, the saving is a quality loss. The synthetic check (A-125) found Jev over-sends easy requests to tier 1 and rarely under-routes hard ones, but that was synthetic text and one rater.
- **Tier 0 is a single model** (gpt-5-nano); the cheaper tier has no second choice while two catalogue models are gone.

## The skipped decisions and the unpriced records

- **26 skipped = 18 + 8.** 18 are path `fast_rules` (12.0% of 150): the gate's decisive rules (greeting, code or coding intent, attachment, long message) answered, so Jev was deliberately not asked. 8 are path `none` (5.3%): the rules found **no eligible model**, so there is nothing to decide. 124 + 18 + 8 = 150.
- **8 unpriced** (`rules_no_model: 8`): the same 8 records. With no model chosen there is no price, so they are left out of **all three** totals and the comparison is on the same 142 records.
- **Why the 8 have no eligible model** was not recorded in run 1. From run 2 the output has a `skips` block (per path and skip reason; the rules' reason code and the exclusion reasons of the models removed), and the differences CSV is written by the same run.

## Still open

- **Labels** for the 150 requests (`reports/routing/dev_slice_v1/review_template.csv`, then `build_router_dev_slice.py import-labels`) or the paid benchmark's judge labels (gate 2, Q-62..Q-64). Until then `against_labels` has nothing to score.
- **Run 2** (`run.ps1` again, about 0.0045 USD) for the differences CSV and the skip reasons. Jev is a hosted model and not guaranteed deterministic: if the counts above change, the table is updated from run 2 and the change is noted here.
- A bootstrap over per-record costs, once the per-record rows are kept, to put an interval on the 2%.
