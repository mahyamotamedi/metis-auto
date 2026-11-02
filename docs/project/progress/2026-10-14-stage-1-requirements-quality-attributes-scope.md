## Stage 1 — Requirements, quality attributes, scope (2026-10-14)

**Outputs:**
- [requirements.md](../requirements.md):
  - goals G-1…G-7
  - functional requirements in 14 areas (`FR-REQ`, `FEAT`, `ROUTE`, `XCACHE`, `SCACHE`, `CTX`, `CASC`, `FAIL`, `ACCT`, `OBS`, `EVAL`, `DATA`, `API`, `FIN`)
  - 8 quality attributes with measurement methods
  - non-goals NG-01…NG-13
  - brief→data-support map BR-01…BR-18
  - the traceability rule and matrix
- [ADR-0005](../../adr/0005-current-phase-scope.md): current-phase scope. Offline foundation, an in-process API, and brief Action 3 deferred (its data enablers stay in scope). **Provisional** pending Q-17.
- [ADR-0006](../../adr/0006-evaluation-metric-definitions.md): the brief's four metrics made defensible:
  - quality is split into agreement, judge, and non-inferiority;
  - hit rate is always paired with hit correctness;
  - cost carries its fidelity and price version;
  - latency is split into overhead (offline) and model/end-to-end (live only).
- [`GLOSSARY.md`](../../../GLOSSARY.md): the domain terms settled in this stage.
- Register: assumptions A-18…A-22 and questions Q-13…Q-17.
- [`CLAUDE.md`](../../../CLAUDE.md) and [context.md](../context.md): pointers added.

**Open questions raised:**
- Q-13 (quality margin δ)
- Q-14 (latency budget)
- Q-15 (future gateway API compatibility)
- Q-16 (cache sharing scope)
- Q-17 (confirm the Action 3 deferral)

None of these blocks Stage 2.

**Exit criteria:** "Every later design element can be traced to a requirement or an experiment." **Met, pending review.** Every requirement has an ID and a source, the traceability rule is in requirements.md §7, and hypotheses H-1…H-7 cover the experimental elements (experiment IDs come in Stage 8).

**Stage 1 status:** awaiting your approval to start Stage 2.

### Stage 1 follow-up — answers to Q-13…Q-17 (2026-10-14)

| Question | Status | Answer |
|---|---|---|
| Q-17 | answered | Action 3 deferred. The event design must still carry everything a dashboard needs. |
| Q-16 | partly answered | Serving default `session`; scope configurable (`session` / `user` / `global`); cross-session and cross-user candidates measured separately; final policy open. |
| Q-13 | answered (provisional) | Judge score drops ≤ 3% overall and ≤ 5% per stratum. LLM judge calibrated against human ratings is primary; agreement is secondary. |
| Q-14 | answered (provisional) | Overhead ≤ 100 ms at p95. |
| Q-15 | open | Separate external-API adapter layer; provisional default OpenAI-compatible chat-completions style. |

**Decision records:**
- ADR-0005 is now decided.
- ADR-0006 gains the provisional thresholds.
- New: [ADR-0007](../../adr/0007-cache-sharing-scope.md) (cache sharing scope).

**Interpretations to confirm:**
- In Q-13, the percentages are relative to the baseline mean.
- In Q-14, the overhead covers all of Metis's pre-model work (features, embeddings, cache lookup, routing, context building).

### Stage 1 follow-up — sample EDA is exploratory (2026-10-14)

**Decision:** [ADR-0008](../../adr/0008-sample-eda-is-exploratory.md).
- Sample-EDA numbers are provisional signals.
- The EDA helpers are reference-only and must not be reused.
- No sample-shaped contracts.
- The full-dataset EDA gets its own home.

**Updated:**
- `CLAUDE.md`: new durable rule.
- context.md: §4 and §5.1 reframed as sample signals; helper row changed.
- requirements.md: source note; BR-01; FR-REQ-03 and FR-DATA-03 changed; new FR-DATA-06…08; the §6 caveat.
- Register: A-01 revised, A-08 split into principle and share, new A-23 and A-24.
- Sample EDA marked preliminary: banners on `docs/sample_eda/*.md`, and READMEs in `experiments/sample_eda/` and `reports/sample_eda/`. No content changed.

**Carried into later stages:**
- **Stage 2:** propose a dedicated full-dataset EDA home (notebooks, analysis code, reports, outputs), separate from the sample EDA. Add a dependency rule that nothing outside the sample EDA imports from `experiments/sample_eda/`.
- **Stage 9:** the onboarding checklist starts with a proper full EDA that re-checks every sample signal (`F-n`, the master prompt's EDA list) and Q-04, Q-06, and Q-09.

**Stage 1 status:** approved (the instruction to continue with Stage 2, 2026-10-14). Stage 2 started 2026-10-14.
