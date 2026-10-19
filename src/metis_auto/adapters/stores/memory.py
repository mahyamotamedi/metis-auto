"""In-memory ``CacheStore`` and ``VectorIndex`` (caching.md §5).

Responsibility: hold entries and vectors for one process or run; no validity
rules (ADR-0011 point 5). Content (answers, vectors) stays in memory.
Built by: wiring (one per run; replay resets cache state per run).
Called by: application.pipeline. Status: stable for offline use.
"""

from __future__ import annotations

import math

from metis_auto.contracts import (
    CacheEntry,
    EmbedderRef,
    Embedding,
    Fingerprint,
    Identifier,
    IndexMatch,
)


class InMemoryCacheStore:
    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}

    def get(self, key: Fingerprint) -> CacheEntry | None:
        return self._entries.get(key)

    def put(self, entry: CacheEntry) -> None:
        self._entries[entry.key.key] = entry

    def __len__(self) -> int:
        return len(self._entries)


class InMemoryVectorIndex:
    """Cosine similarity, brute force. Partitioned by key and embedder."""

    def __init__(self) -> None:
        self._rows: dict[
            tuple[str, EmbedderRef], list[tuple[str, tuple[float, ...]]]
        ] = {}

    def add(
        self, entry_id: Identifier, partition_key: Fingerprint, embedding: Embedding
    ) -> None:
        part = (partition_key, embedding.embedder)
        self._rows.setdefault(part, []).append((entry_id, embedding.vector))

    def query(
        self, partition_key: Fingerprint, embedding: Embedding, top_k: int
    ) -> tuple[IndexMatch, ...]:
        rows = self._rows.get((partition_key, embedding.embedder), [])
        scored = sorted(
            ((_cosine(embedding.vector, v), entry_id) for entry_id, v in rows),
            reverse=True,
        )
        return tuple(
            IndexMatch(entry_id=entry_id, similarity=s, embedder=embedding.embedder)
            for s, entry_id in scored[:top_k]
        )


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0
