"""Event sinks (CMP-14): in-memory and JSON Lines now."""

from .jsonl import JsonLinesEventSink
from .memory import InMemoryEventSink

__all__ = ["InMemoryEventSink", "JsonLinesEventSink"]
