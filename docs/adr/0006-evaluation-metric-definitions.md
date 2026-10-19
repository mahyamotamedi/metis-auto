# ADR-0006: Evaluation metric definitions — making the brief's four metrics defensible

- Status: **decided**. Thresholds are **provisional**: δ (Q-13) and the overhead budget (Q-14) were answered 2026-10-14, to be revisited with the full dataset and real latencies.
- Date: 2026-10-14
- Relates to: [requirements.md](../project/requirements.md) §4, context.md §7, C-07…C-09, ADR-0002

## Context
The brief (§4.1) defines four metrics: quality, semantic-cache hit rate, cost, and latency. Taken literally, each one can mislead:
- **Quality:** logged answers come from 18 heterogeneous labels, are not gold, and are paired heuristically (C-07).
- **Hit rate:** it says nothing about whether served answers were valid. No sample pair passed the strictest safe-candidate screen (F-7, C-09).
- **Cost:** it depends on unverified prices, tokenizer choice (Persian), and an unknown prompt composition.
- **Latency:** it cannot be observed from the data at all (F-9, C-08).

Experiments must report the brief's metrics, but in a form that cannot be misread.

## Decision
1. **Quality** is reported as up to three separate numbers, never merged into one score:
   - **(a) Agreement with as-logged:** similarity to the logged answer, using a Persian-capable embedding model. It is named "agreement", not "quality".
   - **(b) Judge score:** LLM-as-a-judge or human, on a stratified subset, with the judge versioned and opt-in.
   - **(c) Non-inferiority vs. a baseline:** candidate ≥ baseline − δ, where δ is configuration.

   **Provisional thresholds (Q-13):**
   - mean judge score drops ≤ **3%** vs. baseline overall;
   - **and** no stratum (opaque category, language) drops > **5%**;
   - working interpretation: the percentages are relative to the baseline mean.

   **Primary signal:** LLM-as-a-judge, calibrated against a small human-rated set. Agreement (a) is secondary only.

   A strategy may be called "quality-preserving" only on (b) or (c), not on (a) alone.
2. **Cache hit rate** is always reported with **hit correctness**: a false-hit rate, or "unmeasured". It is broken down by key-composition variant and by eligibility exclusions. Offline sample results are "candidate hits", not hits.
3. **Cost** is reported as follows:
   - Every cost figure carries its token-count method (fidelity) and its price-table version.
   - Unknown prices yield "not computed".
   - Cost includes all attempts and all pipeline overhead (router, embeddings, judge, verifier).
   - It is compared against both baselines (ADR-0002).
4. **Latency** is split into:
   - **(a) pipeline overhead**, measured offline, p50/p95, with the hardware recorded;
   - **(b) model latency**, live or recorded only;
   - **(c) end-to-end time**, live or recorded only.

   Logged timestamp gaps are never used as latency. When (b) and (c) are unavailable, results say "unmeasured".

   **Provisional budget (Q-14):** overhead (a) ≤ **100 ms at p95**, excluding model response time. Working interpretation: (a) covers features, embedding, cache lookup, routing, and context building. The budget is configuration; it is revisited once real model latencies exist.
5. Every metric is reported overall and per stratum (FR-EVAL-06), with sample sizes and, where feasible, uncertainty intervals.

## Alternatives considered
- **Use the brief's metrics literally.** Rejected: the problems listed in Context would be reported as results.
- **A single composite score** (e.g. cost-weighted quality). Rejected for now: it hides trade-offs, and its weights would be arbitrary before δ and the latency budget are set. A composite may be added later as a derived view.
- **Replace similarity-to-logged entirely with a judge.** Rejected: judges cost money (ADR-0003) and have their own bias. Agreement is free and still useful as a drift signal.

## Consequences
- The Stage 4 evaluation-result contract needs:
  - separate fields for agreement, judge score, and non-inferiority;
  - hit correctness;
  - method and fidelity on costs;
  - explicit "unmeasured" and "not computed" states.
- Stage 8 experiment plans must name which quality signal (a/b/c) each claim rests on.
- A Persian-capable embedding model must be chosen and verified before agreement numbers mean anything (Stage 8).
