"""Fake judge: a fixed score, or "unmeasured". Carries no quality signal.
Implements ``ports.Judge``. Status: test double; real judges TODO(Stage 8)."""

from __future__ import annotations

from metis_auto.contracts import (
    JudgeScore,
    MetricState,
    ModelResponse,
    Request,
    Version,
)


class FakeJudge:
    def __init__(self, score: float | None = None) -> None:
        self._score = score

    @property
    def judge_id(self) -> Version:
        return "fake-judge@1.0.0"

    def score(self, request: Request, response: ModelResponse) -> JudgeScore:
        if self._score is None:
            return JudgeScore(
                judge=self.judge_id,
                rubric="none",
                state=MetricState.UNMEASURED,
                reason="fake_judge",
            )
        return JudgeScore(
            judge=self.judge_id,
            rubric="none",
            state=MetricState.MEASURED,
            score=self._score,
        )
