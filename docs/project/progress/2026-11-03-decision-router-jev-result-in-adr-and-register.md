## Decision router: the Jev synthetic result recorded in ADR-0047 and the register (2026-11-03)

Parham, branch `route-decision-router-jev` after #40. A records-only change; no code. **Done; awaiting review.**

The synthetic decision-quality check (jev-synth-v1; run, results and limits in [exp-route-013](../../../experiments/routing/exp-route-013-decision-router/README.md#synthetic-decision-quality-check-jev-synth-v1-2026-11-03), merged in #40) is now also in:
- **[ADR-0047](../../adr/0047-system-one-decision-router.md)**, "Results of the owner's runs":
  - tier accuracy: Jev 72%, plain rule-based 59%, rules 43%, THX-01 41% (always-tier-0 scores 60%);
  - by language: Jev 69% Persian, 87% English, 73% mixed;
  - Jev under-routed 1 of 40 hard requests; 0.0032 USD; p50 0.97 s, so never inline;
  - limits: synthetic requests, one rater, n = 100. Serving is unchanged.
- **The register, A-125.** The same finding, next to A-89 (Jev for shadow runs and labelling).

The Jev note (`docs/references/jev_model_note.md`) already holds the Persian first signal and the measured latency (#40). Real-traffic quality stays unproven until Q-55 and labels.
