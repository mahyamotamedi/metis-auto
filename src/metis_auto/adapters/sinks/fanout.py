"""Fan-out event sink: every event to several sinks, in order (T-3; FR-OBS-06;
ADR-0033). Implements ``ports.EventSink``.

Used when ``[events] sink = "postgres"``: the run's JSON Lines file stays the
measurement record (ADR-0022) and Postgres gets the same events. A failure in
any sink raises and fails the run (observability §6). ``close`` closes every
sink, even after one fails, then raises the first failure. It is idempotent
because each sink's ``close`` is.
"""

from __future__ import annotations

from collections.abc import Sequence

from metis_auto.contracts import Event
from metis_auto.ports import EventSink


class FanOutEventSink:
    def __init__(self, sinks: Sequence[EventSink]) -> None:
        self._sinks = tuple(sinks)

    def emit(self, event: Event) -> None:
        for sink in self._sinks:
            sink.emit(event)

    def close(self) -> None:
        first: Exception | None = None
        for sink in self._sinks:
            try:
                sink.close()
            except Exception as exc:
                first = first or exc
        if first is not None:
            raise first
