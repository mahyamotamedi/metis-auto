# Routing experiment plan (Stage 8)

Status: **planned**; no routing strategy is pre-selected (NG-06, FR-ROUTE-03). The `pipeline_replay` runner and the `routing_policy` candidate slot exist and are tested (framework.md §4); no routing experiment has run on the sample yet. Thresholds marked *proposed* are **confirmed as provisional placeholders** (Q-38, 2026-10-19): every run reports its measured values against all of them, and they are revisited with the full dataset. Last updated 2026-10-18.
Framework: [framework.md](framework.md). Architecture: [routing.md](../architecture/routing.md), [attempts.md](../architecture/attempts.md). Requirements: FR-ROUTE-*, FR-CASC-*, FR-FEAT-*, H-5, H-6; owner brief [§7](../project/live_testing_and_demo_brief.md#7-routing-sticky-routing-v1-placeholder-rules-all-in-config) (sticky routing v1).

## 1. What every routing experiment reports

The same comparison format for every strategy (framework.md §6), overall and per stratum (opaque category, turn depth; language and length buckets once the language detector exists):

| Metric | How | Notes |
|---|---|---|
| Quality | judge score and non-inferiority vs the premium and as-logged baselines (ADR-0006 b, c); agreement with the logged answer as a secondary metric | δ: −3 % overall, −5 % per stratum (Q-13). Needs answers from the routed model: `recorded` or `live`, so quality claims wait for them (ADR-0014). |
| Cost | total and per request, with fidelity and price version; savings vs both baselines; the savings decomposition (brief §6) | Includes router overhead, failed attempts, and escalations (A-18). |
| Latency | router overhead p50 and p95 (inside 100 ms, Q-14); model and end-to-end latency only from `recorded` / `live` | Logged timestamp gaps are never latency. |
| Routing accuracy or proxy | agreement with the label of §3 that the approach uses | Always named: "accuracy vs label X". |
| Escalation rate, failover rate | from `escalation_triggered` / `failover_triggered` events | Cascades only. |
| Routing mix | share of requests per model and tier, from `routing_decided` | |
| Coverage | share of cases with an answer from the declared source | Quality over covered cases only, with the bias stated. |

## 2. The label problem

The sample has **no ground-truth difficulty or quality labels**. The logged answers come from 18 heterogeneous labels, are not gold, and are heuristically paired (C-07, A-04). Logged model choice is not a label either: it reflects whatever each bot was configured with, not what each request needed (no within-session model switching was observed, a provisional signal). So:

| Label | What it is | How it is made | Cost and risk | Used by |
|---|---|---|---|---|
| L0: none | strategies that need no training | — | — | rules, sticky v1 |
| L1: cheap-model acceptability | for each request: is the cheapest model's answer acceptable (judge score ≥ τ, or judged non-inferior to the premium answer)? | run the cheap model (and premium) on a stratified subset, judge the pairs | live calls: about 2–3 calls per request (cheap model, premium or reference, judge); the judge's bias; Persian judging unverified | classifiers, ML, learned routers |
| L2: minimal adequate tier | the cheapest tier whose answer passes the judge | L1 extended to every tier | ×tiers the cost of L1 | multi-class routers, cascades |
| L3: owner or human labels | difficulty or acceptability marked by a person on a small set | labelling tool over local content | owner time; no data leaves the machine | judge calibration (TODO-05), sanity checks |
| L4: synthetic labelled set | requests written to be easy or hard (code, reasoning, long context, Persian, mixed) | written for the purpose, marked synthetic | doesn't reflect real traffic | smoke tests, overhead, mechanics |
| Proxy P1 | cheap features: length bucket, code present, attachment, language, turn depth, retrieved context present | the feature extractor | not quality; may encode the sample's quirks | rules |

Budget: with the 10 USD lifetime cap (Q-29) and test-model prices, L1 on a few hundred synthetic or owner-approved requests is affordable (single-digit cents per request); each run is estimated first and needs the owner's approval (ADR-0018). Sample conversations go to a provider only with per-run approval and the privacy review. The judge is calibrated against L3 before its scores are trusted (ADR-0006, TODO-05).

## 3. Hidden reasoning makes nominal prices misleading

The live check verified that **gpt-5-nano, deepseek-v4-flash (thinking on by default through the wrapper), and mimo-v2.5 bill hidden reasoning tokens as output** ([live check](../references/metis_wrapper_live_check.md)): gpt-5-nano billed 256 of 267 output tokens as reasoning for a two-token answer; DeepSeek 30 for 2; MiMo 12 of 15. So "cheapest by price table" is not "cheapest per answer". Every routing experiment therefore:
- prices answers from **reported** usage (`recorded` / `live`) when it compares cost, never from the visible answer alone (which is a lower bound, caveat `reasoning_not_counted`);
- reports **effective cost per answer** per model and stratum (including reasoning), next to the nominal per-token price;
- treats reasoning settings as configuration under test: DeepSeek and MiMo `thinking` on or off (`[model_options]`, Q-34), gpt-5 reasoning effort if exposed later. Thinking off is cheaper (0.000007 vs 0.000033 USD on the tiny check) but may cost quality; that is an experiment, not a default change.

The placeholder tiers and equivalence groups (A-48: by price) are replaced by measured effective cost and quality per model once L1/L2 exist.

## 4. Strategies, in the order they become testable

Each is a `routing_policy` candidate (pure `choose(features, eligible)`) unless noted; a model-based router is a measurement plus a pure decision (P-1).

| ID | Strategy | Needs | Planned EXP-ID |
|---|---|---|---|
| R0 | baselines: `fixed_model` on each test model (always-cheapest, always-mid), premium estimate, as-logged | nothing new | `exp-route-001` |
| R1 | **rules** over cheap features (P1): length bucket, code, attachment, language, turn depth → tier, cheapest eligible in tier (`rule_based`, routing.md §1) | language and code detectors (FR-FEAT, not built) | `exp-route-002` |
| R2 | **simple classifiers**: logistic regression or gradient boosting on cheap features, trained on L1 | L1 labels; a train/test split by session (no leakage) | `exp-route-003` |
| R3 | **traditional ML on text**: TF-IDF / char n-gram + linear model (Persian-safe tokenisation) | L1 | `exp-route-004` |
| R4 | **embedding-based**: nearest labelled neighbours or a small head on embeddings (Persian-capable embedder from the caching plan C2) | L1; embedder overhead | `exp-route-005` |
| R5 | **lightweight learned routers**: preference-trained routers in the style of published router work (matrix factorisation or a BERT-sized classifier over prompt pairs); check each method's licence and Persian coverage before use | L1/L2 pairs | `exp-route-006` |
| R6 | **LLM-based routing / judging**: a cheap model classifies difficulty, or judges whether the cheap answer suffices | live calls (its cost and latency are router overhead) | `exp-route-007` |
| R7 | **cascades**: the cheap model first, a detector decides escalation (ADR-0013); detectors: truncation, empty output (exist), refusal, language mismatch, self-reported uncertainty, a judge (opt-in) | answers from both tiers; L1 for detector accuracy | `exp-route-008` |
| R8 | **sticky routing v1** and its variants (§5) | R1's rules; session order | `exp-route-010` |

## 5. Sticky routing v1 (owner brief §7)

- **Rule (configuration, placeholders):** each history turn records who produced it (a model ID or `cache`); the policy reads it from the request (stateless, P-8). A message **anchors** the session only if it is **substantive**: not served from cache and not a greeting or small talk (a short message matching a configurable Persian + English phrase list, such as سلام, hi, thanks, مرسی, ok; never "short = trivial", since the sample's messages are short). Non-substantive messages go to the cheapest model and leave the session unanchored. Anchored + similar message → stay on the anchor model. Anchored + very different message (code appears or disappears, an attachment appears, the language switches, the length bucket jumps) → re-route and re-anchor. An unsatisfactory answer → escalate, and the session anchors to the stronger model (only up, never down). Initial routing: R1's rules mapped onto the five test models.
- **Variants compared:** (a) per-request routing (R1, no stickiness); (b) sticky v1, re-routing after a cache hit; (c) sticky, staying on the anchor after a cache hit (keeps the provider cache warm, C5); (d) per-bot routing (one model per instruction group, the logged pattern).
- **Contract need:** the "who produced each history turn" field does not exist on `Turn` today; replay can derive it from the logged labels only for as-logged turns. Adding it is a contract change (optional, tri-state), decided in the Demo milestone.
- **Hypotheses:** H-5 (rules route a meaningful share to cheaper models without quality loss); sticky (c) earns more provider-cache saving than (b) at equal quality; (d) ≈ the as-logged pattern.
- **Metrics:** §1, plus the cached share of input tokens (C5), the re-anchor rate, and the escalation rate. The multi-turn effect of routing choices is **not simulated** in replay (logged history, A-30): sticky variants are judged on per-turn quality, and the provider-cache effect needs synthetic multi-turn sessions answered live or recorded.

## 6. Method common to all

- Data: replay cases, admitted flags `clean` and `multiple_answers` for quality metrics (others for cost and overhead only); split by session for any trained router; strata as §1.
- Sources: `fake` and `proxy` for routing mix, overhead, and cost shape; `logged_match` gives quality only where the routed model is the logged one (biased coverage, reported); `recorded` / `live` for quality and real cost.
- Every run reports against R0's baselines in the same table.

## 7. Success and kill criteria (proposed)

- **Success (promotion, repository_structure §6.2): both baselines must be beaten** (Q-38, owner, 2026-10-19):
  - **vs as-logged** (what Metis actually spent): savings ≥ **10 %** at quality non-inferior to the **as-logged answers** within δ (−3 % overall, −5 % per stratum, Q-13);
  - **vs premium:** savings ≥ 30 % with the judge score non-inferior within δ, overall and per stratum.
  Both on effective cost (reasoning and router overhead included), with router overhead p95 ≤ 100 ms and the escalation rate reported; for R1/R8 (no training) the same, on the full dataset. Why the as-logged bar: on the sample's 244 priced cases the premium estimate is 9.0× the as-logged cost (1.58 vs 0.175 USD, [EXP-CACHE-001](../../reports/caching/exp-cache-001/README.md)), so ≥ 30 % vs premium is met by almost any cheap model and says nothing about beating today's spending. Caveats: the as-logged cost is itself an estimate (A-62), and the as-logged quality reference requires judging the logged answers on the same rubric as the candidate's.
- **Kill:** a strategy that cannot beat always-cheapest (R0) on cost at equal quality, or the best fixed model on quality at equal cost, is dropped. A learned router (R2–R5) whose accuracy against L1 is no better than R1's rules on held-out sessions is dropped (simpler wins). An LLM router whose overhead cost exceeds the saving it enables is dropped.

## 8. Data needs and dependencies

Language and code detectors (FR-FEAT); L1 labels (a judge and a budget); recorded answers per test model for a shared request set (pay once, replay free); the full dataset for strata sizes; the `Turn` producer field for R8; Q-38 (thresholds).
