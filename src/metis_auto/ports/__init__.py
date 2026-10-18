"""Interfaces for every swappable boundary.

Protocols for provider/model clients, cache stores and vector indexes,
tokenizers and embedders, event sinks, judges, data sources, clocks, ID
sources, and the spend ledger. Declarations only; implementations live in
adapters and data_access and are chosen by wiring.

May import: contracts.
Traces: QA-REPL, FR-API-02, FR-XCACHE-08, FR-SCACHE-03, FR-OBS-06, FR-EVAL-05,
FR-DATA-02.
"""

from .cache import CacheStore, VectorIndex
from .data import DataSource
from .events import EventSink
from .judge import Judge
from .measurement import Embedder, Tokenizer
from .model_client import ModelClient
from .system import Clock, IdSource, SpendLedger

__all__ = [
    "CacheStore",
    "Clock",
    "DataSource",
    "Embedder",
    "EventSink",
    "IdSource",
    "Judge",
    "ModelClient",
    "SpendLedger",
    "Tokenizer",
    "VectorIndex",
]
