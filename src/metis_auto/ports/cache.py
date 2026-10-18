"""Cache storage ports: ``CacheStore`` and ``VectorIndex`` (CMP-11).

Stores hold data and apply **no** validity rules: TTLs, status, scope, and
thresholds are the cache policy's (domain.caching, ADR-0011 point 5).
Called by: application.pipeline. Implemented by: adapters.stores (in-memory
now; a persistent store after the full EDA, CMP-F4).
Traces: FR-XCACHE-08, FR-SCACHE-03, ADR-0011.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from metis_auto.contracts import (
    CacheEntry,
    Embedding,
    Fingerprint,
    Identifier,
    IndexMatch,
)


@runtime_checkable
class CacheStore(Protocol):
    """Entries by exact key fingerprint."""

    def get(self, key: Fingerprint) -> CacheEntry | None:
        """The entry stored under ``key`` (``CacheKey.key``), if any."""
        ...

    def put(self, entry: CacheEntry) -> None:
        """Store ``entry`` under ``entry.key.key``, replacing any previous one."""
        ...


@runtime_checkable
class VectorIndex(Protocol):
    """Vectors by partition key and embedder version (caching.md §5).

    Vectors from different embedders are never compared; the index partitions
    by ``Embedding.embedder``.
    """

    def add(
        self, entry_id: Identifier, partition_key: Fingerprint, embedding: Embedding
    ) -> None: ...

    def query(
        self, partition_key: Fingerprint, embedding: Embedding, top_k: int
    ) -> tuple[IndexMatch, ...]:
        """Best matches in the same partition and embedder, best first."""
        ...
