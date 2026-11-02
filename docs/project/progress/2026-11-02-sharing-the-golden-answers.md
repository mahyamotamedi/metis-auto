## Sharing the golden answers (2026-11-02)

Branch `golden-answers-sharing`. Status: **built and tested; awaiting review; nothing uploaded, nothing committed**. [ADR-0030](../../adr/0030-golden-answers-gpt-5-5.md) (sharing paragraph); guide: [golden_answers.md](../../evaluation/golden_answers.md#sharing-the-answers-with-the-team), [team_setup.md](../../guides/team_setup.md) step 11.

- **Commands** (`scripts/golden_answers.py`): `export <run>`, `import <folder>`, `verify-answers <run>`, `fingerprint-answers <run>`. The team's private dataset is `Metis-auto/golden-answers-v2`; the raw-data dataset never receives answers.
- **Safety:** the export folder is git-ignored and holds exactly three files; `import` checks the sha256 before opening the file (found by a test: a corrupted file used to crash before the check), the dataset, the golden-v2 fingerprint, every record ID and any differing local answer, and writes nothing when it refuses.
- **Tests:** unit tests for the manifest, card, fingerprint and import checks; opt-in Postgres tests for export, an emptied table, import, idempotency, verify and each refusal.
