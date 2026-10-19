"""In-memory event sink, for tests and the walking skeleton. Implements
``ports.EventSink``. Status: stable (test double)."""

from __future__ import annotations

from metis_auto.contracts import Event


class InMemoryEventSink:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass
