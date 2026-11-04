## Fix branch CI ADR finalization gate (2026-11-05)

- Inspected failed GitHub Actions runs 41921936448 and 41921927548 for commit
  991c347. Both failed at the ADR/progress metadata gate before pytest ran.
- Reproduced the failure with `python scripts/adr_finalize.py --check`: two
  draft ADRs and their unresolved references prevented CI from proceeding.
- Fetched `origin/main`, reviewed the finalizer's dry-run, then ran the
  documented merger script. It assigned ADR-0065 to demo discoverability and
  usable RAG, and ADR-0066 to demo sprint winners, renamed the draft files,
  updated citations/links and regenerated the ADR table. Corrected two wrapped
  source docstring citations that the finalizer's single-line matcher missed.
- No CI checks were disabled or relaxed; application behavior is unchanged.
- ADR check, progress-index check, repository-wide Ruff lint/format, Compose
  configuration validation and diff whitespace checks pass. The full offline
  pytest suite is being rerun using the command from `.github/workflows/ci.yml`.
- Changes are local; remote CI will need a new commit/push. This correction does
  not resolve the separate benchmark/standards findings recorded in the earlier
  demo push-readiness review.
