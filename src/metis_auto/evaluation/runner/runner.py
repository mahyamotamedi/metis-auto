"""Experiment runner (CMP-24; evaluation.md §1–§2).

Responsibility: run one experiment config over a dataset slice against the
baselines; write the ``RunManifest``, events, and ``EvaluationResult`` under
``runs/<EXP-ID>/<run-id>/``. Receives pipeline factories from wiring (it never
imports wiring) and cases from a data source.
Called by: scripts (Stage 8). Calls: evaluation.replay, .baselines, .metrics.

Status: skeleton. TODO(Stage 8): experiment config format, strategy loading
from experiments/ (A-26), manifest fields (code version, data hash, seed).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from metis_auto.application.pipeline import RequestPipeline
from metis_auto.contracts import EvaluationResult, ReplayCase


class ExperimentRunner:
    def __init__(self, pipeline_factory: Callable[[], RequestPipeline]) -> None:
        self._factory = pipeline_factory

    def run(self, cases: Iterable[ReplayCase]) -> EvaluationResult:
        raise NotImplementedError("TODO(Stage 8): experiment runner")
