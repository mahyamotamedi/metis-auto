"""Attempt policy state machine (ADR-0013, attempts.md §2–§3) and detectors."""

from fixtures.synthetic import contract_examples as ex

from metis_auto.contracts import (
    ActionKind,
    AnswerSource,
    AttemptKind,
    AttemptOutcome,
    AttemptRecord,
    AttemptState,
    ErrorClass,
    FailureReason,
    FinishReason,
    ModelCatalogue,
    ModelResponse,
)
from metis_auto.domain.attempts import (
    AttemptPolicyConfig,
    EmptyOutputDetector,
    TruncationDetector,
    is_unsatisfactory,
    next_action,
    run_detectors,
)

CONFIG = AttemptPolicyConfig()
SMALL_B = "synthetic-small-b"
# Two tier-0 models in one group (different providers), one tier-1 model.
CATALOGUE = ModelCatalogue(
    version="v",
    entries=(
        ex.model_catalogue().entries[0],
        ex.model_catalogue()
        .entries[0]
        .model_copy(update={"model_id": SMALL_B, "provider": "synthetic-provider-b"}),
        ex.model_catalogue().entries[1],
    ),
)
DECISION = ex.routing_decision().model_copy(
    update={"eligible": (ex.MODEL, SMALL_B, ex.MODEL_LARGE)}
)


def _record(n, model, outcome, kind=AttemptKind.PRIMARY, **kw) -> AttemptRecord:
    return AttemptRecord(
        attempt_id=f"att-{n}",
        number=n,
        kind=kind,
        model_id=model,
        provider="p",
        outcome=outcome,
        **kw,
    )


def _ok(n, model, unsatisfactory=False, kind=AttemptKind.PRIMARY):
    return _record(
        n,
        model,
        AttemptOutcome.RESPONSE,
        kind,
        finish_reason=FinishReason.COMPLETE,
        unsatisfactory=unsatisfactory,
    )


def _err(n, model, error, kind=AttemptKind.PRIMARY):
    return _record(n, model, AttemptOutcome.ERROR, kind, error_class=error)


def _next(*records, **state):
    s = AttemptState(request_id="req-1", decision=DECISION, attempts=records, **state)
    return next_action(s, CATALOGUE, CONFIG)


def test_primary_then_return():
    first = _next()
    assert (first.action, first.kind, first.target_model_id) == (
        ActionKind.INVOKE,
        AttemptKind.PRIMARY,
        ex.MODEL,
    )
    done = _next(_ok(0, ex.MODEL))
    assert done.action == ActionKind.RETURN and done.return_attempt_id == "att-0"


def test_no_target_fails():
    decision = DECISION.model_copy(
        update={
            "target_model_id": None,
            "equivalence_group": None,
            "tier": None,
            "reason_code": "no_eligible_model",
        }
    )
    state = AttemptState(request_id="req-1", decision=decision)
    assert next_action(state, CATALOGUE, CONFIG).failure == (
        FailureReason.NO_ELIGIBLE_MODEL
    )


def test_retryable_error_retries_with_backoff_then_fails_over():
    timeout = ErrorClass.TIMEOUT
    retry = _next(_err(0, ex.MODEL, timeout))
    assert retry.kind == AttemptKind.RETRY and retry.backoff_ms == 200.0
    history = (
        _err(0, ex.MODEL, timeout),
        _err(1, ex.MODEL, timeout, AttemptKind.RETRY),
        _err(2, ex.MODEL, timeout, AttemptKind.RETRY),
    )
    failover = _next(*history)
    assert failover.kind == AttemptKind.FAILOVER
    assert failover.target_model_id == SMALL_B  # same group, other provider


def test_non_retryable_error_fails_without_retry():
    action = _next(_err(0, ex.MODEL, ErrorClass.AUTH))
    assert action.failure == FailureReason.ALL_ATTEMPTS_FAILED


def test_unsatisfactory_answer_escalates_then_returns_best_flagged():
    escalate = _next(_ok(0, ex.MODEL, unsatisfactory=True))
    assert escalate.kind == AttemptKind.ESCALATION
    assert escalate.target_model_id == ex.MODEL_LARGE
    flagged = _next(
        _ok(0, ex.MODEL, unsatisfactory=True),
        _ok(1, ex.MODEL_LARGE, unsatisfactory=True, kind=AttemptKind.ESCALATION),
    )
    assert flagged.action == ActionKind.RETURN
    assert flagged.unsatisfactory_returned and flagged.return_attempt_id == "att-1"


def test_no_answer_is_never_retried():
    action = _next(_record(0, ex.MODEL, AttemptOutcome.NO_ANSWER))
    assert action.failure == FailureReason.NO_ANSWER


def test_deadline_returns_best_answer_so_far():
    action = _next(_ok(0, ex.MODEL, unsatisfactory=True), deadline_remaining_ms=0)
    assert action.action == ActionKind.RETURN and action.unsatisfactory_returned


def test_detectors():
    def response(text, finish):
        return ModelResponse(text=text, finish_reason=finish, source=AnswerSource.FAKE)

    detectors = (TruncationDetector(), EmptyOutputDetector())
    good = run_detectors(response("[SYNTHETIC] ok", FinishReason.COMPLETE), detectors)
    assert not is_unsatisfactory(good)
    cut = run_detectors(response("[SYNTHETIC] ok", FinishReason.LENGTH), detectors)
    empty = run_detectors(response("  ", FinishReason.COMPLETE), detectors)
    assert is_unsatisfactory(cut) and is_unsatisfactory(empty)
