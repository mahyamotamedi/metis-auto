"""Parquet file of golden answers, for sharing between teammates (ADR-0030).

The file holds answer text: callers keep it in git-ignored folders and upload it
only to the team's private dataset. One fixed schema, rows sorted by record ID,
so the same rows always give the same content.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = pa.schema(
    [
        ("record_id", pa.string()),
        ("run_id", pa.string()),
        ("model_id", pa.string()),
        ("provider_model_version", pa.string()),
        ("effort", pa.string()),
        ("max_output_tokens", pa.int64()),
        ("settings_hash", pa.string()),
        ("prompt_fingerprint", pa.string()),
        ("status", pa.string()),
        ("answer", pa.string()),
        ("answer_chars", pa.int64()),
        ("answer_language_group", pa.string()),
        ("finish_reason", pa.string()),
        ("error_class", pa.string()),
        ("attempts", pa.int64()),
        ("input_tokens", pa.int64()),
        ("cached_input_tokens", pa.int64()),
        ("output_tokens", pa.int64()),
        ("reasoning_tokens", pa.int64()),
        ("cost_usd", pa.string()),
        ("cost_state", pa.string()),
        ("latency_ms", pa.float64()),
        ("caveats", pa.list_(pa.string())),
    ]
)
COLUMNS = tuple(SCHEMA.names)


def write_answers(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    """``rows`` use exactly ``COLUMNS``; ``cost_usd`` is a string (exact decimal)."""
    ordered = sorted(rows, key=lambda r: r["record_id"])
    table = pa.Table.from_pylist(
        [{c: row[c] for c in COLUMNS} for row in ordered], schema=SCHEMA
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")


def read_answers(path: Path) -> list[dict[str, Any]]:
    """The rows of an answers file. Raises if the schema is not ``SCHEMA``."""
    table = pq.read_table(path)
    if table.schema.names != list(COLUMNS):
        raise ValueError("the answers file does not have the expected columns")
    return table.to_pylist()
