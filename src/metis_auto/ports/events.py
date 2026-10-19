"""``EventSink``: durable, ordered delivery of events (CMP-14, ADR-0012).

Called by: application.events (the recorder). Implemented by: adapters.sinks
(in-memory, JSON Lines now; database or telemetry exporter later).
Offline, a sink failure is an exception that fails the run (observability §6).
Traces: FR-OBS-01, FR-OBS-06.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from metis_auto.contracts import Event


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event: Event) -> None:
        """Deliver one event, in order. Events carry no content (tested)."""
        ...

    def close(self) -> None:
        """Flush and release resources. Idempotent."""
        ...
