"""ID sources. ``UuidIdSource`` for real runs; ``SequentialIdSource`` makes
replay reproducible (QA-REPRO). Implements ``ports.IdSource``. Status: stable."""

from __future__ import annotations

import uuid
from collections import defaultdict


class UuidIdSource:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"


class SequentialIdSource:
    def __init__(self, namespace: str = "") -> None:
        self._namespace = f"{namespace}." if namespace else ""
        self._counters: defaultdict[str, int] = defaultdict(int)

    def new_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{self._namespace}{prefix}-{self._counters[prefix]:06d}"
