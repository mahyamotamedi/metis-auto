"""Context compressor backend: ``TextCompressor`` (Demo milestone, context
plan X3; ADR-0023).

A compressor shortens one text (a history turn or a retrieved item) to about
``rate`` of its tokens. It may run a local model (LLMLingua-2), so it is a
measurement-like port called by application only (P-1); the domain decides
what is compressed and records the result. Implemented by
adapters.compressors (LLMLingua-2, extra ``compress``; and a labelled fake for
tests). Traces: FR-CTX-02, brief §9.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from metis_auto.contracts import PolicyRef


@dataclass(frozen=True)
class CompressedText:
    """One compressed text. ``text`` is content (in memory only); the token
    counts are the compressor's own tokens, not the target model's."""

    text: str
    tokens_before: int
    tokens_after: int


@runtime_checkable
class TextCompressor(Protocol):
    @property
    def ref(self) -> PolicyRef:
        """Compressor name and version (model revision included)."""
        ...

    @property
    def token_method(self) -> str:
        """How ``tokens_before`` / ``tokens_after`` are counted."""
        ...

    def compress(self, text: str, rate: float) -> CompressedText: ...
