"""Derive a normalised fingerprint for every distinct chunk text (S-6, EXP-CTX-001).

The shared ingest (``scripts/full_eda_ingest.py``) writes ``h_exact`` only. This
script reads the ``content`` column of the raw RAG chunk shards **in memory**,
and writes one row per distinct non-empty text: ``h_exact`` (same rule as the
ingest: ``text_features.fingerprint`` of the raw text) and ``h_norm``
(``fingerprint(normalize_safe(text))``; the only normaliser). No text, message ID
or chunk ID is written or printed; output counts only. Join to the chunk table
on ``h_exact``. Owner decision 2026-11-02 (option B), git-ignored output.

    .venv/bin/python scripts/derive_chunk_norm_fingerprints.py
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import pandas as pd

from metis_auto.analysis.text_features import fingerprint, normalize_safe

RAW = Path("data/full_data/raw/data/derived")
OUT = Path("data/derived/context/chunk_norm_fingerprints.parquet")


def norm_fingerprints(content: pd.Series) -> pd.DataFrame:
    """``h_exact`` and ``h_norm`` per distinct non-empty text."""
    texts = content.dropna()
    texts = texts[texts != ""].drop_duplicates()
    table = pd.DataFrame(
        {
            "h_exact": [fingerprint(t) for t in texts],
            "h_norm": [fingerprint(normalize_safe(t)) for t in texts],
        }
    )
    return table.drop_duplicates("h_exact").reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    shards = sorted(glob.glob(str(args.raw / "chat_message_rag_chunks-*.parquet")))
    if not shards:
        raise SystemExit(f"no chunk shards under {args.raw}")
    parts = [
        norm_fingerprints(pd.read_parquet(s, columns=["content"])["content"])
        for s in shards
    ]
    table = pd.concat(parts).drop_duplicates("h_exact").reset_index(drop=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(args.out, index=False)
    print(
        f"shards {len(shards)}, distinct texts {len(table)}, "
        f"distinct normalised texts {table['h_norm'].nunique()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
