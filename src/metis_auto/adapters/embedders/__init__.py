"""Embedder backends (CMP-13). Persian-capable backends are chosen in Stage 8."""

from .fake import FakeEmbedder

__all__ = ["FakeEmbedder"]
