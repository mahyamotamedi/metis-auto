"""Run-tracking port: ``RunTracker`` (sprint T-2).

A tracker is an **exporter** of finished lever results to an experiment-tracking
service; the content-free ``LeverResult`` JSON stays the record (ADR-0022,
ADR-0032 point 8). It takes a plain mapping because ports may not import
``analysis`` (ADR-0009).
Called by: scripts/log_levers.py. Implemented by: adapters.tracking.
Traces: QA-REPRO, QA-PRIV.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class RunTracker(Protocol):
    """Logs one lever result as one run."""

    def log_result(self, result: Mapping[str, object]) -> str:
        """Log ``result`` (a lever-result mapping) and return the run ID.

        Idempotent by ``lever_id`` + ``manifest.config_hash``: logging the same
        result again returns the existing run's ID.
        """
        ...
