"""Attempt state, actions, records, and detector verdicts (CMP-08; ADR-0013).

The attempt policy reads ``AttemptState`` and returns ``AttemptAction``. Answer
text is never in these contracts: the pipeline keeps responses by attempt ID.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from ._base import (
    ContractModel,
    Identifier,
    Name,
    NonNegFloat,
    NonNegInt,
    Privacy,
    Version,
    field,
)
from .accounting import Cost, Money
from .model_io import AnswerSource, AttemptKind, ErrorClass, FinishReason
from .routing import RoutingDecision
from .tokens import TokenUsage


class VerdictState(StrEnum):
    EVALUATED = "evaluated"
    NOT_EVALUATED = "not_evaluated"
    """Input unavailable (e.g. no judge configured)."""


class DetectorVerdict(ContractModel):
    """One detector's view of one answer (FR-CASC-05, attempts.md §4)."""

    detector: Name = field(Privacy.OPERATIONAL, "Detector ID.")
    version: Version = field(Privacy.OPERATIONAL, "Detector version.")
    state: VerdictState = field(Privacy.OPERATIONAL, "Evaluated or not.")
    value: float | None = field(Privacy.DERIVED, "Measured value.", default=None)
    threshold: float | None = field(Privacy.OPERATIONAL, "Threshold.", default=None)
    fired: bool = field(Privacy.DERIVED, "Flags the answer as unsatisfactory.")

    @model_validator(mode="after")
    def _check(self) -> DetectorVerdict:
        if self.state == VerdictState.NOT_EVALUATED and self.fired:
            raise ValueError("a detector that did not evaluate cannot fire")
        return self


class AttemptOutcome(StrEnum):
    RESPONSE = "response"
    ERROR = "error"
    NO_ANSWER = "no_answer"
    BUDGET_BLOCKED = "budget_blocked"


class AttemptRecord(ContractModel):
    """Content-free summary of one finished attempt."""

    attempt_id: Identifier = field(Privacy.REFERENCE, "Attempt.")
    parent_attempt_id: Identifier | None = field(
        Privacy.REFERENCE, "Previous attempt in the chain.", default=None
    )
    number: NonNegInt = field(Privacy.OPERATIONAL, "0 for the primary attempt.")
    kind: AttemptKind = field(Privacy.OPERATIONAL, "Why it happened.")
    model_id: Name = field(Privacy.OPERATIONAL, "Model called.")
    provider: Name = field(Privacy.OPERATIONAL, "Provider.")
    outcome: AttemptOutcome = field(Privacy.OPERATIONAL, "What came back.")
    source: AnswerSource | None = field(
        Privacy.OPERATIONAL, "Client kind; None if blocked before a call.", default=None
    )
    error_class: ErrorClass | None = field(
        Privacy.OPERATIONAL, "Set iff outcome is error.", default=None
    )
    finish_reason: FinishReason | None = field(
        Privacy.OPERATIONAL, "Set iff outcome is response.", default=None
    )
    usage: TokenUsage | None = field(
        Privacy.DERIVED, "Usage, best fidelity.", default=None
    )
    cost: Cost | None = field(Privacy.OPERATIONAL, "Charged cost.", default=None)
    duration_ms: NonNegFloat | None = field(
        Privacy.OPERATIONAL, "model_call span duration.", default=None
    )
    effort: Name | None = field(
        Privacy.OPERATIONAL,
        "Effort label requested (Stage E6). Not populated by any production "
        "code yet: always None until a producer fills it.",
        default=None,
    )
    time_to_first_token_ms: NonNegFloat | None = field(
        Privacy.OPERATIONAL,
        "Time to first token (Stage E6). Not populated by any production code "
        "yet: always None until an adapter measures it.",
        default=None,
    )
    verdicts: tuple[DetectorVerdict, ...] = field(
        Privacy.DERIVED, "Detector verdicts on a response.", default=()
    )
    unsatisfactory: bool | None = field(
        Privacy.DERIVED, "Combined verdict; None if not a response.", default=None
    )

    @model_validator(mode="after")
    def _check(self) -> AttemptRecord:
        is_error = self.outcome == AttemptOutcome.ERROR
        is_response = self.outcome == AttemptOutcome.RESPONSE
        if is_error != (self.error_class is not None):
            raise ValueError("error_class must be set exactly for errors")
        if is_response != (self.finish_reason is not None):
            raise ValueError("finish_reason must be set exactly for responses")
        if not is_response and (self.verdicts or self.unsatisfactory is not None):
            raise ValueError("only responses carry verdicts")
        return self


class AttemptState(ContractModel):
    """Everything the attempt policy may read (attempts.md §1)."""

    request_id: Identifier = field(Privacy.REFERENCE, "Request.")
    decision: RoutingDecision = field(Privacy.OPERATIONAL, "Routing decision.")
    attempts: tuple[AttemptRecord, ...] = field(
        Privacy.OPERATIONAL, "Finished attempts, oldest first.", default=()
    )
    deadline_remaining_ms: float | None = field(
        Privacy.OPERATIONAL, "Time left; None if no deadline.", default=None
    )
    budget_remaining: Money | None = field(
        Privacy.OPERATIONAL, "Spend cap left; None if no cap applies.", default=None
    )
    rerouted: bool = field(
        Privacy.OPERATIONAL, "A re-route already happened.", default=False
    )


class ActionKind(StrEnum):
    INVOKE = "invoke"
    RETURN = "return"
    FAIL = "fail"


class FailureReason(StrEnum):
    """Why a request ends without an answer (lifecycle §1 terminal outcomes)."""

    NO_ELIGIBLE_MODEL = "no_eligible_model"
    ALL_ATTEMPTS_FAILED = "all_attempts_failed"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CONTEXT_OVERFLOW = "context_overflow"
    NO_ANSWER = "no_answer"
    CONTENT_FILTERED = "content_filtered"


class AttemptAction(ContractModel):
    """The attempt policy's next step."""

    action: ActionKind = field(Privacy.OPERATIONAL, "Invoke, return, or fail.")
    reason: Name = field(Privacy.OPERATIONAL, "Machine-readable reason.")
    target_model_id: Name | None = field(
        Privacy.OPERATIONAL, "Set iff invoke.", default=None
    )
    kind: AttemptKind | None = field(
        Privacy.OPERATIONAL, "Set iff invoke.", default=None
    )
    backoff_ms: NonNegFloat | None = field(
        Privacy.OPERATIONAL, "Wait before invoking (retries).", default=None
    )
    return_attempt_id: Identifier | None = field(
        Privacy.REFERENCE, "Set iff return: which answer.", default=None
    )
    unsatisfactory_returned: bool = field(
        Privacy.DERIVED, "Returning an answer a detector flagged.", default=False
    )
    failure: FailureReason | None = field(
        Privacy.OPERATIONAL, "Set iff fail.", default=None
    )

    @model_validator(mode="after")
    def _check(self) -> AttemptAction:
        invoke = self.action == ActionKind.INVOKE
        if invoke != (self.target_model_id is not None and self.kind is not None):
            raise ValueError("target_model_id and kind are set exactly for invoke")
        if (self.action == ActionKind.RETURN) != (self.return_attempt_id is not None):
            raise ValueError("return_attempt_id is set exactly for return")
        if (self.action == ActionKind.FAIL) != (self.failure is not None):
            raise ValueError("failure is set exactly for fail")
        return self
