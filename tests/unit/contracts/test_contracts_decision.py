"""Decision-router contracts (ADR-XXXX (system-one-decision-router)): shape rules that
keep answers typed, outcomes consistent, and the local cost honest. All text is
SYNTHETIC."""

from decimal import Decimal

import pytest
from fixtures.synthetic import contract_examples as ex
from pydantic import ValidationError

from metis_auto.contracts import (
    AvailabilityReason,
    BackendAttempt,
    BackendAvailability,
    Component,
    ComponentState,
    Cost,
    CostBasis,
    CostStatus,
    DecisionAnswer,
    DecisionError,
    DecisionFailureReason,
    DecisionOption,
    DecisionOutcome,
    DecisionQuestion,
    DecisionQuestionSet,
    DecisionQuestionType,
    DecisionSkipReason,
    DecisionState,
    DecisionStatus,
    ErrorClass,
    Language,
    LastAssistantTurnKind,
    Money,
    QuestionLanguage,
    RouterPath,
    RouterSummary,
)

CHOICE = DecisionQuestionType.CHOICE
SCORE = DecisionQuestionType.SCORE
NOUL = DecisionQuestionType.NOUL


def opt(name: str) -> DecisionOption:
    return DecisionOption(name=name, description=f"Option {name}.")


# --- Questions --------------------------------------------------------------------


def test_question_shapes_by_type():
    DecisionQuestion(
        id="q", type=CHOICE, instructions="Q?", options=(opt("a"), opt("b"))
    )
    DecisionQuestion(id="q", type=SCORE, instructions="Q?", levels=("low", "high"))
    DecisionQuestion(id="q", type=NOUL, instructions="Condition.")
    with pytest.raises(ValidationError):
        DecisionQuestion(id="q", type=CHOICE, instructions="Q?", options=(opt("a"),))
    with pytest.raises(ValidationError):
        DecisionQuestion(
            id="q", type=CHOICE, instructions="Q?", options=(opt("a"), opt("a"))
        )
    with pytest.raises(ValidationError):
        DecisionQuestion(id="q", type=SCORE, instructions="Q?", levels=("only",))
    with pytest.raises(ValidationError):
        DecisionQuestion(id="q", type=NOUL, instructions="Q?", levels=("a", "b"))
    with pytest.raises(ValidationError):
        DecisionQuestion(id="q", type=NOUL, instructions="   ")


def test_question_set_needs_unique_ids():
    q = DecisionQuestion(id="q", type=NOUL, instructions="Condition.")
    with pytest.raises(ValidationError):
        DecisionQuestionSet(
            version="v", language_variant=QuestionLanguage.ENGLISH, questions=(q, q)
        )
    with pytest.raises(ValidationError):
        DecisionQuestionSet(
            version="v", language_variant=QuestionLanguage.ENGLISH, questions=()
        )
    qs = ex.decision_question_set()
    assert qs.get("intent") is not None and qs.get("missing") is None


# --- Answers ----------------------------------------------------------------------


def test_answers_set_exactly_their_type_fields():
    DecisionAnswer(question_id="q", type=NOUL, p_yes=0.3)
    with pytest.raises(ValidationError):
        DecisionAnswer(question_id="q", type=NOUL, p_yes=0.3, score=1.0)
    with pytest.raises(ValidationError):
        DecisionAnswer(question_id="q", type=NOUL, p_yes=1.3)
    with pytest.raises(ValidationError):
        DecisionAnswer(question_id="q", type=SCORE, p_yes=0.3)
    with pytest.raises(ValidationError):
        DecisionAnswer(question_id="q", type=CHOICE, score=1.0)
    with pytest.raises(ValidationError):
        DecisionAnswer(question_id="q", type=NOUL, p_yes=0.5, probabilities={"a": 1.0})


def test_choice_must_be_among_its_probabilities():
    with pytest.raises(ValidationError):
        DecisionAnswer(
            question_id="q", type=CHOICE, choice="c", probabilities={"a": 0.5, "b": 0.5}
        )


@pytest.mark.parametrize("probs", [{"a": 0.5, "b": 0.3}, {"a": 0.9, "b": 0.9}])
def test_probabilities_must_sum_to_one(probs):
    with pytest.raises(ValidationError):
        DecisionAnswer(question_id="q", type=CHOICE, choice="a", probabilities=probs)


def test_rounding_within_tolerance_is_accepted():
    DecisionAnswer(
        question_id="q", type=CHOICE, choice="a", probabilities={"a": 0.333, "b": 0.664}
    )


def test_score_without_probabilities_is_valid():
    # The Metis page's example score answer has no probabilities (2026-11-02).
    a = DecisionAnswer(question_id="q", type=SCORE, score=1.0, confidence=1.0)
    assert a.probabilities == {}


def test_result_has_one_answer_per_question():
    result = ex.decision_result()
    with pytest.raises(ValidationError):
        type(result).model_validate(
            result.model_dump() | {"answers": [result.answers[0].model_dump()] * 2}
        )
    assert result.answer("intent").choice == "other"


# --- Errors, availability, cost --------------------------------------------------


def test_error_is_either_an_error_class_or_invalid_response():
    DecisionError(backend=ex.BACKEND, error_class=ErrorClass.TIMEOUT, latency_ms=1)
    DecisionError(backend=ex.BACKEND, invalid_response=True, latency_ms=1)
    with pytest.raises(ValidationError):
        DecisionError(backend=ex.BACKEND, latency_ms=1)
    with pytest.raises(ValidationError):
        DecisionError(
            backend=ex.BACKEND,
            error_class=ErrorClass.AUTH,
            invalid_response=True,
            latency_ms=1,
        )


def test_availability_reason_iff_unavailable():
    assert BackendAvailability.ok().available
    down = BackendAvailability.unavailable(AvailabilityReason.MISSING_ASSETS)
    assert not down.available
    with pytest.raises(ValidationError):
        BackendAvailability(available=True, reason=AvailabilityReason.DISABLED)


def test_local_compute_cost_is_zero_without_a_price_table():
    zero = Money(amount=Decimal("0"), currency="USD")
    cost = Cost(status=CostStatus.COMPUTED, basis=CostBasis.LOCAL_COMPUTE, amount=zero)
    assert cost.price_table_version is None
    with pytest.raises(ValidationError):
        Cost(
            status=CostStatus.COMPUTED,
            basis=CostBasis.LOCAL_COMPUTE,
            amount=Money(amount=Decimal("0.01"), currency="USD"),
        )
    with pytest.raises(ValidationError):  # other bases still need the table
        Cost(status=CostStatus.COMPUTED, basis=CostBasis.ACTUAL, amount=zero)


# --- Outcomes ---------------------------------------------------------------------


def test_outcome_examples_are_consistent():
    answered, skipped, failed, cached = ex.decision_outcomes()
    assert answered.result is not None and skipped.rule_id == "gate.greeting"
    assert failed.error_class == ErrorClass.TIMEOUT and cached.attempts == ()


@pytest.mark.parametrize(
    "fields",
    [
        {"status": DecisionStatus.ANSWERED},  # no result
        {"status": DecisionStatus.SKIPPED},  # no skip reason
        {"status": DecisionStatus.FAILED},  # no failure reason
        {
            "status": DecisionStatus.FAILED,
            "failure_reason": DecisionFailureReason.ERROR,
        },  # error without its class
        {
            "status": DecisionStatus.FAILED,
            "failure_reason": DecisionFailureReason.TIMEOUT,
            "rule_id": "gate.x",
        },  # rule only when rules were decisive
        {
            "status": DecisionStatus.SKIPPED,
            "skip_reason": DecisionSkipReason.MODE_OFF,
            "attempts": (
                BackendAttempt(backend=ex.BACKEND, answered=True, latency_ms=1.0),
            ),
        },  # skipped yet tried a backend
        {
            "status": DecisionStatus.FAILED,
            "failure_reason": DecisionFailureReason.TIMEOUT,
            "soft_result": ex.decision_result(),
        },  # soft signals only on low confidence
    ],
)
def test_inconsistent_outcomes_are_rejected(fields):
    with pytest.raises(ValidationError):
        DecisionOutcome(**fields)


def test_a_cache_hit_tried_no_backend():
    with pytest.raises(ValidationError):
        DecisionOutcome(
            status=DecisionStatus.ANSWERED,
            result=ex.decision_result(cache_hit=True),
            attempts=(BackendAttempt(backend=ex.BACKEND, answered=True, latency_ms=1),),
        )


def test_low_confidence_may_keep_soft_signals():
    DecisionOutcome(
        status=DecisionStatus.FAILED,
        failure_reason=DecisionFailureReason.LOW_CONFIDENCE,
        soft_result=ex.decision_result(),
    )


def test_backend_attempt_rules():
    with pytest.raises(ValidationError):
        BackendAttempt(backend=ex.BACKEND, answered=False, latency_ms=1)
    with pytest.raises(ValidationError):
        BackendAttempt(
            backend=ex.BACKEND,
            answered=False,
            failure_reason=DecisionFailureReason.TIMEOUT,
            error_class=ErrorClass.TIMEOUT,
            latency_ms=1,
        )


def test_router_summary_is_content_free_and_optional_on_routing():
    assert ex.routing_decision().router_summary is None
    summary = ex.routing_decision_with_router().router_summary
    assert summary == RouterSummary(
        path=RouterPath.SLOW_LOCAL,
        backend=ex.BACKEND,
        mapped_tier=0,
        thresholds_fired=("tau_ok",),
        reasoning_effort="minimal",
    )


# --- State ------------------------------------------------------------------------


def test_state_needs_a_message_and_no_previous_turn_on_a_first_turn():
    base = {
        "last_assistant_turn_kind": LastAssistantTurnKind.NONE,
        "retrieved_state": ComponentState.ABSENT,
        "language": Language.ENGLISH,
    }
    DecisionState(message=f"{ex.MARKER} hi", turn_depth=0, **base)
    with pytest.raises(ValidationError):
        DecisionState(message="   ", turn_depth=0, **base)
    with pytest.raises(ValidationError):
        DecisionState(
            message=f"{ex.MARKER} hi",
            turn_depth=0,
            previous_user_turn=Component.present(f"{ex.MARKER} earlier"),
            **base,
        )


def test_state_defaults_to_not_dataset_derived():
    assert ex.decision_state().dataset_derived is False
