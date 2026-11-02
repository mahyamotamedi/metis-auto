## Progress entries as files, ADRs as drafts (2026-11-02)

Under the owner's task. Status: **built and tested; awaiting review; nothing committed**. Guide: [team_workflow.md](../../guides/team_workflow.md); ADR convention: [adr/README.md](../../adr/README.md).

- **Why:** `progress.md` (1,033 lines) was appended to by every branch and conflicted on almost every merge; two branches also both created ADR-0031.
- **Progress:** each of the 21 sections of `progress.md` moved into its own file in `docs/project/progress/` (`YYYY-MM-DD-<slug>.md`). Content is unchanged; checked line by line (765 of 765 non-blank lines identical; the only changes are 107 link targets, which had to gain one `../` because the files moved one folder deeper). `progress.md` is now a short page: the lead-owned Current status and a generated index (`scripts/progress_index.py`, `--check`). `.gitattributes` keeps `merge=union` for it, now with a comment. Rule: add a new file, never edit someone else's entry.
- **ADRs:** a new ADR on a branch is `docs/adr/draft-<slug>.md`, cited as `ADR-XXXX (<slug>)`. `scripts/adr_finalize.py` (the merger runs it) numbers the drafts after the highest on `origin/main`, rewrites the references and rebuilds the ADR table in `docs/README.md` from each ADR's title and Status line (the hand-written descriptions of the old table are gone; the generated table is complete and no longer breaks across a blank line).
- **Existing ADRs 0001 to 0034:** contiguous, no duplicates, no gaps, every file's number matches its title line; nothing renumbered.
- **Rules updated:** `CLAUDE.md`, `AGENTS.md`, `docs/README.md`, the guides, the master-prompt note, and references that meant a specific entry now link to it.
- **Tests:** `tests/architecture/test_docs_conventions.py` (the index matches the folder, no duplicate ADR numbers, the README table matches the files, and both scripts on synthetic trees including renumbering from a real `main`).
- **Not changed:** `module_reference.md` and the assumptions register are still appended to by hand and can still conflict; keep both sides and run the tests.
