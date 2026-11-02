# Team workflow: parallel branches without merge conflicts

Several people (and agents) work on branches at the same time. Two kinds of file used to
conflict on almost every merge, because every branch added to them: the progress log and
the ADR list. Both are now structured so that branches do not touch the same lines.

## 1. Progress: one file per entry

[`docs/project/progress.md`](../project/progress.md) holds only the lead's **Current
status** and a generated **index**. Each piece of work is its own file in
[`docs/project/progress/`](../project/progress/).

**To record work**

1. Create `docs/project/progress/YYYY-MM-DD-<slug>.md` (today's date; a short
   lower-case slug).
2. Start it with a heading `## Title (YYYY-MM-DD)`, then what you did, what you
   checked, what is open. The older entries are examples.
3. Run `python scripts/progress_index.py` and commit the entry together with the
   updated index.

**Rules**

- **Never edit someone else's entry.** If something in it is wrong or out of date, say
  so in your own new entry and link to the old one.
- Do not add entries to `progress.md` itself. Only the lead edits its Current status.
- Entries of the same day sort by file name.
- Relative links in an entry are relative to `docs/project/progress/`.

## 2. ADRs: drafts until merge

A new ADR on a branch is `docs/adr/draft-<slug>.md`, titled `# ADR-XXXX (<slug>): ...`,
and cited as `ADR-XXXX (<slug>)` everywhere. Never choose a number. The full convention
is in [`docs/adr/README.md`](../adr/README.md).

## 3. For the person merging a branch

Before merging, on the merged result:

```bash
python scripts/adr_finalize.py --dry-run     # drafts get numbers after the highest on main
python scripts/adr_finalize.py               # rename, update references, rebuild the table
python scripts/progress_index.py             # rebuild the progress index
python scripts/adr_finalize.py --check       # must print OK
python scripts/progress_index.py --check     # must print OK
.venv/bin/python -m pytest                   # includes the same checks
```

CI fails while a draft ADR is unnumbered; the merger runs adr_finalize.py on the branch,
then CI turns green.

Commit what the scripts changed with the merge. `progress.md` is merged line by line
(`merge=union` in `.gitattributes`), so two branches that both added index lines merge
without a conflict; the script then puts the index in order.

## 4. What can still conflict

Files that several branches append to by hand can still conflict, mainly
`docs/architecture/module_reference.md` (one row per module) and
`docs/project/assumptions_and_questions.md` (the register). They conflict only where two
branches added a line at the same place: keep both sides, then run the tests (the
module-reference test checks that every module has exactly one row).
