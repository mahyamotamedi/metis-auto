"""JSON Lines event sink: one event per line, under ``runs/`` (gitignored).

Responsibility: durable, ordered event delivery for offline runs. A write
failure raises and fails the run (observability §6). Events carry no content
(tested), so the file holds none. Implements ``ports.EventSink``.
Built by: wiring with a path from runtime config. Status: stable for offline.
"""

from __future__ import annotations

from pathlib import Path

from metis_auto.contracts import Event


class JsonLinesEventSink:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a", encoding="utf-8")

    def emit(self, event: Event) -> None:
        self._file.write(event.model_dump_json() + "\n")

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
