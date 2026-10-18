"""Replay-case builder (CMP-18; evaluation.md §3, FR-REQ-03, FR-REQ-06).

Responsibility: turn a ``Session`` into ``ReplayCase``s, one per user turn,
holding only what came before that turn (no look-ahead), with 0…n paired
answers, the pairing method and flag, and exclusion counts (answers with no
preceding user message never become cases). The pairing heuristic is
re-implemented and tested (A-04); never taken from the EDA helpers.
Called by: wiring-built data pipelines for evaluation (Stage 8/9).

Status: skeleton. TODO(Stage 9).
"""

from __future__ import annotations

from metis_auto.contracts import ExclusionCount, ReplayCase, Session


def build_cases(
    session: Session,
) -> tuple[tuple[ReplayCase, ...], tuple[ExclusionCount, ...]]:
    raise NotImplementedError("TODO(Stage 9): pairing and case building")
