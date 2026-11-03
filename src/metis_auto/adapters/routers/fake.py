"""Fake System-One decision backend: scripted, deterministic
(ADR-0047).

Responsibility: let the router cascade, the pipeline and the chat demo run
offline with no weights and no keys. Implements ``ports.BaseRouter``.

- Answers every question: a scripted value per question ID when given
  (``float`` for score and noul, option name for choice), otherwise a neutral
  answer (first option, middle level, P(yes) = 0.5).
- Latency comes from a fake ``Clock``: the call advances it by
  ``latency_ms``. Like an in-process model it cannot be pre-empted: a call
  slower than ``timeout_ms`` still takes its full time and is then reported
  as a timeout with that duration.
- Injected failures are consumed one per call, in order (``None`` = answer).
- Reports no usage (``usage=None``). Cost: local → zero (``local_compute``);
  hosted → not computed (no price), unless a cost is supplied.

Never reads or stores the state's text. Built by: tests, wiring (R4).
Status: test double.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Literal

from metis_auto.contracts import (
    BackendAvailability,
    BackendKind,
    Cost,
    CostBasis,
    CostEstimate,
    CostStatus,
    DecisionAnswer,
    DecisionError,
    DecisionLatencySource,
    DecisionQuestion,
    DecisionQuestionSet,
    DecisionQuestionType,
    DecisionResult,
    DecisionState,
    ErrorClass,
    Fidelity,
    Money,
    NotComputedReason,
    PolicyRef,
    TokenCount,
)
from metis_auto.ports import Clock

ScriptValue = float | str
InjectedFailure = ErrorClass | Literal["invalid_response"] | None

_PEAK = 0.7
"""Probability mass the fake puts on its chosen option or level."""


def local_zero_cost() -> Cost:
    return Cost(
        status=CostStatus.COMPUTED,
        basis=CostBasis.LOCAL_COMPUTE,
        amount=Money(amount=Decimal("0"), currency="USD"),
    )


def _not_computed() -> Cost:
    return Cost(
        status=CostStatus.NOT_COMPUTED,
        basis=CostBasis.ACTUAL,
        reason=NotComputedReason.PRICE_UNKNOWN,
    )


def _peaked(names: tuple[str, ...], chosen: str) -> dict[str, float]:
    if len(names) == 1:
        return {chosen: 1.0}
    rest = (1.0 - _PEAK) / (len(names) - 1)
    return {n: (_PEAK if n == chosen else rest) for n in names}


def neutral_answer(question: DecisionQuestion) -> ScriptValue:
    if question.type == DecisionQuestionType.CHOICE:
        return question.options[0].name
    if question.type == DecisionQuestionType.SCORE:
        return float((len(question.levels) - 1) // 2)
    return 0.5


def answer_for(question: DecisionQuestion, value: ScriptValue) -> DecisionAnswer:
    """A well-formed answer of ``question``'s type carrying ``value``."""
    if question.type == DecisionQuestionType.CHOICE:
        if not isinstance(value, str) or value not in question.option_names:
            raise ValueError(f"fake script: {question.id!r} needs one of its options")
        return DecisionAnswer(
            question_id=question.id,
            type=question.type,
            choice=value,
            probabilities=_peaked(question.option_names, value),
            confidence=_PEAK,
        )
    if isinstance(value, str):
        raise ValueError(f"fake script: {question.id!r} needs a number")
    if question.type == DecisionQuestionType.SCORE:
        top = len(question.levels) - 1
        if not 0 <= value <= top:
            raise ValueError(f"fake script: {question.id!r} score outside 0..{top}")
        levels = tuple(str(i) for i in range(top + 1))
        return DecisionAnswer(
            question_id=question.id,
            type=question.type,
            score=float(value),
            probabilities=_peaked(levels, str(round(value))),
            confidence=_PEAK,
        )
    if not 0 <= value <= 1:
        raise ValueError(f"fake script: {question.id!r} p_yes outside 0..1")
    return DecisionAnswer(question_id=question.id, type=question.type, p_yes=value)


class FakeDecisionBackend:
    """Scripted decision backend for tests and offline demos."""

    def __init__(
        self,
        clock: Clock,
        *,
        name: str = "fake",
        version: str = "0.0.0-synthetic",
        kind: Literal["hosted", "local"] = "local",
        latency_ms: float = 0.0,
        script: Mapping[str, ScriptValue] | None = None,
        failures: Iterable[InjectedFailure] = (),
        availability: BackendAvailability | None = None,
        calibrated: bool = True,
        cost: Cost | None = None,
    ) -> None:
        self._clock = clock
        self._ref = PolicyRef(name=name, version=version)
        self._kind: Literal["hosted", "local"] = kind
        self._latency_ms = latency_ms
        self._script = dict(script or {})
        self._failures: deque[InjectedFailure] = deque(failures)
        self._availability = availability or BackendAvailability.ok()
        self._calibrated = calibrated
        self._cost = cost
        self.calls = 0

    @property
    def ref(self) -> PolicyRef:
        return self._ref

    @property
    def kind(self) -> Literal["hosted", "local"]:
        return self._kind

    def available(self) -> BackendAvailability:
        return self._availability

    def estimate_cost(self, state_tokens: int) -> CostEstimate | None:
        if self._kind == "local":
            return None
        return CostEstimate(
            model_id=self._ref.name,
            input_tokens=TokenCount(
                tokens=state_tokens,
                fidelity=Fidelity.APPROXIMATION,
                method="fake-backend@1",
            ),
            assumed_output_tokens=0,
            cost=self._cost
            or Cost(
                status=CostStatus.NOT_COMPUTED,
                basis=CostBasis.PRE_CALL_ESTIMATE,
                reason=NotComputedReason.PRICE_UNKNOWN,
            ),
        )

    def decide(
        self,
        state: DecisionState,
        questions: DecisionQuestionSet,
        *,
        timeout_ms: float,
    ) -> DecisionResult | DecisionError:
        del state  # never read: the fake's answers do not depend on content
        self.calls += 1
        start = self._clock.monotonic_ms()
        self._clock.sleep_ms(self._latency_ms)
        elapsed = self._clock.monotonic_ms() - start
        failure = self._failures.popleft() if self._failures else None
        if elapsed > timeout_ms:
            failure = ErrorClass.TIMEOUT
        if failure == "invalid_response":
            return DecisionError(
                backend=self._ref, invalid_response=True, latency_ms=elapsed
            )
        if failure is not None:
            return DecisionError(
                backend=self._ref, error_class=failure, latency_ms=elapsed
            )
        answers = tuple(
            answer_for(q, self._script.get(q.id, neutral_answer(q)))
            for q in questions.questions
        )
        local = self._kind == "local"
        return DecisionResult(
            answers=answers,
            backend=self._ref,
            backend_kind=BackendKind.LOCAL if local else BackendKind.HOSTED,
            model_revision=self._ref.version,
            question_set_version=questions.version,
            latency_ms=elapsed,
            latency_source=DecisionLatencySource.MEASURED_LOCAL
            if local
            else DecisionLatencySource.MEASURED_REMOTE,
            usage=None,
            cost=self._cost or (local_zero_cost() if local else _not_computed()),
            calibrated=self._calibrated,
        )
