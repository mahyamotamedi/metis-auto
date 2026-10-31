"""Phase 1b: build the linked request-level table from the ingest outputs.

    python scripts/full_eda_requests.py [--smoke]

Writes data/derived/full_eda[_smoke]/requests.parquet (local only, holds grouping
hashes) and a manifest line with row counts and pairing flags.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path

import pandas as pd

from metis_auto.analysis.requests_table import build_requests


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--dir", default="data/derived/full_eda")
    a = ap.parse_args()
    d = Path(a.dir + ("_smoke" if a.smoke else ""))
    msgs = pd.concat(
        [
            pd.read_parquet(f).assign(shard=i)
            for i, f in enumerate(sorted(glob.glob(str(d / "messages_*.parquet"))))
        ],
        ignore_index=True,
    )
    sessions = pd.read_parquet(d / "sessions.parquet")
    bots = pd.read_parquet(d / "bots.parquet")
    # A hash of the retrieved chunk set per AI message (rank-insensitive).
    sets = {}
    for f in sorted(glob.glob(str(d / "chunks" / "*.parquet"))):
        c = pd.read_parquet(f, columns=["message_id", "h_exact"]).dropna()
        for mid, g in c.groupby("message_id"):
            sets[mid] = hashlib.blake2b(
                "|".join(sorted(g["h_exact"])).encode(), digest_size=12
            ).hexdigest()
    rag_set = pd.Series(sets, dtype="object")
    r = build_requests(msgs, sessions, bots, rag_set)
    r.to_parquet(d / "requests.parquet", index=False)
    info = {"n_requests": len(r), "pair_flags": r["pair_flag"].value_counts().to_dict()}
    (d / "requests_manifest.json").write_text(json.dumps(info, indent=2))
    print(info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
