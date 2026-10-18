"""``DataSource``: where logged or synthetic sessions come from (CMP-18).

Nothing outside the data layer depends on where data is stored (FR-DATA-02).
Called by: evaluation (replay-case building, via wiring), analysis.
Implemented by: data_access (sample loader, synthetic generator; full-dataset
loader and database repositories later). Traces: FR-DATA-01…08.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from metis_auto.contracts import Name, Session


@runtime_checkable
class DataSource(Protocol):
    @property
    def dataset(self) -> Name:
        """Dataset ID recorded in manifests, e.g. ``synthetic_v1``."""
        ...

    def sessions(self) -> Iterator[Session]:
        """Sessions in a stable order. Each is generic: dataset quirks were
        handled by the loader (contracts.md §4)."""
        ...
