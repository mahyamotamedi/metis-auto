"""Replay harness (CMP-21; evaluation.md §3).

Responsibility: feed ``ReplayCase``s to a pipeline and pair each case with its
``FinalResponse``. References stay here, never reach the pipeline (FR-REQ-06).
Called by: the experiment runner (Stage 8), tests. Calls: the pipeline it is
given (built by wiring; evaluation never imports wiring).

Status: skeleton. Cases run in the order given. TODO(Stage 8): the ordering
rule (session, then naive logged time; A-31), admitted pairing flags and
exclusion counts (FR-EVAL-08), coverage (ADR-0014), cache reset per run.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from metis_auto.application.pipeline import RequestPipeline
from metis_auto.contracts import FinalResponse, Identifier, ReplayCase


@dataclass(frozen=True)
class ReplayOutcome:
    case_id: Identifier
    response: FinalResponse


def replay(
    cases: Iterable[ReplayCase], pipeline: RequestPipeline
) -> list[ReplayOutcome]:
    return [
        ReplayOutcome(
            case_id=case.case_id,
            response=pipeline.handle(
                case.request,
                case_id=case.case_id,
                logged_timestamp=case.logged_timestamp,
            ),
        )
        for case in cases
    ]
