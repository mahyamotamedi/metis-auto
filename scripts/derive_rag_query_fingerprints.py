"""Derive the normalised retrieval-query fingerprints of every message (R-C1,
EXP-CACHE-004).

The shared ingest keeps no query text. This script reads the ``rag`` column of
the raw message shards **in memory**, takes each logged query's
``fingerprint(normalize_safe(query))`` (the only normaliser), and writes one row
per message with a parseable ``rag`` list: ``message_id`` and ``query_fps``
(sorted fingerprints; a missing or blank query has none, so a message whose
list is shorter than ``a_rag_n_queries`` has an unknown query set). No query
text is written or printed; output counts only. Owner decision 2026-11-02
(decision 3), git-ignored output under ``data/derived/cache/``.

    .venv/bin/python scripts/derive_rag_query_fingerprints.py
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import pandas as pd

from metis_auto.analysis.text_features import fingerprint, normalize_safe

RAW = Path("data/full_data/raw/data")
OUT = Path("data/derived/cache/rag_query_fingerprints.parquet")


def query_fingerprints(raw: str | None) -> list[str] | None:
    """Sorted fingerprints of one message's logged queries; ``None`` when the
    ``rag`` field is missing, malformed or not a list."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        items = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(items, list):
        return None
    out = []
    for item in items:
        query = item.get("query") if isinstance(item, dict) else None
        norm = normalize_safe(query) if isinstance(query, str) else ""
        if norm:
            out.append(fingerprint(norm))
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    shards = sorted(glob.glob(str(args.raw / "chat_message-*.parquet")))
    if not shards:
        raise SystemExit(f"no message shards under {args.raw}")
    parts = []
    for shard in shards:
        m = pd.read_parquet(shard, columns=["message_id", "rag"])
        m = m[m["rag"].notna()]
        fps = m["rag"].map(query_fingerprints)
        keep = fps.notna()
        parts.append(
            pd.DataFrame(
                {"message_id": m.loc[keep, "message_id"], "query_fps": fps[keep]}
            )
        )
    table = pd.concat(parts).drop_duplicates("message_id").reset_index(drop=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(args.out, index=False)
    n_fps = table["query_fps"].map(len)
    print(
        f"shards {len(shards)}, messages {len(table)}, "
        f"with at least one query {int((n_fps > 0).sum())}, queries {int(n_fps.sum())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
