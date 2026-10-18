"""Measurement backends: ``Tokenizer`` (CMP-12) and ``Embedder`` (CMP-13).

Called by: application.measurement only (P-1: domain never calls a port).
Implemented by: adapters.tokenizers (approximation now; exact backends in
Stage 7) and adapters.embedders (fake now; Persian-capable backends in Stage 8).
Traces: FR-ACCT-01, FR-SCACHE-03, H-7, ADR-0006.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from metis_auto.contracts import EmbedderRef, Embedding, Name, TokenCount


@runtime_checkable
class Tokenizer(Protocol):
    """Counts tokens for one model family. Every count carries its fidelity
    and method (FR-ACCT-01). Network counting backends are opt-in."""

    @property
    def ref(self) -> Name:
        """Catalogue ``tokenizer_ref`` this backend serves."""
        ...

    def count(self, text: str) -> TokenCount: ...


@runtime_checkable
class Embedder(Protocol):
    """Text to vector. The vector is content (A-32)."""

    @property
    def ref(self) -> EmbedderRef: ...

    def embed(self, text: str) -> Embedding: ...
