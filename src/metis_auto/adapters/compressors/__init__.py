"""Context-compressor backends (Demo milestone, ADR-0023): LLMLingua-2
(optional extra ``compress``; imported only when built) and a labelled fake
for offline tests. Implement ``ports.TextCompressor``."""

from .fake import FakeCompressor

__all__ = ["FakeCompressor"]
