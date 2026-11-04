"""``ReplayFirstClient``: answer from recordings when possible, else live
(ADR-0014; P-1 "every answer is recorded so a rerun costs nothing").

``invoke`` asks the recorded-answer replay first (``ReplayModelClient``
built with ``recorded_from``: same model and same exact input). A recorded
response is returned as it was recorded (``source = recorded``: measured, no
new spend). Only a ``ModelNoAnswer`` from the replay goes to the live client,
which the caller wraps in the recording decorator and the spend guard. The
client's own ``source`` is the live client's (``live``), so the E4 harness
still requires the owner's live approval for the run; the counts of replayed
and live calls are kept for the run summary.
A recorded reply that was cut off at its limit with empty text is not replayed;
the live client is asked again.

Implements ``ports.ModelClient``. Built by: wiring.benchmark. Status:
provisional.
"""

from __future__ import annotations

from metis_auto.contracts import (
    AnswerSource,
    FinishReason,
    ModelInvocation,
    ModelNoAnswer,
    ModelResponse,
    ModelResult,
)
from metis_auto.ports import ModelClient


class ReplayFirstClient:
    def __init__(self, replay: ModelClient, live: ModelClient) -> None:
        if replay.source != AnswerSource.RECORDED:
            raise ValueError("the replay side must be a recorded-answer client")
        self._replay = replay
        self._live = live
        self.replayed = 0
        self.live_calls = 0

    @property
    def source(self) -> AnswerSource:
        return self._live.source

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        recorded = self._replay.invoke(invocation)
        if not isinstance(recorded, ModelNoAnswer) and not _cut_off_empty(recorded):
            self.replayed += 1
            return recorded
        self.live_calls += 1
        return self._live.invoke(invocation)


def _cut_off_empty(result: ModelResult) -> bool:
    """A recorded reply that hit its output limit with no visible text (a model
    that spent the limit on hidden reasoning). It carries no answer, so a
    rerun asks again instead of replaying it."""
    return (
        isinstance(result, ModelResponse)
        and result.finish_reason == FinishReason.LENGTH
        and not result.text.strip()
    )
