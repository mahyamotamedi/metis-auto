"""``ModelClient``: the one way the system obtains a model answer (CMP-10).

Called by: application.pipeline (attempts), application.measurement (model-based
features, later). Implemented by: adapters.providers (fake, fault- and
quality-injecting decorators; replay, recording, and live clients later).
Contracts: ``ModelInvocation`` in, ``ModelResult`` out (providers.md §1).
Traces: FR-API-02, FR-FAIL-06, ADR-0003, ADR-0013, ADR-0014.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from metis_auto.contracts import AnswerSource, ModelInvocation, ModelResult


@runtime_checkable
class ModelClient(Protocol):
    """Answers one invocation. Synchronous (ADR-0010).

    Provider failures come back as ``ModelError`` and missing counterfactual
    answers as ``ModelNoAnswer``; an exception means a programming or
    configuration error. Adapters never retry internally (ADR-0013): every
    attempt is the pipeline's, so it is recorded and charged.
    """

    @property
    def source(self) -> AnswerSource:
        """Which counterfactual source this client is (ADR-0014). The pipeline
        applies the spend guard only to ``live`` clients."""
        ...

    def invoke(self, invocation: ModelInvocation) -> ModelResult: ...
