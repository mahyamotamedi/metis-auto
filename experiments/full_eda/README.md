# experiments/full_eda/: full-dataset EDA

Home of the full-dataset EDA ([ADR-0008](../../docs/adr/0008-sample-eda-is-exploratory.md), [ADR-0009](../../docs/adr/0009-repository-structure-and-dependency-rules.md)). Status: **run 2026-10-30 on `poriniki/metis` revision `30f578f283b903cdbd06cd1b5f7f962f76452ded`**; results in [`docs/full_eda/`](../../docs/full_eda/full_eda_report.md).

| What | Where |
|---|---|
| notebook | `metis_full_eda.ipynb` (display and orchestration; no content in outputs) |
| tested analysis code | `src/metis_auto/analysis/` (re-implemented; nothing from `sample_eda/eda_helpers.py`), tests in `tests/unit/analysis/` |
| pipeline scripts | `scripts/full_eda_ingest.py`, `full_eda_requests.py`, `full_eda_analyze.py`, `full_eda_figures.py`, `full_eda_review_sets.py`, `full_eda_render.py` |
| feature-only tables, ledger, figures, review sets | `reports/full_eda/` |
| write-up | `docs/full_eda/` |
| local derived data (git-ignored) | `data/derived/full_eda/`, `runs/full_eda/` |

## Setup and dataset access

The dataset is private and gated. Provide a Hugging Face token **only** through the environment or an existing `huggingface-cli login`; never write it to a file.

```bash
export HF_TOKEN=...        # your token
.venv/bin/python - <<'EOF'
from huggingface_hub import snapshot_download
snapshot_download("poriniki/metis", repo_type="dataset",
                  revision="30f578f283b903cdbd06cd1b5f7f962f76452ded",
                  local_dir="data/full_data/raw")
EOF
```

`data/full_data/` is git-ignored and read-only by convention. Optional notebook and plotting libraries (`matplotlib`, `nbformat`, `nbclient`, `ipykernel`, `nbconvert`) were installed into the venv with `pip` and are **not** in the lock files; add an extra before promoting this work.

## Reproduce

```bash
.venv/bin/python scripts/full_eda_ingest.py            # about 3 minutes on 8 CPUs
.venv/bin/python scripts/full_eda_requests.py          # about 1 minute
.venv/bin/python scripts/full_eda_analyze.py --phases scope,language,tokens,history,rag,cache,routing,reduction --tag a
.venv/bin/python scripts/full_eda_analyze.py --phases semantic --tag b
.venv/bin/python scripts/full_eda_analyze.py --phases extras --tag c
.venv/bin/python scripts/full_eda_figures.py
.venv/bin/python scripts/full_eda_review_sets.py
.venv/bin/python scripts/full_eda_render.py            # ledger merge and report render
.venv/bin/python scripts/full_eda_render.py --check    # every number comes from the ledger
```

Add `--smoke` to the ingest, requests and analyze scripts for a 3,000-message run of one shard (written to `*_smoke` directories). The report is built from the templates in `docs/full_eda/templates/`; edit a template, never the rendered file.

## Resources and known limits

Peak memory about 6 GB (the request table and message features are held in memory); disk about 1 GB raw plus about 2 GB derived. CPU only. Seeds: sampling 20261030. Known limits: heuristic language labels (validation pending), heuristic pairing, no embedding-based semantic analysis, candidate (not validated) cache hits, recorded costs on a different basis from the price file, two integration tests of the live adapter fail on a machine without the fetched tokenizer assets (unrelated to this work).
