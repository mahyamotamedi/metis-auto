"""Derive the intent flags of every user message (EXP-ROUTE-012 strict modes,
ADR-0046 Amendment 1).

The shared ingest keeps no message text. This script reads the ``content`` of
the ``USER`` rows of the raw message shards **in memory**, labels each with
``analysis.prompt_labels.primary_category`` (and its secondary tags) and the
domain code detector (``flags_table`` in the experiment's ``version.py``), and
writes only ``message_id``, ``primary_category``, ``blocked_by_category``,
``has_code`` and ``label_state`` (empty or unreadable text: ``unknown``). No
text is written or printed; output counts only. Owner decision 2026-11-03
(decision 1), git-ignored output under ``data/derived/routing/``. The labels
are heuristic, not ground truth (A-78).

    .venv/bin/python scripts/derive_turn_intent_flags.py
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/routing/exp-route-012-small-classifier"
RAW = ROOT / "data/full_data/raw/data"
OUT = ROOT / "data/derived/routing/turn_intent_flags.parquet"
USER_TYPE = "USER"


def _version():
    name = "exp_route_012_version"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, EXP / "version.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def derive(raw: Path, out: Path) -> pd.DataFrame:
    """Flags of the ``USER`` messages of every shard under ``raw``, written to
    ``out`` (first row per ``message_id``)."""
    v = _version()
    shards = sorted(glob.glob(str(raw / "chat_message-*.parquet")))
    if not shards:
        raise SystemExit(f"no message shards under {raw}")
    parts = []
    for shard in shards:
        m = pd.read_parquet(shard, columns=["message_id", "type", "content"])
        m = m[m["type"].eq(USER_TYPE)]
        parts.append(v.flags_table(m["message_id"].tolist(), m["content"].tolist()))
        del m
    table = pd.concat(parts).drop_duplicates("message_id").reset_index(drop=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out, index=False)
    return table


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    table = derive(args.raw, args.out)
    blocked = table["blocked_by_category"] | table["has_code"]
    print(
        f"user messages {len(table)}, label unknown "
        f"{int(table['label_state'].ne('ok').sum())}, blocked {int(blocked.sum())} "
        f"(category {int(table['blocked_by_category'].sum())}, "
        f"code {int(table['has_code'].sum())})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
