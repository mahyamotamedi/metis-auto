"""Event sinks (CMP-14): in-memory and JSON Lines now."""

from .fanout import FanOutEventSink
from .jsonl import JsonLinesEventSink
from .memory import InMemoryEventSink
from .postgres import PostgresEventSink

__all__ = [
    "FanOutEventSink",
    "InMemoryEventSink",
    "JsonLinesEventSink",
    "PostgresEventSink",
]
