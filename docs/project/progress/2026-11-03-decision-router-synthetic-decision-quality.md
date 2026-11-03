## Decision router: first decision-quality check on SYNTHETIC requests (2026-11-03)

Parham, after #36. A first measurement of how well the routers pick a tier, against labels, with text that may go to Jev today. **Done; awaiting review.** Traces: H-1, FR-ROUTE-03, FR-EVAL-04, QA-PRIV; [ADR-0047](../../adr/0047-system-one-decision-router.md); [exp-route-013](../../../experiments/routing/exp-route-013-decision-router/README.md#synthetic-decision-quality-check-jev-synth-v1-2026-11-03).

**Set (jev-synth-v1).**
- 100 SYNTHETIC requests written for this check, never copied or paraphrased from the dataset: 70 Persian, 15 English, 15 mixed, over nine kinds of request (greetings to multi-step reasoning).
- An expected tier (0 or 1) and a reason for each. The owner reviewed them and approved them as is (60 / 40; 5 borderline).
- Frozen with sha256: `experiments/routing/exp-route-013-decision-router/synthetic_v1/labels_frozen.{csv,json}`.

**Runner.** `synthetic_v1/run.py` and `run.ps1`, through the real pipeline with the fake answering client:
- the routers compared are the router's rules path, the plain rule-based policy, THX-01 (local) and Jev (Metis, live);
- the models are asked on every row with the gate off and R8's offline settings; an "as configured" view adds the fast gate;
- the `[SYNTHETIC]` marker is removed before routing for every router: it made the language detector call 21 of 70 Persian requests "mixed".

**Live spend.** Jev, 100 calls: 0.0032 USD, charged to `data/spend/ledger.jsonl` by the cascade's spend guard under a 0.02 USD run cap. The plan was printed first and live was switched off afterwards.

**Results** (owner's run; report in `reports/routing/exp-route-013/synthetic_v1/`):
- **Tier accuracy:** Jev 72%, plain rule-based 59%, rules 43%, THX-01 41%. On this set, always-tier-0 would score 60% and always-tier-1 40%.
- **Jev's errors** are on the cost side: 1 of 40 hard requests went to tier 0, and 27 easy ones went to tier 1. The plain rule-based policy sent 35 hard requests to tier 0.
- **By language,** Jev scored 69% on Persian, 87% on English and 73% on mixed.
- **THX-01** almost never chose tier 0 (`cheap_model_ok` p50 0.59 < `tau_ok` 0.7).
- **Latency:** Jev p50 0.97 s; THX-01 p50 4.1 s.

**Limits.** Synthetic requests, one rater, n = 100: a first signal, not proof. The set is now an evaluation set, so no threshold may be tuned on it.

**Also recorded.**
- TODO-17 gains the owner's probe of 2026-11-03: `gpt-4.1-nano` is deprecated (OpenAI's error passed through), `mimo-v2.5` is "Unsupported model", and Metis's sample URL `/v1/chat/completions` returns 404.
- `jev_model_note.md`: Persian support (first signal) and measured latency.
- Router quickstart: §9 no longer lists gpt-4.1-nano, and §11 gives the synthetic check's command.
- The exp-route-013 README's title said EXP-ROUTE-012; it is fixed.

**Next.**
- A second rater on the same 100.
- Q-55, so Jev can be measured on the dev slice.
- THX-01's mapping thresholds, studied on separate data.
