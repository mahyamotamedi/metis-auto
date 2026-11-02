## Full-dataset EDA (2026-10-30)

Run under the owner's pre-authorisation to execute all phases in one go ([execution prompt](../../../../Metis_Full_EDA_Claude_Code_Prompt.md), outside the repo). Status: **awaiting review**. Write-up: [full_eda_report.md](../../full_eda/full_eda_report.md); detail, dictionary, plan, questions and the item-level [checklist](../../full_eda/checklist_status.md) are in [`docs/full_eda/`](../../full_eda).

**Data:** `poriniki/metis` revision `30f578f283b903cdbd06cd1b5f7f962f76452ded`; 80,179 sessions, 710,640 messages, 349,079 candidate request-response pairs (the "about 100k sessions" figure is not borne out). Relational Parquet with bot configuration, billing records, user IDs and RAG chunk tables, unlike the sample's nested JSON. Dataset licence: educational use, no redistribution; committed outputs are aggregates only.

**Headline results (all in the claims ledger; see the report for denominators):** five user IDs produce 97% of requests; per-call fees (tied to RAG queries) are 37.6% of recorded cost; instructions and retrieved chunks are very probably sent in full (turn-0 fits, R² 0.95 to 0.98) while history is reduced; full-key exact-cache candidate hits are small and cross-session only; `gemini-2.5-flash` is 12.5% of requests and 65% of recorded cost; no quality, latency or failure evidence exists.

**Repository changes:**
- New code: `src/metis_auto/analysis/` (7 modules, 12 offline tests in `tests/unit/analysis/`), `scripts/full_eda_*.py` (ingest, requests, analyze, figures, review sets, render and check), `config/reference/label-mapping-full-v1.toml`, the notebook `experiments/full_eda/metis_full_eda.ipynb` (executed), README, `docs/full_eda/*`, `reports/full_eda/*`.
- `pyproject.toml`: per-file ruff ignore of E501 for `scripts/full_eda_*.py` (long ledger text). `docs/architecture/module_reference.md`: seven `analysis` rows.
- **Not in the lock files:** matplotlib, nbformat, nbclient, ipykernel, nbconvert, installed into the venv with pip.

**Validation:** 702 tests pass; ruff clean on the new code; architecture tests (import rules, module reference) pass. Two live-adapter integration tests fail on this machine only because the git-ignored tokenizer assets are not fetched (chars/4 fallback); unrelated to this work. Report numbers are checked against the ledger (`scripts/full_eda_render.py --check`).

**Not done or not verified:** embedding-based semantic cache analysis; label validation (needs Persian-capable reviewers); task taxonomy; any quality, latency or failover measurement; PDF export; the earlier PDF report and the brief were not re-read in full.

**Decisions to confirm:** hand-checking of the claims behind the report; whether to rotate the Hugging Face token that appeared in the prompt file; the licence question for sharing derived tables (questions file, item 5).
