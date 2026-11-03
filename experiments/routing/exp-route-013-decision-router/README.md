# EXP-ROUTE-013: the System-One decision router (Parham; J-3 remapped; R8)

- **Hypothesis:** H-1 (part of the traffic can run on a cheaper model). Here a System-One decision model (THX-01 local, Jev hosted) answers typed questions about each request, and a pure policy maps the answers to a tier. Traces: FR-FEAT-02 (a semantic signal), FR-ROUTE-03 (comparable, swappable strategies), FR-ROUTE-04 (router overhead), FR-ROUTE-05 (unknown limits exclude), FR-EVAL-04/06 (stratified, leakage-safe evaluation), QA-LAT (the 60 ms p95 budget inside the 100 ms overhead), QA-PRIV.
- **Decision record:** [ADR-0047](../../../docs/adr/0047-system-one-decision-router.md); the routing base is [ADR-0045](../../../docs/adr/0045-routing-base-eligibility-and-failover.md).
- **ID:** `exp-route-013`. `exp-route-011` is Pipeline B's kNN router; the routing plan reserves 001 to 008 and 010; R9 of the routing plan is this experiment.
- **Evidence class:** *simulation*. There are **no quality labels yet**, so agreement with the rules is not accuracy. Every result says "quality not proven".
- **Status (2026-11-03):** harness, routing step version and tests done; the THX-01 shadow run and the latency benchmark were run on the owner's machine (results below). The L1 labelling plan is prepared, not run. A first measurement of **decision quality** against owner labels on 100 SYNTHETIC requests (rules, THX-01 and Jev) is in [Synthetic decision-quality check](#synthetic-decision-quality-check-jev-synth-v1-2026-11-03).

## Parts

1. **Shadow evaluation on the frozen dev slice** (`scripts/evaluate_router_slice.py`, `wiring/router_eval.py`, `evaluation/router_eval/metrics.py`).
   - Each of the 150 records goes through two pipelines with the fake answering client:
     - **rules only:** the `decision_router` policy with `router.mode = "off"`, which applies the rules, then the safe tier; this is the inline mode if THX-01 misses the budget (A-114);
     - **with the router:** THX-01, local.
   - Reported, for all records, the tune split and the check split, each **balanced** and **traffic-weighted**, and per language group with **Persian first**:
     - the tier mix of each, agreement and its direction;
     - decision status and gate share;
     - the share below the confidence gate (mapping questions, Q-61);
     - path mix;
     - confidence p10/p50/p90;
     - the decision step's p95.
   - Local backends only. Jev never sees slice text until Metis allows it (Q-55).
2. **L4 synthetic labels in CI** (`tests/integration/test_router_shadow_eval.py`). A scripted backend's own tiers are used as SYNTHETIC labels, and the harness must reproduce them wherever the router answered. This tests the harness, not a model.
3. **Routing step version on R-0** (`version.py`, `DecisionRouterRouting`).
   - Decided tiers become routed models through the shared routing base, unchanged:
     - `candidate_costs` (R-0's eligibility rules) gives each eligible candidate's cost;
     - the cheapest eligible candidate **of the decided tier** is chosen;
     - the request moves only if that is strictly cheaper than the incumbent.
   - Reasons: `no_decision`, `incumbent_unpriced`, `no_eligible_in_tier`, `no_cheaper_candidate`, `moved`.
   - A full-data run needs a tier per request, i.e. the router run on full-data text; not done in the sprint (see Open).
4. **Latency** (`scripts/measure_router_overhead.py`):
   - variants: threads 2/4/8, at most 300 message characters, text vs JSON state;
   - inputs: synthetic and from the slice;
   - target: p95 ≤ 60 ms (Q-14, owner).

## Decision rules (declared before the results; owner, 2026-11-03)

- **Inline mode:** if any measured setting gives p95 ≤ 60 ms on `--from-slice`, the best one becomes the default and `local` is the router's inline mode. If none does, there is no ONNX conversion now (future work), inline routing is rules only, and THX-01 runs in shadow and offline evaluation only.
- **Gate:** the confidence gate reads the mapping questions only (complexity, needs_reasoning, cheap_model_ok), not intent (Q-61, configurable).
- **Routing rule (from the PDF, kept):** move traffic to a cheaper model only with quality labels showing that its acceptable rate is within 10 points of the incumbent's. Without labels, this experiment reports cost and agreement only.

## L1 labelling plan (prepared, not run)

L1 = golden-v2 reference answers judged per model (plan P-1/P-2), giving a tier label per request (the cheapest model whose answer is acceptable).

- **Gate:** the plan's three gates: the budget amendment, Metis allowing samples to be sent, and approval in chat per run.
- **Cost bound:** about 20–25 USD for 300 requests over five arms (the PDF's scaled estimate). It is replaced by `scripts/sampling_plan.py`'s printed estimate before any run.
- **Owner:** Kimia now owns P-1 to P-3 (scope change, 2026-11-03), so this experiment only consumes their labels: `against_labels(rows, labels)` scores rules and router once a tier label per slice or golden record exists.

L3 = human review of the slice: the review template is `reports/routing/dev_slice_v1/review_template.csv`. Labels come back through `scripts/build_router_dev_slice.py import-labels`, which checks IDs and values and keeps the labels local.

## Results (owner's runs, 2026-11-03)

- **Latency (THX-01, 4-core CPU, slice):**
  - p50 3.7 s, p95 10.8 s; load 152 s; 2.3 GB.
  - The weights are already float32. One batched pass of 5 × 172–222 tokens takes 3.3–4.8 s of forward time.
  - It is inherent on this CPU: **inline = rules only** (A-118).
- **Offline shadow run** (no deadline, no cache, gate off):
  - THX-01 answered 82.7% of the 150 records (the gate rules skip 17.3%) and **changed no routing decision**.
  - Agreement with the rules is 1.0, with no upgrade or downgrade. This holds overall, on tune and check, balanced and traffic-weighted, in every language group, and under both gate proposals.
  - Its yes/no answers sit near 0.5 (`cheap_model_ok` p50 0.62), so the tier-0 rule rarely fires and the safe tier (1) decides, as for the rules (A-121).
- **Confidence per question (p10 / p50 / p90, reported confidence):**
  - complexity 0.06 / 0.15 / 0.39;
  - intent 0.19 / 0.44 / 0.77;
  - needs_reasoning 0.52 / 0.63 / 0.90;
  - cheap_model_ok 0.52 / 0.62 / 0.85;
  - depends_on_history 0.52 / 0.62 / 0.84.
- **Gate proposals (provisional, unused, A-119):**
  - reported 0.0671: gates 8.1% of check answers;
  - probability 0.3897: gates 16.2%;
  - neither changes a check decision.
- **Conclusion:** no saving over the rules on the slice. Whether THX-01 is right needs labels; L1 is the next step.

## Synthetic decision-quality check (jev-synth-v1, 2026-11-03)

The first measurement of **decision quality** (not answer quality) with labels, using text that may go to Jev today. Owner request and approval in chat, 2026-11-03.

- **Set:** 100 SYNTHETIC requests written for this check, never copied or paraphrased from the dataset ([`synthetic_v1/labels_frozen.csv`](synthetic_v1/labels_frozen.csv)): 70 Persian, 15 English, 15 mixed. They cover greetings, short follow-ups (with the previous user turn), factual, support, translation, writing, code, math and multi-step reasoning, with easy and hard cases in each category.
- **Labels:** an expected tier per request, 0 (a small model is enough) or 1 (needs a stronger model), with a one-line reason. The owner, a Persian speaker, reviewed the set and approved it as is: 60 tier 0, 40 tier 1, 5 marked borderline. Frozen with sha256 in [`synthetic_v1/labels_frozen.json`](synthetic_v1/labels_frozen.json); the runner refuses a changed file.
- **Routers**, all through the real pipeline with the fake answering client:
  - `rules`: the `decision_router` policy with the router off (the R8 baseline): gate, then a matching rule, else the safe tier (1);
  - `rule_based`: the plain rule-based policy (ADR-0023 demo rules);
  - `thx01` (local) and `jev` (Metis, live): the model is asked on every row, with the fast gate off and the offline settings of R8;
  - `*_with_gate`: the router as configured, i.e. the fast gate's tier where it fires (14 rows), else the model's.
- **Text sent:** the `[SYNTHETIC]` marker is removed before routing for every router, because it made the language detector call 21 of the 70 Persian requests "mixed". `--keep-marker` sends it.
- **Run:** `powershell -ExecutionPolicy Bypass -File experiments\routing\exp-route-013-decision-router\synthetic_v1\run.ps1`. It prints the plan (Jev upper bound 0.0069 USD for 100 calls), runs the local routers, then Jev live with a 0.02 USD run cap through the spend guard and the ledger, and switches live off afterwards. Report: [`reports/routing/exp-route-013/synthetic_v1/report.md`](../../../reports/routing/exp-route-013/synthetic_v1/report.md) (tiers and IDs only).

**Results** (owner's run on Windows, 2026-11-03; Jev reported `jev-1.14.0`):

| Router | Accuracy (all, n = 100) | Persian (70) | English (15) | Mixed (15) | Under-routed, 1 → 0 (quality risk) | Over-routed, 0 → 1 (cost) |
|---|---|---|---|---|---|---|
| rules | 43% | 41% | 47% | 47% | 0 | 57 |
| rule_based | 59% | 61% | 53% | 53% | 35 | 6 |
| thx01 | 41% | 39% | 47% | 47% | 0 | 59 |
| **jev** | **72%** | **69%** | **87%** | **73%** | **1** | 27 |
| thx01_with_gate | 44% | 43% | 47% | 47% | 0 | 56 |
| jev_with_gate | 70% | 67% | 87% | 67% | 1 | 29 |

- **Trivial baselines:** always tier 0 scores 60% on this set, always tier 1 scores 40%. `rule_based` behaves almost like always-0 (89 rows to tier 0), and `rules` and THX-01 almost like always-1. Only Jev is above both; the Wilson 95% interval of its 72% is about 63–80%, which only just clears 60%.
- **Jev:** it missed 1 of the 40 tier-1 requests (a short humorous Persian couplet). Its errors are mostly easy requests sent to tier 1, which costs money but not quality. Where its own answers decided (85 rows; on 15 rows no mapping rule fired and the safe tier decided), it was right on 84.7%. Its weakest category is support (43%): simple procedural questions go to tier 1. It reports a confidence only for `complexity` (p50 0.83) and `intent` (p50 1.0); the yes/no answers carry probabilities only, as in R6. Decision latency p50 0.97 s, p90 1.1 s (about 10× the 100 ms overhead budget). Cost 0.0032 USD for 100 calls (0.0000325 per call, about 700 input tokens).
- **THX-01:** it sent 1 of the 60 tier-0 requests to tier 0. `cheap_model_ok` sits around 0.59 (p50), under `tau_ok` 0.7, so the low tier almost never fires; on 40 rows no rule fired and the safe tier decided. Where its own answers decided (60 rows): 63%. Whether this is the model or the placeholder thresholds needs tuning on a separate set, never this one. Decision latency p50 4.1 s on the owner's CPU, as in R5.
- **Borderline rows (5):** every router got 2 right. **Rows changed by the owner:** none (approved as is), so that slice is empty.
- **Agreement (tier 0/1):** Jev with THX-01 65/100, with `rules` 69/100, with `rule_based` 41/100; `rules` with THX-01 96/100.

**Limits:** SYNTHETIC requests, not real traffic (lengths, topics and phrasing differ from the dataset); one rater, with no agreement measure; n = 100, so per-language and per-category numbers rest on 15 or fewer rows each; tiers 0/1 only (router tiers ≥ 1 count as 1); accuracy against labels, not answer quality. **A first signal, not proof.** This set is now an evaluation set: no threshold may be tuned on it.

**Next:** a second rater on the same 100, labelling without seeing these labels (free; gives the agreement between raters); Q-55, so Jev can be measured on the dev slice; THX-01's mapping thresholds studied on separate data.

## Jev on the real dev slice (2026-11-03)

Run, results and limits: [jev_dev_slice/README.md](jev_dev_slice/README.md). In short: a cost simulation on the 150 records; Jev adds about 2% over the rules, not significant on this sample; quality not proven (A-126).

## Open

- **A full-data tier per request** (for `version.py` on the full replay) needs THX-01 run on full-data text. That is local and allowed, but is several hours on CPU. Not in the sprint.
- **Jev's shadow answers on dataset text** wait for Q-55. The synthetic check above (Jev 72% vs rules 43% and THX-01 41% against owner labels) is the case for asking.
- **A-97:** the tier-0 safe tier vs tier 1 comparison waits for labels.
- **A-103:** escalation on low confidence needs a chain of two local backends; Mizan is skipped (A-117).
