"""Metrics and aggregates (CMP-23; evaluation.md §6, ADR-0006).

Responsibility: compute ADR-0006 metrics and FR-OBS-05 aggregates **from
events plus references**, overall and per stratum, with sample sizes and
intervals; the same code later serves the dashboard. Hit rate always comes
with hit correctness; cost with fidelity and price version.
Called by: the experiment runner. Calls: ports ``Judge``, ``Embedder``.

Status: skeleton. TODO(Stage 8).
"""

from __future__ import annotations

from collections.abc import Iterable

from metis_auto.contracts import EvaluationResult, Event, ReplayCase


def aggregate(events: Iterable[Event], cases: Iterable[ReplayCase]) -> EvaluationResult:
    raise NotImplementedError("TODO(Stage 8): metric computation")
