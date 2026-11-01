"""Write dataset exports as Parquet and JSON Lines. One JSON-text column per object."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


def _plain(value: Any) -> Any:
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return value


def write_rows(rows: Sequence[Mapping[str, Any]], stem: Path) -> list[Path]:
    """``stem``.parquet and ``stem``.jsonl; both deterministic for the same rows."""
    stem.parent.mkdir(parents=True, exist_ok=True)
    jsonl = stem.with_suffix(".jsonl")
    with jsonl.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
            )
    table = pa.Table.from_pylist(
        [{k: _plain(v) for k, v in sorted(row.items())} for row in rows]
    )
    parquet = stem.with_suffix(".parquet")
    pq.write_table(table, parquet, compression="zstd")
    return [parquet, jsonl]
