# ADR-0008: The sample EDA is exploratory — provisional signals only, helpers not reusable

- Status: **decided**
- Date: 2026-10-14
- Supersedes: the framing of the master prompt's §2 "Key EDA facts you must carry forward", and the "established facts" framing in [context.md §5.1](../project/context.md). The master prompt file itself is not edited.
- Relates to: A-01, A-08, FR-DATA-03, FR-DATA-06, FR-REQ-03

## Context
The sample EDA (`experiments/sample_eda/`, `docs/sample_eda/`, `reports/sample_eda/`) ran on a 100-session sample to judge whether the project is worth doing. Stage 0 and Stage 1 docs called its numbers "established facts" and used them as sources for requirements. The project owner has clarified three things:
- the sample is small and may not be representative;
- the helper functions are deliberately simplified and unreliable;
- the full dataset may differ in schema and quality.

## Decision
1. **EDA results are provisional signals, not facts.** Every sample-EDA number and finding is a signal to re-verify on the full dataset. That includes the master prompt's "Key EDA facts" and context.md's `F-n` items. Design decisions may be *informed* by these signals but must not *depend on their exact values*. A design that would break if a sample number changed must be made configurable or re-derived after the full EDA.
2. **The EDA helpers are reference-only.** `experiments/sample_eda/eda_helpers.py` must not be imported, reused, copied, or built on by any domain, application, evaluation, or experiment code. It may be read only to see which kinds of analysis were tried. Any analysis logic the system needs (language detection, normalisation, pairing, near-duplicate detection, size estimates) is re-implemented properly, with tests. The EDA's existing tests (`tests/test_sample_eda_helpers.py`) stay; they cover EDA code only.
3. **No sample-shaped contracts.** Contracts, data interfaces, and synthetic fixtures must not be shaped around sample-specific quirks. Examples: the 4,019-char plateau, the exact field set and nesting, `default`/`workflow` labels, bot-side `input.items`, role names, and category count. They model the domain generically, with sample quirks handled in a sample-specific loader or adapter.
4. **A dedicated full-dataset EDA home.** The full-dataset EDA (notebooks, analysis code, reports, outputs) gets its own place, separate from the sample EDA. The location is proposed in Stage 2. The sample EDA is kept unchanged in content and marked **preliminary / sample-only**.
5. **The full EDA comes first in onboarding.** The Stage 9 full-dataset onboarding checklist begins with a proper full EDA. That EDA re-checks every sample signal (`F-n`, the master prompt's EDA list) and the data-owner questions (Q-04, Q-06, Q-09), using the re-implemented, tested analysis code from point 2.

## Alternatives considered
- **Keep treating sample EDA numbers as facts for this sample.** Rejected: even scoped "to this sample", they were being used as requirement sources and design constraints.
- **Promote and harden the existing helpers.** Rejected by the owner: they are simplified on purpose. Re-implementing against requirements with tests is cleaner than auditing them.
- **Archive or delete the sample EDA.** Rejected: it is still a useful record of what was tried and why the project was started.

## Consequences
- context.md §4–§5 are reframed as sample signals. Requirement sources that cite `F-n` are read as "informed by", not "established by".
- A-01 changes from "schema is representative" to "**not** assumed representative".
- A-08 (Persian-aware processing) stays as a design principle, but the Persian *share* is a signal.
- Stage 2 must place the full-dataset EDA and say how the sample EDA is marked. It also enforces point 2 through its dependency rules: no code outside the sample EDA may import from `experiments/sample_eda/`.
- Stage 9's checklist starts with the full EDA. Thresholds and design values tuned to sample numbers are re-derived afterwards.
