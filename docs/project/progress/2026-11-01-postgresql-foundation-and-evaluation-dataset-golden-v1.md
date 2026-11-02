## PostgreSQL foundation and evaluation dataset golden-v1 (2026-11-01)

Run on branch `golden-dataset` under the owner's task, checkpoints C0 to C6 authorised without stops. Status: **awaiting review**; nothing committed. Decisions: [ADR-0027](../../adr/0027-local-postgresql-foundation.md), [ADR-0028](../../adr/0028-evaluation-dataset-golden-v1.md). Docs: [golden_v1.md](../../evaluation/golden_v1.md), [team_setup.md](../../guides/team_setup.md). No model calls; labels are rule proposals.

- **C0.** Sources read. Footers re-counted: all row counts match. New facts: 257 bots have owners absent from `users`; derived chunks reproduce the message JSON exactly; `pyarrow` was undeclared (now in extra `db`).
- **C1.** Extra `db`, `requirements-db.lock`, Compose hardened, tables, five migrations; upgrade, `alembic check`, downgrade and re-upgrade pass.
- **C2.** Ingestion on synthetic fixtures, then real data: 2,404,351 rows, reconciliation clean; re-run inserts 0.
- **C3.** `eval.request`: 355,965 USER messages; 329,669 eligible. Pair flags match the EDA ledger (clean 331,397; consecutive 6,928).
- **C4.** Exactly 300 records and 150 reserves; every margin and coverage minimum met on rule labels.
- **C5.** Rule labels, import commands, validation (V-10 pending human review), exports, quality report.
- **C6.** Docs, SQL examples, fingerprint, guide followed from a clean copy (fresh venv, empty database, different hash seeds): `verify` PASS, shareable export byte-identical. Not run: `hf download`, Windows.
- **Pending:** human review; approval of the quotas; whether to retire the EDA proposal.
