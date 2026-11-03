"""Write and read the dev slice's local record file (Parquet, git-ignored).

The record file holds content (message, history, instructions, retrieved
chunks, the logged answer) and lives only under ``data/derived/`` (licence:
no redistribution). Nested values are JSON text columns so the schema stays
flat and stable. Called by: wiring.router_slice. Traces: FR-DATA-06, QA-PRIV.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


def write_records(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(pa.Table.from_pylist(list(rows)), tmp, compression="zstd")
    tmp.replace(path)


def read_records(path: Path) -> list[dict[str, Any]]:
    return pq.read_table(path).to_pylist()
