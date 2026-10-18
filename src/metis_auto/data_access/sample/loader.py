"""Sample-file loader (CMP-18; contracts.md §4).

Responsibility: read ``data/sample_data/raw/`` (read-only) and yield generic
``Session``s. All sample quirks stop here: role ``bot`` → ``assistant``;
category → opaque stratum ID; session ID → keyed ``session_ref``; empty
values → absent (O-4); joint instruction/model/provider nulls → unknown with
reason ``not_in_log`` (Q-25); attachment type → modality; possibly truncated
retrieved context → a ``DataQualityFlag``. Re-implemented and tested; never
taken from the sample-EDA helpers (ADR-0008). Implements ``ports.DataSource``.
Built by: wiring with a path from runtime config.

Status: skeleton. TODO(Stage 9).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from metis_auto.contracts import Name, Session


class SampleDataSource:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def dataset(self) -> Name:
        return "sample_v1"

    def sessions(self) -> Iterator[Session]:
        raise NotImplementedError("TODO(Stage 9): sample loader")
