"""Phase 1: ingest the full Metis dataset into content-free feature tables.

Reads the pinned Hugging Face snapshot (data/full_data/raw, git-ignored) and
writes Parquet feature tables plus a manifest to data/derived/full_eda/
(git-ignored). Usable pieces are resumable per shard. ``--smoke`` processes
only the first 3,000 messages of the first shard.

    python scripts/full_eda_ingest.py [--smoke] [--raw DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import platform
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from metis_auto.analysis.ingest import bot_features, message_features
from metis_auto.analysis.text_features import fingerprint

REVISION = "30f578f283b903cdbd06cd1b5f7f962f76452ded"


def _do_messages(args: tuple[str, str, int | None]) -> tuple[str, int]:
    path, out, limit = args
    name = Path(path).stem
    dest = Path(out) / f"messages_{name}.parquet"
    if dest.exists() and limit is None:
        return name, pq.ParquetFile(dest).metadata.num_rows
    df = pd.read_parquet(path)
    if limit:
        df = df.head(limit)
    rows = []
    for i, r in enumerate(df.to_dict("records")):
        f = message_features(r)
        f["shard_row"] = i
        rows.append(f)
    pd.DataFrame(rows).to_parquet(dest, index=False)
    return name, len(rows)


def _do_chunks(args: tuple[str, str, int | None]) -> tuple[str, int]:
    path, out, limit = args
    name = Path(path).stem
    dest = Path(out) / f"{name}.parquet"
    if dest.exists() and limit is None:
        return name, pq.ParquetFile(dest).metadata.num_rows
    df = pd.read_parquet(
        path, columns=["message_id", "chunk_id", "content", "corpusId", "relevancy"]
    )
    if limit:
        df = df.head(limit)
    c = df["content"].fillna("")
    res = pd.DataFrame(
        {
            "message_id": df["message_id"],
            "chunk_id": df["chunk_id"],
            "corpus_id": df["corpusId"],
            "relevancy": df["relevancy"],
            "n_chars": c.str.len(),
            "h_exact": [fingerprint(x) if x else None for x in c],
        }
    )
    res.to_parquet(dest, index=False)
    return name, len(res)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--raw", default="data/full_data/raw/data")
    ap.add_argument("--out", default="data/derived/full_eda")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    raw, out = Path(a.raw), Path(a.out)
    if a.smoke:
        out = out.with_name(out.name + "_smoke")
    (out / "chunks").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    limit = 3000 if a.smoke else None

    # Dimension tables.
    bots = pd.read_parquet(raw / "chat_bot.parquet")
    pd.DataFrame([bot_features(r) for r in bots.to_dict("records")]).to_parquet(
        out / "bots.parquet", index=False
    )
    sess = pd.read_parquet(raw / "chat_session.parquet").drop(columns=["headline"])
    sess.to_parquet(out / "sessions.parquet", index=False)
    pd.read_parquet(raw / "users.parquet").drop(columns=["username_anon"]).to_parquet(
        out / "users.parquet", index=False
    )
    # Derived billing/rag/input tables duplicate the JSON columns; message features cover them.
    shards = sorted(glob.glob(str(raw / "chat_message-*.parquet")))
    chunk_files = sorted(
        glob.glob(str(raw / "derived" / "chat_message_rag_chunks-*.parquet"))
    )
    if a.smoke:
        shards, chunk_files = shards[:1], chunk_files[:1]
    counts: dict[str, int] = {}
    with ProcessPoolExecutor(a.workers) as ex:
        for name, n in ex.map(_do_messages, [(s, str(out), limit) for s in shards]):
            counts[name] = n
            print("messages", name, n, flush=True)
        for name, n in ex.map(
            _do_chunks, [(s, str(out / "chunks"), limit) for s in chunk_files]
        ):
            counts[name] = n
            print("chunks", name, n, flush=True)

    cfg = {"revision": REVISION, "smoke": a.smoke, "limit": limit}
    manifest = {
        "phase": "ingest",
        "revision": REVISION,
        "smoke": a.smoke,
        "config_hash": hashlib.sha256(
            json.dumps(cfg, sort_keys=True).encode()
        ).hexdigest()[:16],
        "row_counts": counts,
        "bots": len(bots),
        "sessions": len(sess),
        "python": sys.version.split()[0],
        "pandas": pd.__version__,
        "pyarrow": pa.__version__,
        "platform": platform.platform(),
        "cpus": os.cpu_count(),
        "elapsed_s": round(time.time() - t0, 1),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("done in", manifest["elapsed_s"], "s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
