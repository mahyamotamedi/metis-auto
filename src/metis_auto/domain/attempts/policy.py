"""The attempt policy (CMP-08; attempts.md §1–§3, ADR-0013).

Responsibility: from the full ``AttemptState``, decide the next action:
invoke a target (primary, retry, failover, escalation), return an answer, or
fail. The pipeline executes it. Pure and deterministic.
Called by: application.pipeline (stage 6). Calls: contracts only.
Config: ``AttemptPolicyConfig`` (limits and error-class actions are
provisional configuration). Traces: FR-CASC-01…05, FR-FAIL-01…04, A-20.

Status: reference state machine. TODO: ``context_overflow`` errors rebuild the
context or re-route (now: fail); "best answer so far" ranking by detector
scores (now: most recent successful answer); provider health (FR-FAIL-05).
"""

from __future__ import annotations

from enum import StrEnum

from metis_auto.contracts import (
    ActionKind,
    AttemptAction,
    AttemptKind,
    AttemptOutcome,
    AttemptRecord,
    AttemptState,
    ContractModel,
    ErrorClass,
    FailureReason,
    ModelCatalogue,
    Name,
)


class ErrorAction(StrEnum):
    RETRY_THEN_FAILOVER = "retry_then_failover"
    FAILOVER = "failover"
    FAIL = "fail"


DEFAULT_ERROR_ACTIONS: dict[ErrorClass, ErrorAction] = {
    ErrorClass.TIMEOUT: ErrorAction.RETRY_THEN_FAILOVER,
    ErrorClass.RATE_LIMITED: ErrorAction.RETRY_THEN_FAILOVER,
    ErrorClass.UNAVAILABLE: ErrorAction.RETRY_THEN_FAILOVER,
    ErrorClass.CONNECTION: ErrorAction.RETRY_THEN_FAILOVER,
    ErrorClass.UNKNOWN: ErrorAction.RETRY_THEN_FAILOVER,
    ErrorClass.CONTEXT_OVERFLOW: ErrorAction.FAIL,
    ErrorClass.CONTENT_FILTERED: ErrorAction.FAIL,
    ErrorClass.INVALID_REQUEST: ErrorAction.FAIL,
    ErrorClass.AUTH: ErrorAction.FAIL,
}
"""attempts.md §3 defaults, except ``context_overflow`` (TODO: rebuild/re-route)."""

_ERROR_FAILURE = {
    ErrorClass.CONTEXT_OVERFLOW: FailureReason.CONTEXT_OVERFLOW,
    ErrorClass.CONTENT_FILTERED: FailureReason.CONTENT_FILTERED,
}


class AttemptPolicyConfig(ContractModel):
    """Bounds (FR-FAIL-04, FR-CASC-03). Values are provisional defaults."""

    version: str = "0.1.0"
    max_attempts: int = 6
    max_retries_per_model: int = 2
    unknown_error_max_retries: int = 1
    backoff_ms: tuple[float, ...] = (200.0, 800.0)
    """Wait before retry n (the last value repeats)."""
    max_escalation_depth: int = 1
    error_actions: dict[ErrorClass, ErrorAction] = DEFAULT_ERROR_ACTIONS
    detectors: tuple[Name, ...] = ("truncation", "empty_output")
    """Enabled detectors; wiring maps names to implementations."""


def next_action(
    state: AttemptState, catalogue: ModelCatalogue, config: AttemptPolicyConfig
) -> AttemptAction:
    decision = state.decision
    if decision.target_model_id is None:
        return _fail(FailureReason.NO_ELIGIBLE_MODEL)
    if not state.attempts:
        return _invoke(decision.target_model_id, AttemptKind.PRIMARY, "primary")
    if state.deadline_remaining_ms is not None and state.deadline_remaining_ms <= 0:
        return _best_or_fail(state, FailureReason.DEADLINE_EXCEEDED)
    if len(state.attempts) >= config.max_attempts:
        return _best_or_fail(state, FailureReason.ALL_ATTEMPTS_FAILED)

    last = state.attempts[-1]
    if last.outcome == AttemptOutcome.RESPONSE:
        if not last.unsatisfactory:
            return AttemptAction(
                action=ActionKind.RETURN,
                reason="satisfactory",
                return_attempt_id=last.attempt_id,
            )
        target = _next_escalation(state, config)
        if target is not None:
            return _invoke(target, AttemptKind.ESCALATION, "unsatisfactory")
        return _best_or_fail(state, FailureReason.ALL_ATTEMPTS_FAILED)
    if last.outcome == AttemptOutcome.NO_ANSWER:
        # A coverage gap, never retried or failed over (ADR-0014).
        return _best_or_fail(state, FailureReason.NO_ANSWER)
    if last.outcome == AttemptOutcome.BUDGET_BLOCKED:
        return _best_or_fail(state, FailureReason.BUDGET_EXHAUSTED)

    error = last.error_class or ErrorClass.UNKNOWN
    action = config.error_actions.get(error, ErrorAction.FAIL)
    if action == ErrorAction.FAIL:
        reason = _ERROR_FAILURE.get(error, FailureReason.ALL_ATTEMPTS_FAILED)
        return _best_or_fail(state, reason)
    if action == ErrorAction.RETRY_THEN_FAILOVER:
        retries = _retries_on(state.attempts, last.model_id)
        limit = (
            config.unknown_error_max_retries
            if error == ErrorClass.UNKNOWN
            else config.max_retries_per_model
        )
        if retries < limit:
            backoff = config.backoff_ms[min(retries, len(config.backoff_ms) - 1)]
            return _invoke(
                last.model_id, AttemptKind.RETRY, f"retry_{error.value}", backoff
            )
    failover = _failover_target(state, catalogue, last)
    if failover is not None:
        return _invoke(failover, AttemptKind.FAILOVER, f"failover_{error.value}")
    return _best_or_fail(state, FailureReason.ALL_ATTEMPTS_FAILED)


def _invoke(
    model_id: str, kind: AttemptKind, reason: str, backoff_ms: float | None = None
) -> AttemptAction:
    return AttemptAction(
        action=ActionKind.INVOKE,
        reason=reason,
        target_model_id=model_id,
        kind=kind,
        backoff_ms=backoff_ms,
    )


def _fail(reason: FailureReason) -> AttemptAction:
    return AttemptAction(action=ActionKind.FAIL, reason=reason.value, failure=reason)


def _best_or_fail(state: AttemptState, reason: FailureReason) -> AttemptAction:
    """Return the most recent successful answer, flagged, or fail (attempts.md §2)."""
    best = next(
        (a for a in reversed(state.attempts) if a.outcome == AttemptOutcome.RESPONSE),
        None,
    )
    if best is None:
        return _fail(reason)
    return AttemptAction(
        action=ActionKind.RETURN,
        reason=f"best_after_{reason.value}",
        return_attempt_id=best.attempt_id,
        unsatisfactory_returned=bool(best.unsatisfactory),
    )


def _retries_on(attempts: tuple[AttemptRecord, ...], model_id: str) -> int:
    """Consecutive retries on ``model_id`` at the end of the history."""
    count = 0
    for a in reversed(attempts):
        if a.model_id != model_id or a.kind != AttemptKind.RETRY:
            break
        count += 1
    return count


def _next_escalation(state: AttemptState, config: AttemptPolicyConfig) -> str | None:
    done = sum(1 for a in state.attempts if a.kind == AttemptKind.ESCALATION)
    chain = state.decision.chain
    if done >= config.max_escalation_depth or done >= len(chain):
        return None
    return chain[done]


def _failover_target(
    state: AttemptState, catalogue: ModelCatalogue, last: AttemptRecord
) -> str | None:
    """An untried, eligible model in the failed model's equivalence group,
    another provider first (attempts.md §1)."""
    entries = {e.model_id: e for e in catalogue.entries}
    failed = entries.get(last.model_id)
    if failed is None:
        return None
    tried = {a.model_id for a in state.attempts}
    candidates = [
        e
        for e in catalogue.entries
        if e.equivalence_group == failed.equivalence_group
        and e.model_id not in tried
        and e.model_id in state.decision.eligible
    ]
    candidates.sort(key=lambda e: e.provider == failed.provider)  # stable
    return candidates[0].model_id if candidates else None
