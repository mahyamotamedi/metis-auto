## Parallel work: progress entries and ADR drafts

- Record progress as a **new file** in `docs/project/progress/` (`YYYY-MM-DD-<slug>.md`, first line `## Title (YYYY-MM-DD)`); **never edit someone else's entry**; run `python scripts/progress_index.py`. `progress.md` is only an index plus the lead's Current status.
- A new ADR is a **draft**, `docs/adr/draft-<slug>.md`, cited as `ADR-XXXX (<slug>)`. Do not choose a number: the merger runs `python scripts/adr_finalize.py` (and `progress_index.py`) before merging. See `docs/adr/README.md` and `docs/guides/team_workflow.md`.

## Agent skills

### Issue tracker

Issues and specs live as Markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Use the single-context layout. See `docs/agents/domain.md`.
