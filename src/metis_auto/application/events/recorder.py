"""Event recorder (CMP-03; ADR-0012, observability.md §2–§3).

Responsibility: wrap each payload in an ``Event`` envelope (IDs, run mode,
UTC time, span and duration, versions) and deliver it to the ``EventSink``.
At construction it checks with ``contracts.privacy`` that the event type can
hold no CONTENT field; payloads are typed contracts, so no raw content can be
passed in. A sink failure propagates (fails an offline run).
Called by: application.pipeline (and later the experiment runner). Calls:
ports ``EventSink``, ``Clock``, ``IdSource``. Built by: wiring.
Traces: FR-OBS-01…03, QA-PRIV.
"""

from __future__ import annotations

from datetime import datetime

from metis_auto.contracts import (
    Event,
    EventPayload,
    Identifier,
    RunMode,
    SpanName,
    Versions,
)
from metis_auto.contracts.privacy import content_paths
from metis_auto.ports import Clock, EventSink, IdSource


class EventRecorder:
    def __init__(
        self,
        sink: EventSink,
        clock: Clock,
        ids: IdSource,
        run_id: Identifier,
        run_mode: RunMode,
        versions: Versions,
    ) -> None:
        leaks = content_paths(Event)
        if leaks:
            raise RuntimeError(f"Event contract has content fields: {leaks}")
        self._sink = sink
        self._clock = clock
        self._ids = ids
        self.run_id = run_id
        self.run_mode = run_mode
        self.versions = versions

    def emit(
        self,
        payload: EventPayload,
        *,
        request_id: Identifier | None = None,
        session_ref: Identifier | None = None,
        case_id: Identifier | None = None,
        attempt_id: Identifier | None = None,
        parent_attempt_id: Identifier | None = None,
        span: SpanName | None = None,
        duration_ms: float | None = None,
        logged_timestamp: datetime | None = None,
    ) -> Event:
        event = Event(
            event_id=self._ids.new_id("evt"),
            event_type=payload.event_type,
            run_id=self.run_id,
            run_mode=self.run_mode,
            request_id=request_id,
            session_ref=session_ref,
            case_id=case_id,
            attempt_id=attempt_id,
            parent_attempt_id=parent_attempt_id,
            timestamp=self._clock.now(),
            logged_timestamp=logged_timestamp,
            span=span,
            duration_ms=duration_ms,
            versions=self.versions,
            payload=payload,
        )
        self._sink.emit(event)
        return event
