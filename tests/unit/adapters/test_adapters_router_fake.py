"""The fake decision backend (ADR-0047): deterministic,
scripted, honest about time and cost, and never reads the state. SYNTHETIC only."""

from datetime import UTC, datetime

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.routers import FakeDecisionBackend
from metis_auto.adapters.system import FakeClock
from metis_auto.contracts import (
    AvailabilityReason,
    BackendAvailability,
    BackendKind,
    CostBasis,
    CostStatus,
    DecisionError,
    DecisionLatencySource,
    DecisionResult,
    ErrorClass,
)
from metis_auto.ports import BaseRouter

QS = ex.decision_question_set()
STATE = ex.decision_state()


def clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 2, tzinfo=UTC))


def test_implements_the_port():
    assert isinstance(FakeDecisionBackend(clock()), BaseRouter)


def test_neutral_answers_cover_every_question():
    result = FakeDecisionBackend(clock()).decide(STATE, QS, timeout_ms=60)
    assert isinstance(result, DecisionResult)
    assert [a.question_id for a in result.answers] == [q.id for q in QS.questions]
    assert result.answer("complexity").score == 1.0  # middle of 0..3, rounded down
    assert result.answer("needs_reasoning").p_yes == 0.5
    assert result.answer("intent").choice == "chitchat"  # first option
    assert result.question_set_version == QS.version
    assert result.usage is None


def test_scripted_answers():
    backend = FakeDecisionBackend(
        clock(), script={"complexity": 3, "needs_reasoning": 0.9, "intent": "code"}
    )
    result = backend.decide(STATE, QS, timeout_ms=60)
    assert result.answer("complexity").score == 3.0
    assert result.answer("needs_reasoning").p_yes == 0.9
    assert result.answer("intent").choice == "code"
    assert sum(result.answer("intent").probabilities.values()) == pytest.approx(1)


@pytest.mark.parametrize(
    "script", [{"intent": "nope"}, {"complexity": 7}, {"needs_reasoning": 2}]
)
def test_a_bad_script_is_a_programming_error(script):
    with pytest.raises(ValueError):
        FakeDecisionBackend(clock(), script=script).decide(STATE, QS, timeout_ms=60)


def test_latency_is_measured_and_an_overrun_is_a_timeout_with_its_duration():
    fast = FakeDecisionBackend(clock(), latency_ms=20).decide(STATE, QS, timeout_ms=60)
    assert fast.latency_ms == 20
    assert fast.latency_source == DecisionLatencySource.MEASURED_LOCAL
    slow = FakeDecisionBackend(clock(), latency_ms=90).decide(STATE, QS, timeout_ms=60)
    assert isinstance(slow, DecisionError)
    assert slow.error_class == ErrorClass.TIMEOUT and slow.latency_ms == 90


def test_injected_failures_are_consumed_in_order():
    backend = FakeDecisionBackend(
        clock(), failures=[ErrorClass.RATE_LIMITED, "invalid_response", None]
    )
    first = backend.decide(STATE, QS, timeout_ms=60)
    second = backend.decide(STATE, QS, timeout_ms=60)
    third = backend.decide(STATE, QS, timeout_ms=60)
    fourth = backend.decide(STATE, QS, timeout_ms=60)
    assert first.error_class == ErrorClass.RATE_LIMITED
    assert second.invalid_response is True
    assert isinstance(third, DecisionResult) and isinstance(fourth, DecisionResult)
    assert backend.calls == 4


def test_local_cost_is_zero_and_hosted_cost_is_not_computed():
    local = FakeDecisionBackend(clock()).decide(STATE, QS, timeout_ms=60)
    assert local.cost.basis == CostBasis.LOCAL_COMPUTE
    assert local.cost.amount.amount == 0
    hosted_backend = FakeDecisionBackend(clock(), kind="hosted")
    hosted = hosted_backend.decide(STATE, QS, timeout_ms=60)
    assert hosted.backend_kind == BackendKind.HOSTED
    assert hosted.cost.status == CostStatus.NOT_COMPUTED
    assert hosted.latency_source == DecisionLatencySource.MEASURED_REMOTE
    estimate = hosted_backend.estimate_cost(120)
    assert estimate.input_tokens.tokens == 120
    assert estimate.cost.status == CostStatus.NOT_COMPUTED
    assert FakeDecisionBackend(clock()).estimate_cost(120) is None


def test_availability_is_reported_as_configured():
    down = BackendAvailability.unavailable(AvailabilityReason.MISSING_ASSETS)
    assert FakeDecisionBackend(clock(), availability=down).available() == down


def test_results_never_carry_the_state():
    result = FakeDecisionBackend(clock()).decide(STATE, QS, timeout_ms=60)
    assert ex.MARKER not in result.model_dump_json()
