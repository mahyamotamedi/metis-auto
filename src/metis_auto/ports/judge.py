"""``Judge``: scores an answer on a rubric (CMP-15).

Called by: evaluation.metrics (offline, evaluation cost) and, later,
application.measurement (runtime detector input, request overhead).
Implemented by: adapters.judges (fake now; LLM judge and human-label import
later, opt-in). Traces: FR-EVAL-05, FR-CASC-02, ADR-0006.

TODO(Stage 8, contracts.md O-6): the judge *input* contract (rubric,
reference handling) is open; ``Request`` + ``ModelResponse`` is provisional.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from metis_auto.contracts import JudgeScore, ModelResponse, Request, Version


@runtime_checkable
class Judge(Protocol):
    @property
    def judge_id(self) -> Version:
        """``ID@version``, recorded with every score."""
        ...

    def score(self, request: Request, response: ModelResponse) -> JudgeScore: ...
