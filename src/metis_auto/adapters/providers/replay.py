"""Counterfactual-source clients without new calls (ADR-0014;
evaluation.md §4): replay (``logged_match`` / ``recorded``) and ``proxy``.

``ProxyModelClient`` is complete: a proxy run has no answers by definition.
``ReplayModelClient`` is a skeleton. Implements ``ports.ModelClient``.
Built by: wiring for evaluation runs. Status: replay is TODO(Stage 8).
"""

from __future__ import annotations

from metis_auto.contracts import (
    AnswerSource,
    ModelInvocation,
    ModelNoAnswer,
    ModelResult,
    NoAnswerReason,
)


class ProxyModelClient:
    """No answers at all: cost and overhead estimates only."""

    @property
    def source(self) -> AnswerSource:
        return AnswerSource.NONE

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        return ModelNoAnswer(
            reason=NoAnswerReason.PROXY_SOURCE, source=AnswerSource.NONE
        )


class ReplayModelClient:
    """Answers from logged references or ``data/recorded/``.

    TODO(Stage 8): look up by case ID × model × composition fingerprint
    (ADR-0014 consequence); ``logged_match`` needs the Stage 7 label mapping;
    return ``ModelNoAnswer`` (``not_recorded``, ``target_not_logged_model``,
    ``label_unmapped``) when nothing matches.
    """

    def __init__(self, source: AnswerSource) -> None:
        if source not in (AnswerSource.LOGGED, AnswerSource.RECORDED):
            raise ValueError("replay sources are logged or recorded")
        self._source = source

    @property
    def source(self) -> AnswerSource:
        return self._source

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        raise NotImplementedError("TODO(Stage 8): replay lookup")
