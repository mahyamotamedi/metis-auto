# Project Progress

Single source of truth for stage status across sessions. Stage definitions: master prompt §5 (`metis_claude_code_master_prompt_1.md`, currently untracked; see [Q-02](assumptions_and_questions.md#open-questions)).

| Stage | Title | Status | Exit criteria met? |
|---|---|---|---|
| 0 | Orientation & inventory | **awaiting review** | Yes (pending your confirmation) |
| 1 | Requirements, quality attributes, scope | not started | — |
| 2 | Repository structure proposal | not started | — |
| 3 | Architecture & system design | not started | — |
| 4 | Internal contracts | not started | — |
| 5 | Skeletons & wiring | not started | — |
| 6 | Configuration, environment, containers | not started | — |
| 7 | Token & cost accounting utility | not started | — |
| 8 | Experiment framework & exact-cache baseline | not started | — |
| 9 | Data layer plan | not started | — |
| 10 | Architecture review & roadmap | not started | — |

---

## Stage 0 — Orientation & inventory (2026-10-14)

**Outputs:**
- [context.md](context.md) — problem, brief summary, repository inventory, data shape, facts/hypotheses/unknowns, brief↔data conflicts, evaluation weaknesses.
- [assumptions_and_questions.md](assumptions_and_questions.md) — the register.
- this file.
- [`CLAUDE.md`](../../CLAUDE.md) — durable agent rules.

**Repo operations:**
- Local `main` was fast-forwarded to `origin/main` (`5a9421a`).
- `sys-des` was rebased onto it, because it had been cut from a stale `main` without the EDA.
- Tests: 3/3 pass.
- Data hash is unchanged.

**Open questions raised:** Q-01 … Q-11. The most pressing are Q-03 (gitignore), Q-05 (premium baseline), Q-07 (tooling), and Q-08 (live calls).

**Tooling proposal (not applied):**
- Python 3.13, matching the EDA kernel and the local interpreter.
- A `pyproject.toml` with a `src/metis_auto` layout.
- black, already in use.
- ruff for linting (proposed).
- pytest as the runner, compatible with the existing unittest tests.
- mypy, optional and later.
- The dependency manager is open (Q-07).
- Contract-model library choice is deferred to Stage 4.

**Exit criteria:** "I can read one document and understand the problem, the data's real shape and limits, and what is unknown." That document is [context.md](context.md). Met, pending review.
