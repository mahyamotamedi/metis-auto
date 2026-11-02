# Decision records (ADRs)

One file per decision: context, alternatives, decision, consequences. The table of all
ADRs is in [`../README.md`](../README.md#decision-records-adr); it is generated.

## Numbering: drafts until merge

Two branches that both pick "the next number" collide (this happened with 0031). So
**nobody picks a number on a branch.** A new ADR is a **draft**:

| What | Convention |
|---|---|
| File | `docs/adr/draft-<slug>.md` (`<slug>`: lower-case letters, digits and hyphens) |
| Title line | `# ADR-XXXX (<slug>): Title` |
| Status line | `- Status: ...` among the first lines (the generated table shows it) |
| References | write `ADR-XXXX (<slug>)` in prose, and link to `draft-<slug>.md` |

Use the same `<slug>` everywhere (code comments, docs, progress entries, other ADRs),
so that one command can find all references.

## The merger finalizes

Before merging a branch that adds drafts, the person merging runs:

```bash
python scripts/adr_finalize.py --dry-run   # what would happen
python scripts/adr_finalize.py             # do it
python scripts/adr_finalize.py --check     # must print OK
```

The script reads the highest number on `origin/main` (else the local `main`, else the
working tree; the larger of that and the tree counts), renames each draft to the next
free number in alphabetical order of slug, replaces every `ADR-XXXX (<slug>)` and every
link to `draft-<slug>.md` across the repository's text files, and rebuilds the ADR
table in `docs/README.md` (between the `adr-table` marker comments) from each ADR's
title line and Status line. Commit the result with the merge.

`--check` fails while a draft or an unresolved `ADR-XXXX (<slug>)` remains, when a
number is used twice, when a file's number differs from its title line, and when the
README table is stale. Gaps in the numbers are only reported.

Existing ADRs keep their numbers: do not renumber an ADR that is already on `main`.
Never write a number into a draft's title or text by hand.

## Status words

`decided`, `provisional`, `proposed`, `open`, `amended` or `superseded`, with the date
and who decided, as in the existing records. Amend a decision by adding an
"Amendment" section to the same ADR.

See also [`../guides/team_workflow.md`](../guides/team_workflow.md).
