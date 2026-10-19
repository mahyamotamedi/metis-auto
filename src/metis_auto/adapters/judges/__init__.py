"""Judge backends (CMP-15). LLM judge and human-label import come later, opt-in."""

from .fake import FakeJudge

__all__ = ["FakeJudge"]
