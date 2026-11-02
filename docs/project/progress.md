# Project Progress

Single source of truth for stage status across sessions. Stage definitions: master prompt §5 ([`metis_claude_code_master_prompt.md`](../../metis_claude_code_master_prompt.md)). Decision records: [`docs/adr/`](../adr/).

**How this page works.** It has two parts: **Current status** (written by the lead only) and an **index of entries**, which a script generates. Each piece of work is its own file in [`progress/`](progress/), named `YYYY-MM-DD-<slug>.md` and starting with a `## Title (YYYY-MM-DD)` heading.

- To record work: **add a new file** in `docs/project/progress/`. **Never edit someone else's entry.** Then run `python scripts/progress_index.py` and commit the updated index.
- Before merging a branch, the merger runs `python scripts/progress_index.py` again (`--check` fails if the index is stale). Git merges this page line by line (`merge=union` in `.gitattributes`), so two branches adding entries no longer conflict.
- Entries of the same day sort by file name.

## Current status (lead-owned)

| Stage | Title | Status | Exit criteria met? |
|---|---|---|---|
| 0 | Orientation & inventory | done (answers recorded) | Yes |
| 1 | Requirements, quality attributes, scope | done | Yes |
| 2 | Repository structure proposal | done | Yes |
| 3 | Architecture & system design | done (approved by the instruction to continue, 2026-10-17) | Yes |
| 4 | Internal contracts | done (approved by the instruction to continue, 2026-10-18) | Yes (the configuration diagram was labelled in Stage 6) |
| 5 | Skeletons & wiring | done (approved by the instruction to continue with Stage 6, 2026-10-18) | Yes |
| 6 | Configuration, environment, containers | done (approved by the instruction to continue with Stage 7, 2026-10-18) | Yes: native and container |
| 7 | Token & cost accounting utility (+ brief §12 items) | done (approved by the instruction to continue with Stage 8, 2026-10-18) | Yes |
| 7.5 | Live adapter and wrapper check (**new**, small; [brief](live_testing_and_demo_brief.md) §12) | done (approved by the instruction to continue with Stage 8, 2026-10-18) | Yes |
| 8 | Experiment framework & exact-cache baseline (+ sample loader, pairing, case builder pulled forward from Stage 9) | **awaiting review** (2026-10-18; follow-up 2026-10-19: Q-37, Q-38) | **Yes** (see below) |
| Demo | Demo milestone (**new**, after Stage 8; brief §12; includes the required teammate quickstart): **A** backend, **B** UI | **A: awaiting review** (2026-10-19); **B: awaiting review** (2026-10-19) | A: **yes**; B: **yes** (see below; live smoke test run 2026-10-19) |
| 9 | Data layer plan | not started | — |
| 10 | Architecture review & roadmap | not started | — |

**Planned steps added 2026-10-18 from the [owner's brief](live_testing_and_demo_brief.md) §12** (not started; scope as the brief states it):
- **Stage 7 additions:** ~~tokenizers for the six catalogue models; price schema with cached input, cache writes, and context-length tiers; the premium-baseline estimate (brief §5); `scripts/measure_overhead.py` (brief §11)~~ **done in Stage 7**, plus the savings decomposition (brief §6) as pure functions, ahead of the Demo milestone.
- **Stage 7.5 (new, small):** one live OpenAI-compatible adapter (base URL per family; SDK auto-retries off; normalised errors; provider-reported usage, finish reason, cached tokens, and model); the tiny live wrapper check (brief §3), results recorded with dates; a `scripts/chat.py` CLI. Prerequisites: TODO-10 (context windows), the spend-guard TODO for uncomputable actual costs, Q-29.
- **Stage 8 additions:** ~~the sample loader, pairing heuristic, and replay-case builder pulled forward from Stage 9; the sticky-routing experiment plan (brief §7)~~ **done in Stage 8.**
- **Demo milestone (after Stage 8):** rule-based plus sticky routing v1; the LLMLingua-2 strategy as a labelled experimental toggle (heavy dependencies in an optional extra); demo cache scope and seed; showing the savings decomposition (computed since Stage 7, `AccountingService.decompose`); a Streamlit UI as a thin wrapper over `wiring` (brief §10).
  - **Required deliverable (owner, 2026-10-18; brief §10, §12 amended):** [`docs/guides/demo_quickstart.md`](../guides/demo_quickstart.md), the teammate quickstart. Drafted on 2026-10-18 for everything that exists today (setup, fake and real-model modes, `.env` and the key, `config/local.toml`, the budget and the per-computer ledger, `chat.py` and the cost panel, troubleshooting). **To complete in the Demo milestone:** the UI start command, its toggles, and a screenshot (§7), and the compression row. The milestone is not done until the guide is followed end to end on a fresh clone.
- **Stage 10 roadmap:** the Gemini adapter; a tokenizer-fetch step in the `dev` Docker image (Stage 7).

## Entries, newest first

<!-- progress-index:start -->
- 2026-11-02: [Sprint Day 1, Pipeline C: replay scope, split and four baselines](progress/2026-11-02-sprint-day-1-pipeline-c-replay-scope-split-baselines.md)
- 2026-11-02: [Sprint Day 1, Pipeline C: demo shell, lever view model](progress/2026-11-02-sprint-day-1-pipeline-c-demo-shell-lever-view.md)
- 2026-11-02: [Sprint Day 1, Pipeline C: CI on GitHub Actions](progress/2026-11-02-sprint-day-1-pipeline-c-ci-github-actions.md)
- 2026-11-02: [Sprint Day 1, Pipeline B: comparison, cache guard, Postgres event sink](progress/2026-11-02-sprint-day-1-pipeline-b-comparison-cache-guard-postgres.md)
- 2026-11-02: [Sharing the golden answers](progress/2026-11-02-sharing-the-golden-answers.md)
- 2026-11-02: [Progress entries as files, ADRs as drafts](progress/2026-11-02-progress-entries-and-adr-drafts.md)
- 2026-11-02: [Popular-question cache, R-A1 phase 2: full-data run](progress/2026-11-02-popular-question-cache-r-a1-phase-2.md)
- 2026-11-02: [Popular-question cache, R-A1 phase 1](progress/2026-11-02-popular-question-cache-r-a1-phase-1.md)
- 2026-11-02: [Lever base: StepVersion, combine, LeverResult, Manifest](progress/2026-11-02-lever-base-stepversion-combine-leverresult-manifest.md)
- 2026-11-01: [Session and configuration analysis, golden-set proposal](progress/2026-11-01-session-and-configuration-analysis-golden-set-proposal.md)
- 2026-11-01: [PostgreSQL foundation and evaluation dataset golden-v1](progress/2026-11-01-postgresql-foundation-and-evaluation-dataset-golden-v1.md)
- 2026-11-01: [golden-v2: the 300 records without attachment images](progress/2026-11-01-golden-v2-the-300-records-without-attachment-images.md)
- 2026-11-01: [Golden answers from gpt-5.5 for golden-v2](progress/2026-11-01-golden-answers-from-gpt-5-5-for-golden-v2.md)
- 2026-10-30: [Research note — evaluation framework](progress/2026-10-30-research-note-evaluation-framework.md)
- 2026-10-30: [Full-dataset EDA](progress/2026-10-30-full-dataset-eda.md)
- 2026-10-19: [Demo milestone, part B — the UI ("the face")](progress/2026-10-19-demo-milestone-part-b-the-ui-the-face.md)
- 2026-10-19: [Demo milestone, part A — the backend ("the brain")](progress/2026-10-19-demo-milestone-part-a-the-backend-the-brain.md)
- 2026-10-18: [Stage 8 — Experiment framework and first cache baseline](progress/2026-10-18-stage-8-experiment-framework-and-first-cache-baseline.md)
- 2026-10-18: [Stage 7.5 — Live adapter and wrapper check](progress/2026-10-18-stage-7-5-live-adapter-and-wrapper-check.md)
- 2026-10-18: [Stage 7 — Token & cost accounting](progress/2026-10-18-stage-7-0-token-and-cost-accounting.md)
- 2026-10-18: [Stage 6 — Configuration, environment, containers](progress/2026-10-18-stage-6-configuration-environment-containers.md)
- 2026-10-18: [Stage 5 — Skeletons & wiring](progress/2026-10-18-stage-5-skeletons-and-wiring.md)
- 2026-10-17: [Stage 4 — Internal contracts](progress/2026-10-17-stage-4-internal-contracts.md)
- 2026-10-14: [Stage 3 — Architecture & system design](progress/2026-10-14-stage-3-architecture-and-system-design.md)
- 2026-10-14: [Stage 2 — Repository structure](progress/2026-10-14-stage-2-repository-structure.md)
- 2026-10-14: [Stage 1 — Requirements, quality attributes, scope](progress/2026-10-14-stage-1-requirements-quality-attributes-scope.md)
- 2026-10-14: [Stage 0 — Orientation & inventory](progress/2026-10-14-stage-0-orientation-and-inventory.md)
<!-- progress-index:end -->
