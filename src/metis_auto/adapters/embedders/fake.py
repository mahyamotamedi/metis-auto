"""Deterministic fake embedder: a vector derived from a hash of the text.

Responsibility: exercise the semantic-tier plumbing offline. Similar texts do
**not** get similar vectors; it carries no meaning. Implements
``ports.Embedder``. Status: test double; real backends TODO(Stage 8).
"""

from __future__ import annotations

import hashlib

from metis_auto.contracts import EmbedderRef, Embedding


class FakeEmbedder:
    def __init__(self, dimensions: int = 8) -> None:
        self._ref = EmbedderRef(
            embedder_id="fake-embedder", version="1.0.0", dimensions=dimensions
        )

    @property
    def ref(self) -> EmbedderRef:
        return self._ref

    def embed(self, text: str) -> Embedding:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        n = self._ref.dimensions
        vector = tuple((digest[i % len(digest)] - 127.5) / 127.5 for i in range(n))
        return Embedding(embedder=self._ref, vector=vector)
