"""Unsatisfactory-response detectors (attempts.md §4).

Responsibility: each detector returns a ``DetectorVerdict`` for one response;
a combination rule turns verdicts into one decision (FR-CASC-05). Pure.
Called by: application.pipeline after each response. Status: the two free
built-in detectors are implemented; which detectors actually work is open
(A-20, TODO-06). TODO(Stage 8): refusal, language mismatch, length anomaly,
judge-score threshold (the judge score is a measurement, P-1).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from metis_auto.contracts import (
    DetectorVerdict,
    FinishReason,
    ModelResponse,
    VerdictState,
)


class Detector(Protocol):
    def evaluate(self, response: ModelResponse) -> DetectorVerdict: ...


class TruncationDetector:
    """Fires when the provider stopped at the output limit."""

    def evaluate(self, response: ModelResponse) -> DetectorVerdict:
        fired = response.finish_reason == FinishReason.LENGTH
        return DetectorVerdict(
            detector="truncation",
            version="1.0.0",
            state=VerdictState.EVALUATED,
            value=1.0 if fired else 0.0,
            threshold=1.0,
            fired=fired,
        )


class EmptyOutputDetector:
    """Fires on an empty or whitespace-only answer."""

    def evaluate(self, response: ModelResponse) -> DetectorVerdict:
        fired = not response.text.strip()
        return DetectorVerdict(
            detector="empty_output",
            version="1.0.0",
            state=VerdictState.EVALUATED,
            value=float(len(response.text.strip())),
            threshold=0.0,
            fired=fired,
        )


def run_detectors(
    response: ModelResponse, detectors: Sequence[Detector]
) -> tuple[DetectorVerdict, ...]:
    return tuple(d.evaluate(response) for d in detectors)


def is_unsatisfactory(verdicts: Sequence[DetectorVerdict]) -> bool:
    """Default combination rule: any fired detector (attempts.md §4).
    TODO(Stage 8): configurable rules once detector precision is measured."""
    return any(v.fired for v in verdicts)
