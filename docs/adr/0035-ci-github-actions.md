# ADR-0035: CI on GitHub Actions runs lint, format check and the offline test suite on Linux and macOS

- Status: **decided** for the sprint, 2026-11-02 (Pipeline C, task E-1). The action versions are **provisional** (re-check when they are bumped).
- Date: 2026-11-02
- Relates to: [ADR-0001](0001-python-tooling.md) (tooling, locks, release-age rule), [ADR-0003](0003-offline-by-default-model-calls.md) (offline by default), [ADR-0009](0009-repository-structure-and-dependency-rules.md) (import rules), [ADR-0027](0027-local-postgresql-foundation.md) (opt-in database tests); sprint plan E-1; QA-TEST, QA-REPL, QA-PRIV.

## Context
Until now every check ran only on a developer's machine. Five people and their agents now merge into `main` in parallel, and the layer rules (ADR-0009: `analysis` imports only `domain`, `ports`, `contracts`; libraries only in their adapters) are enforced by tests that someone has to remember to run. QA-TEST asks that "the CI-equivalent command runs with network disabled" and that all default tests pass offline. There was no CI.

The repository is on GitHub. The suite runs on macOS (two developers) and Linux (the Docker image). On Windows it has known failures (33 failed, 3 collection errors in the Day 1 baseline): the spend ledger locks with the POSIX-only `fcntl` (`adapters/system/ledger.py`), and some tests assume POSIX paths. The plan records these as a baseline and does not fix them in the sprint.

## Decision
1. **One workflow**, `.github/workflows/ci.yml`, on every `push` and `pull_request`.
2. **Matrix:** `ubuntu-latest` and `macos-latest`, Python 3.13 (ADR-0001), `fail-fast: false` so both results show. **Windows is excluded**, with the reason in a comment in the file.
3. **Steps are the documented local setup, in the same order:** `python -m venv .venv`; `.venv/bin/pip install --require-hashes -r requirements-db.lock`; `.venv/bin/pip install -e . --no-deps`; `.venv/bin/python scripts/fetch_tokenizer_assets.py`; `ruff check .`; `ruff format --check .`; `python -m pytest -q`. A failure on CI is reproducible with the same commands locally.
   - **Why the db lock, not the dev lock** (owner, 2026-11-02): `requirements-db.lock` is `requirements-dev.lock` (extras `dev`, `eda`, `live`, `tokenizers`, so `eda` needs no separate step) plus the `db` extra, with the shared pins equal (its header). `wiring/golden_answers.py` imports `sqlalchemy` at module level, so with the dev lock alone three test modules fail to import (`tests/integration/test_golden_answers_request.py`, `tests/unit/evaluation/test_evaluation_golden_answers.py`, `tests/unit/evaluation/test_evaluation_golden_review.py`; seen in a fresh clone 2026-11-02). Installing the db libraries starts no database.
   - **Why the tokenizer fetch** (owner, 2026-11-02): without the files, `tests/integration/test_live_probe.py::test_probe_plan_is_under_the_owners_limit` and `tests/integration/test_live_wiring.py::test_demo_live_check_plan_and_mocked_run` fail, because the chars/4 fallback puts a pre-call estimate just over the limit. The files are public (OpenAI blob storage, Hugging Face), about 10 MB, sha256-pinned in `config/reference/tokenizers.toml`, and need no key. This is setup; the test run itself stays offline.
4. **Offline and without secrets:** no `secrets.*`, no API key, no `--run-network`, no `--run-postgres`; `permissions: contents: read`. Opt-in tests stay skipped (`tests/conftest.py`). Other git-ignored data (`data/derived/`, compressor files) is absent on the runner, so tests that need it skip as they do in a fresh clone.
5. **Actions pinned by commit**, with the tag in a comment: `actions/checkout` v7.0.1 (`3d3c42e…`, released 2026-07-20) and `actions/setup-python` v7.0.0 (`5fda3b9…`, released 2026-07-20), checked on the GitHub API 2026-11-02. setup-python v7.1.0 (2026-10-22) is younger than ADR-0001's two-week release-age rule and is not used yet.
6. **The workflow itself is tested:** `tests/architecture/test_ci_workflow.py` checks the triggers, the matrix, the commands and their order, the absence of secrets and opt-in flags, read-only permissions, and commit pins. A change to the workflow that breaks these rules fails locally before it reaches GitHub.

## Alternatives considered
- **No CI, a local pre-merge checklist** (status quo): relies on memory; the import rules were already only as strong as the last person who ran them. Rejected.
- **A Windows runner too:** red from the first run because of the known `fcntl` and path failures, which the sprint does not fix. A permanently red job teaches people to ignore CI. Rejected for now; revisit when the ledger lock is portable.
- **Linux only:** cheaper, but two developers work on macOS, and macOS-only differences (file system case, paths) would go unseen. Rejected.
- **`actions/setup-python` with `cache: pip`:** faster, but the cache key and restore add moving parts, and a full hash-checked install is the reproducibility proof. Not now.
- **Tag pins (`@v7`) instead of commit pins:** simpler to read, but a tag can move. The Docker base image is already pinned by digest (local development guide §6); this follows the same rule.
- **The dev lock only, as first planned:** red on a fresh runner (above). Making `wiring/golden_answers.py` import `sqlalchemy` lazily would let the dev lock suffice, but it edits another owner's module; left to that owner. Then CI can go back to the dev lock.
- **Making the two budget tests skip without tokenizer files:** removes the download, but edits another owner's tests and hides a real difference between the approximation and the exact count. Not now.
- **Running the opt-in suites (network, Postgres) on CI:** needs secrets or a service container, and network tests can spend money (ADR-0018). Rejected for the default workflow.

## Consequences
- Guarding tests on every push: `tests/architecture/test_import_rules.py` (layer rules, QA-REPL), `test_live_sdk_imports.py`, `test_db_imports.py`, `test_compress_imports.py`, `test_ui_imports.py` (libraries only in their adapter or page), `test_module_reference.py`, `test_contracts_reference.py` (no `content` field in records, QA-PRIV), `test_docs_conventions.py`, and the new `test_ci_workflow.py`.
- A forbidden import (for example `domain` importing `adapters`) turns CI red. The proof for the slide (sprint plan E-1) is done by hand: a throwaway branch with such an import, a screenshot of the red run, then the branch is deleted.
- A green CI means "lint, format and the offline suite pass on a fresh clone". It does not cover Windows, the network or Postgres suites, or anything that needs local derived data.
- CI depends on the two tokenizer hosts being reachable; a download failure is red for a reason unrelated to the code. The sha256 pin makes a changed file fail loudly rather than silently.
- A local `.venv` with more locks installed than CI can hide import problems (this is how the `sqlalchemy` one went unseen). CI is the check for the clean install.
- Bumping an action means checking the new release's date against the release-age rule and replacing the commit pin; `test_ci_workflow.py` refuses a tag pin.
- Runner minutes and their cost were not checked (unverified); look at the repository's Actions usage after the first week.

## Amendment 1 (2026-11-03): pinned Ubuntu, macOS on main only, ADR-numbering check

- **Decided by:** the project owner, 2026-11-03 (Pipeline C, follow-up to E-1).
- **Reasons:**
  - macOS runners queue for a long time. On 2026-11-02 one run on `main` failed with "The job was not acquired by Runner of type hosted even after multiple attempts" (run 41519280471), and PRs waited 10+ minutes for macOS. macOS minutes also count 10x on private repositories.
  - GitHub annotated the runs: "The ubuntu-latest label will migrate to Ubuntu 26 beginning October 19, 2026" (actions/runner-images issue 14748). The final demo is on Day 4; the CI image must not change under us.
  - An unnumbered ADR draft was merged once (PR #19), because CI did not check the numbering.
- **Change** (`.github/workflows/ci.yml`):
  1. Linux is pinned: `ubuntu-24.04` instead of `ubuntu-latest`.
  2. Two jobs instead of a matrix over the OS: `test` (Linux) on every `push` and `pull_request`; `test-macos` (`macos-latest`) only on pushes to `main` (`if: github.event_name == 'push' && github.ref == 'refs/heads/main'`), with the same steps. Each keeps Python 3.13, `fail-fast: false` and the 20-minute timeout. A separate job was preferred over a matrix expression, for readability.
  3. A new step in the Linux job, after the package install and before the tests, "ADRs numbered and progress index current": `scripts/adr_finalize.py --check` and `scripts/progress_index.py --check` (the merger's checks, [team workflow](../guides/team_workflow.md) §3).
  4. Everything else is unchanged: pinned action SHAs, the db lock, the tokenizer fetch, the offline tests, read-only permissions. `tests/architecture/test_ci_workflow.py` asserts the new shape.
- **Consequences:**
  - PRs get Linux feedback only. A macOS regression is found after the merge, on `main`, and is fixed forward.
  - A branch that still holds a `docs/adr/draft-*.md` (or a stale progress index) is red until the merger runs `scripts/adr_finalize.py` (and `scripts/progress_index.py`) on it. Draft ADRs therefore block the merge until numbered; the red is expected while a branch is in review.
  - Moving off `ubuntu-24.04` is a deliberate change of this file, not a label migration.
