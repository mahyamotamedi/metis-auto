"""Aggregate report of EXP-CTX-001 within-message chunk dedup (S-6).

Reads ``requests.parquet``, the chunk table and the local ``h_norm`` map (from
``scripts/derive_chunk_norm_fingerprints.py``; without it the normalised figures
are "not computed"), applies the version and writes counts and shares by fitting
split (``replay_scope.split_by_session``) and in total, over all requests and
over LLM requests only, to ``reports/context/exp-ctx-001/summary.csv``. Also
prints the EDA re-check (every chunk row with text, joined or not). No IDs,
hashes or text are written or printed. No saving is computed (README).

    .venv/bin/python scripts/context_dedup_report.py
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import sys
import tomllib
from pathlib import Path

import pandas as pd

from metis_auto.analysis.levers import ReplayContext
from metis_auto.analysis.replay_scope import (
    period_bounds_from_config,
    scope,
    split_by_session,
)

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/context/exp-ctx-001-within-message-dedup"
DERIVED = ROOT / "data/derived/full_eda"
NORM = ROOT / "data/derived/context/chunk_norm_fingerprints.parquet"
OUT = ROOT / "reports/context/exp-ctx-001/summary.csv"
REQ_COLUMNS = [
    "ai_message_id",
    "session_id",
    "bot_id",
    "u_h_norm",
    "a_timestamp",
    "a_order",
    "bot_provider_name",
]


def _version():
    name = "exp_ctx_001_version"
    spec = importlib.util.spec_from_file_location(name, EXP / "version.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    version = _version()
    sprint = tomllib.loads((ROOT / "config/evaluation/sprint.toml").read_text())
    ctx = ReplayContext(
        period_bounds=period_bounds_from_config(sprint["periods"]),
        price_table={},
        catalogue={},
        seed=sprint["split"]["seed"],
    )
    req = scope(pd.read_parquet(DERIVED / "requests.parquet", columns=REQ_COLUMNS), ctx)
    req["split"] = split_by_session(req, seed=ctx.seed)
    files = sorted(glob.glob(str(DERIVED / "chunks" / "*.parquet")))
    chunks = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    if NORM.exists():
        chunks = chunks.merge(pd.read_parquet(NORM), on="h_exact", how="left")

    text = chunks["h_exact"].notna()
    eda_dup = version.within_message_duplicates(chunks)
    joined = chunks["message_id"].isin(req["ai_message_id"])
    print(
        f"EDA re-check (all chunk rows with text): "
        f"{int(eda_dup['n_dup_exact'].sum())} / {int(text.sum())} exact duplicate rows"
        f" = {eda_dup['n_dup_exact'].sum() / text.sum():.4f}; "
        f"chunk rows {len(chunks)}, joined to a request {int(joined.sum())}"
    )
    out = version.WithinMessageDedup(chunks).apply(req, ctx)
    summary = version.summarise(out, by="split")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.out, index=False, float_format="%.6f")
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
