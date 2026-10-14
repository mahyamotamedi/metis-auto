# Project Progress

Single source of truth for stage status across sessions. Stage definitions: master prompt §5 ([`metis_claude_code_master_prompt.md`](../../metis_claude_code_master_prompt.md)). Decision records: [`docs/adr/`](../adr/).

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

**Tooling proposal:** superseded by [ADR-0001](../adr/0001-python-tooling.md). See the follow-up below.

**Exit criteria:** "I can read one document and understand the problem, the data's real shape and limits, and what is unknown." That document is [context.md](context.md). Met, pending review.

### Stage 0 follow-up — answers to open questions (2026-10-14)

**Recorded:** answers in the [register](assumptions_and_questions.md).

| Question | Status |
|---|---|
| Q-01 | answered |
| Q-02 | answered |
| Q-03 | answered |
| Q-07 | answered |
| Q-08 | partly answered |
| Q-05 | open |
| Q-10 | open |
| Q-11 | open |
| Q-12 | new, open |
| Q-04, Q-06, Q-09 | open; grouped as "questions for the data owner", with unverified working assumptions A-06, A-14, A-15, A-16 |

**Decision records:**
- [ADR-0001](../adr/0001-python-tooling.md) — Python tooling: 3.13, venv + pip, pyproject, pip-tools lock (provisional), ruff, pytest.
- [ADR-0002](../adr/0002-configurable-baselines.md) — configurable premium placeholder plus mandatory as-logged baseline.
- [ADR-0003](../adr/0003-offline-by-default-model-calls.md) — offline by default; live calls opt-in with a spending cap; `.env.example` key guidance in Stage 6.
- [ADR-0004](../adr/0004-repository-hygiene.md) — repository hygiene.

**Repo changes:**
- `.gitignore`: removed the `AGENTS.md` and `docs/agents/` lines.
- `.idea/` and `.vscode/` untracked (`git rm --cached`; local files kept).
- Brief copied to `docs/brief/project-draft.pdf`.
- Master prompt renamed to `metis_claude_code_master_prompt.md`.

**Carried into later stages:**
- Stage 2: proposed home for `docs/agents/` content and the master prompt.
- Stage 6: `.env.example` with commented provider-key entries and insertion instructions; spending-cap config.
- Stage 5/6: create `pyproject.toml` and the lockfiles. TODO-08: install a standalone Python 3.13.

**Stage 0 status:** awaiting your approval to start Stage 1.
