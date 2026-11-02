## Parallel work: progress entries and ADR drafts

- Record progress as a **new file** in `docs/project/progress/` (`YYYY-MM-DD-<slug>.md`, first line `## Title (YYYY-MM-DD)`); **never edit someone else's entry**; run `python scripts/progress_index.py`. `progress.md` is only an index plus the lead's Current status.
- A new ADR is a **draft**, `docs/adr/draft-<slug>.md`, cited as `ADR-XXXX (<slug>)`. Do not choose a number: the merger runs `python scripts/adr_finalize.py` (and `progress_index.py`) before merging. See `docs/adr/README.md` and `docs/guides/team_workflow.md`.

## Agent skills

### Issue tracker

Issues and specs live as Markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Use the single-context layout. See `docs/agents/domain.md`. Follow its instructions before exploring domain concepts or architecture.

## Efficient repository work

- Start with the user's specific task. Inspect only the files needed to understand and complete it.
- Do not recursively scan the repository by default. Expand the search only when the task requires it.
- Avoid reading lockfiles, generated files, logs, datasets, build artifacts, and unrelated documentation unless directly relevant.
- For architecture or domain work, read the relevant glossary and ADRs as described in `docs/agents/domain.md`. Do not read unrelated ADRs.
- If the user provides an issue or spec path, read that file first and follow the repository's issue-tracker conventions.
- Before modifying code, identify the relevant implementation and tests. Prefer targeted inspection and targeted tests over broad commands.
- Do not modify unrelated files, change dependencies, or perform destructive operations unless the task requires it. Ask when the intended scope is unclear.
- Keep plans and final reports concise. Distinguish confirmed facts from assumptions, and report what was changed and which tests were actually run.
- For broad or ambiguous tasks, clarify the scope or propose a short plan before exploring widely.
