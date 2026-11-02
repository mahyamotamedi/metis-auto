## Sprint Day 3, Pipeline C: CI on pinned Ubuntu, macOS on main only, ADR-numbering check (2026-11-03)

Follow-up to E-1 (ADR-0035), branch `ci-pin-ubuntu-macos-main-adr-check` (from `main` at 0842ad1, #31). **Awaiting review.** Traceability: ADR-0035 Amendment 1, QA-TEST, QA-REPL.

- **Owner decisions (2026-11-03):** Linux pinned to `ubuntu-24.04` (the `ubuntu-latest` label migrates to Ubuntu 26 from 2026-10-19; the image must not change before the Day 4 demo); macOS moved to its own job `test-macos`, run only on pushes to `main` (long macOS queues, one main run on 2026-11-02 never picked up, 10x minutes on private repositories); a new Linux step "ADRs numbered and progress index current" runs `adr_finalize.py --check` and `progress_index.py --check` after the package install and before the tests (an unnumbered draft was merged once, PR #19).
- **Changed:** `.github/workflows/ci.yml`, `tests/architecture/test_ci_workflow.py` (8 tests, was 5), `docs/adr/0035-ci-github-actions.md` (Amendment 1 appended; the existing text unchanged), `docs/guides/team_workflow.md` (one line in §3).
- **TDD:** the new assertions failed against the old workflow (6 failed, 2 passed: the trigger and the offline/no-secrets tests already held), then passed after the workflow change.
- **Consequences:** PRs get Linux feedback only; a macOS regression is found on `main` after the merge and fixed forward. A branch with a `docs/adr/draft-*.md` or a stale progress index is red until the merger runs the scripts on it.
- **Not checked:** `actionlint` is not installed locally; the workflow was checked with `yaml.safe_load` and the tests only. The first runs on GitHub (a PR run: Linux only; the push to `main`: Linux and macOS) are the real check.
