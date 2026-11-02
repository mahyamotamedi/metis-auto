"""``ModelClient`` adapters (CMP-10; providers.md §2). Decorators compose,
e.g. fault(fake). Live clients come later, opt-in only (ADR-0003)."""

from .dispatch import ModelDispatchClient
from .fake import FakeModelClient
from .injecting import FaultInjectingClient, Quality, QualityInjectingClient
from .recording import RecordingModelClient
from .replay import ProxyModelClient, ReplayModelClient

__all__ = [
    "FakeModelClient",
    "FaultInjectingClient",
    "ModelDispatchClient",
    "ProxyModelClient",
    "Quality",
    "QualityInjectingClient",
    "RecordingModelClient",
    "ReplayModelClient",
]
