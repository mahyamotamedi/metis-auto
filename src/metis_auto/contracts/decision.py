"""System-One decision contracts (ADR-0047; FR-FEAT-02,
FR-ROUTE-02/04, FR-ACCT-03).

A System-One decision model returns no text: given a minimised request state
and named, typed questions, it returns one typed answer per question with
probabilities. A pure domain policy maps the answers to a tier and a model;
the decision model never picks a model itself.

- ``DecisionQuestion`` / ``DecisionQuestionSet``: our configured questions
  (operational text, never content).
- ``DecisionAnswer`` / ``DecisionResult``: what one backend returned (derived).
- ``DecisionError``: a backend's expected failure, returned, never raised.
- ``DecisionOutcome``: answered, skipped or failed, with every backend tried.
- ``RouterSummary``: the content-free router part of a ``RoutingDecision``.
- ``BackendAvailability``: whether a backend can be called at all.

The state sent to a backend is content and lives in ``decision_state``; none
of the models here may hold content (tested: they reach events).
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from ._base import (
    ContractModel,
    Fingerprint,
    Name,
    NonNegFloat,
    NonNegInt,
    PolicyRef,
    Privacy,
    Version,
    field,
)
from .accounting import Cost
from .model_io import ErrorClass
from .tokens import TokenUsage

PROBABILITY_SUM_TOLERANCE = 0.01
"""How far a probability distribution may sum away from 1 (rounding by the
backend). Larger deviations are malformed (``invalid_response``)."""

QuestionText = Annotated[
    str, StringConstraints(min_length=1, max_length=500, strip_whitespace=True)
]
"""Configured question or option wording. Operational configuration written by
the project (English or Persian), never request content."""

Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class DecisionQuestionType(StrEnum):
    """Question types used for routing (System-One wire names)."""

    CHOICE = "choice"
    """One of N named options."""
    SCORE = "score"
    """An ordered rubric of levels, lowest first; the answer is a fractional level."""
    NOUL = "noul"
    """A yes/no condition; the answer is P(yes)."""


class QuestionLanguage(StrEnum):
    """Language the question set is phrased in (an A/B dimension)."""

    ENGLISH = "en"
    PERSIAN = "fa"


class DecisionOption(ContractModel):
    """One option of a ``choice`` question."""

    name: Name = field(Privacy.OPERATIONAL, "Option code, returned as the choice.")
    description: QuestionText = field(
        Privacy.OPERATIONAL, "What the option means (configured wording)."
    )


class DecisionQuestion(ContractModel):
    """One configured question. Adapters map ``options`` / ``levels`` onto the
    wire's ``criteria``."""

    id: Name = field(Privacy.OPERATIONAL, "Question ID, the answer's key.")
    type: DecisionQuestionType = field(Privacy.OPERATIONAL, "Question type.")
    instructions: QuestionText = field(
        Privacy.OPERATIONAL, "The question or condition (configured wording)."
    )
    options: tuple[DecisionOption, ...] = field(
        Privacy.OPERATIONAL, "Choice options; empty for other types.", default=()
    )
    levels: tuple[QuestionText, ...] = field(
        Privacy.OPERATIONAL,
        "Score levels, lowest first (level i scores i); empty for other types.",
        default=(),
    )
    required: bool = field(
        Privacy.OPERATIONAL,
        "A result missing this answer is an invalid response.",
        default=True,
    )

    @model_validator(mode="after")
    def _check_shape(self) -> DecisionQuestion:
        if self.type == DecisionQuestionType.CHOICE:
            if len(self.options) < 2 or self.levels:
                raise ValueError("a choice question has two or more options, no levels")
            names = [o.name for o in self.options]
            if len(set(names)) != len(names):
                raise ValueError("option names must be unique")
        elif self.type == DecisionQuestionType.SCORE:
            if len(self.levels) < 2 or self.options:
                raise ValueError("a score question has two or more levels, no options")
        elif self.options or self.levels:
            raise ValueError("a noul question has no options or levels")
        return self

    @property
    def option_names(self) -> tuple[str, ...]:
        return tuple(o.name for o in self.options)


class DecisionQuestionSet(ContractModel):
    """A versioned set of questions asked together in one backend call."""

    version: Version = field(Privacy.OPERATIONAL, "e.g. routing_qs_v1.")
    language_variant: QuestionLanguage = field(
        Privacy.OPERATIONAL, "Language of the wording."
    )
    questions: tuple[DecisionQuestion, ...] = field(
        Privacy.OPERATIONAL, "The questions, in a stable order."
    )

    @model_validator(mode="after")
    def _check_ids(self) -> DecisionQuestionSet:
        if not self.questions:
            raise ValueError("a question set has at least one question")
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question IDs must be unique")
        return self

    def get(self, question_id: str) -> DecisionQuestion | None:
        return next((q for q in self.questions if q.id == question_id), None)


def _check_distribution(probabilities: dict[str, float]) -> None:
    if probabilities and not math.isclose(
        sum(probabilities.values()), 1.0, abs_tol=PROBABILITY_SUM_TOLERANCE
    ):
        raise ValueError("probabilities must sum to 1")


class DecisionAnswer(ContractModel):
    """One typed answer. Exactly the fields of its type are set."""

    question_id: Name = field(Privacy.OPERATIONAL, "Which question.")
    type: DecisionQuestionType = field(Privacy.OPERATIONAL, "Question type.")
    choice: Name | None = field(
        Privacy.DERIVED, "Chosen option (choice only).", default=None
    )
    score: NonNegFloat | None = field(
        Privacy.DERIVED, "Fractional level, 0 = lowest (score only).", default=None
    )
    p_yes: Probability | None = field(
        Privacy.DERIVED, "Probability of yes (noul only).", default=None
    )
    probabilities: dict[Name, Probability] = field(
        Privacy.DERIVED,
        "Per option (choice) or per level index as a string (score); empty if "
        "the backend did not return them.",
        default_factory=dict,
    )
    confidence: Probability | None = field(
        Privacy.DERIVED,
        "Backend-reported confidence; never derived from the probabilities.",
        default=None,
    )

    @model_validator(mode="after")
    def _check_type(self) -> DecisionAnswer:
        kind = self.type
        if kind == DecisionQuestionType.CHOICE:
            if self.choice is None or self.score is not None or self.p_yes is not None:
                raise ValueError("a choice answer sets choice only")
            if self.probabilities and self.choice not in self.probabilities:
                raise ValueError("the choice must be one of the probabilities' keys")
        elif kind == DecisionQuestionType.SCORE:
            if self.score is None or self.choice is not None or self.p_yes is not None:
                raise ValueError("a score answer sets score only")
        else:
            if self.p_yes is None or self.choice is not None or self.score is not None:
                raise ValueError("a noul answer sets p_yes only")
            if self.probabilities:
                raise ValueError("a noul answer has no probabilities")
        _check_distribution(self.probabilities)
        return self


class BackendKind(StrEnum):
    HOSTED = "hosted"
    """Called over the network (Jev via Metis, an LLM via the wrapper)."""
    LOCAL = "local"
    """Runs on this machine (in-process, or a localhost server)."""


class DecisionLatencySource(StrEnum):
    MEASURED_LOCAL = "measured_local"
    """Monotonic clock around an in-process or localhost call."""
    MEASURED_REMOTE = "measured_remote"
    """Monotonic clock around a network call (includes the network)."""


class DecisionResult(ContractModel):
    """What one backend answered for one state (derived, content-free)."""

    answers: tuple[DecisionAnswer, ...] = field(Privacy.DERIVED, "One per question.")
    backend: PolicyRef = field(Privacy.OPERATIONAL, "Backend name and version.")
    backend_kind: BackendKind = field(Privacy.OPERATIONAL, "Hosted or local.")
    model_revision: Version = field(
        Privacy.OPERATIONAL,
        "Model version reported by the backend (e.g. jev-1.13.0) or the pinned "
        "weights revision.",
    )
    question_set_version: Version = field(Privacy.OPERATIONAL, "Questions asked.")
    state_fingerprint: Fingerprint | None = field(
        Privacy.FINGERPRINT,
        "Keyed fingerprint of the normalised state (ADR-0015); router-cache key part.",
        default=None,
    )
    latency_ms: NonNegFloat = field(Privacy.OPERATIONAL, "Duration of the call.")
    latency_source: DecisionLatencySource = field(
        Privacy.OPERATIONAL, "How it was measured."
    )
    usage: TokenUsage | None = field(
        Privacy.DERIVED,
        "Token usage as reported by the backend; None if not reported.",
        default=None,
    )
    cost: Cost = field(
        Privacy.OPERATIONAL,
        "Hosted: priced from usage, or not computed. Local: zero, basis local_compute.",
    )
    cache_hit: bool = field(
        Privacy.OPERATIONAL, "Served from the router-result cache.", default=False
    )
    calibrated: bool = field(
        Privacy.OPERATIONAL,
        "The backend applies a fitted calibration to its probabilities.",
    )

    @model_validator(mode="after")
    def _check_answers(self) -> DecisionResult:
        ids = [a.question_id for a in self.answers]
        if len(set(ids)) != len(ids):
            raise ValueError("one answer per question")
        return self

    def answer(self, question_id: str) -> DecisionAnswer | None:
        return next((a for a in self.answers if a.question_id == question_id), None)


class DecisionError(ContractModel):
    """An expected backend failure. Backends return it; they never raise for
    timeouts, transport, provider or parsing failures
    (ADR-0047)."""

    outcome: Literal["error"] = field(
        Privacy.OPERATIONAL, "Discriminator.", default="error"
    )
    backend: PolicyRef = field(Privacy.OPERATIONAL, "Backend name and version.")
    error_class: ErrorClass | None = field(
        Privacy.OPERATIONAL,
        "Normalised transport or provider error; None for an invalid response.",
        default=None,
    )
    invalid_response: bool = field(
        Privacy.OPERATIONAL,
        "The backend answered, but the answer failed validation.",
        default=False,
    )
    provider_error_code: Name | None = field(
        Privacy.OPERATIONAL,
        "e.g. http_429 or http_400:invalid_field; never a provider message.",
        default=None,
    )
    latency_ms: NonNegFloat = field(Privacy.OPERATIONAL, "Time spent before failing.")

    @model_validator(mode="after")
    def _check_kind(self) -> DecisionError:
        if (self.error_class is None) != self.invalid_response:
            raise ValueError("exactly one of error_class or invalid_response")
        return self


class AvailabilityReason(StrEnum):
    MISSING_EXTRA = "missing_extra"
    """The backend's optional dependencies are not installed."""
    MISSING_ASSETS = "missing_assets"
    """Pinned weights or files are not fetched."""
    SHA_MISMATCH = "sha_mismatch"
    """A fetched file's sha256 differs from the pin."""
    SERVER_UNREACHABLE = "server_unreachable"
    """A localhost server did not answer its health check."""
    DISABLED = "disabled"
    """Disabled in configuration."""
    NOT_CONFIGURED = "not_configured"
    """Hosted: no key, no live mode, or no spend guard."""


class BackendAvailability(ContractModel):
    """Whether a backend can be called; checked at build time and per request."""

    available: bool = field(Privacy.OPERATIONAL, "Usable now.")
    reason: AvailabilityReason | None = field(
        Privacy.OPERATIONAL, "Why not; set iff unavailable.", default=None
    )

    @model_validator(mode="after")
    def _check_reason(self) -> BackendAvailability:
        if self.available == (self.reason is not None):
            raise ValueError("reason is set exactly when unavailable")
        return self

    @classmethod
    def ok(cls) -> BackendAvailability:
        return cls(available=True)

    @classmethod
    def unavailable(cls, reason: AvailabilityReason) -> BackendAvailability:
        return cls(available=False, reason=reason)


class DecisionStatus(StrEnum):
    ANSWERED = "answered"
    SKIPPED = "skipped"
    FAILED = "failed"


class DecisionSkipReason(StrEnum):
    RULES_DECISIVE = "rules_decisive"
    """A configured gate rule decided without asking a model (fast path)."""
    MODE_OFF = "mode_off"
    NOT_NEEDED = "not_needed"
    INELIGIBLE_STATE = "ineligible_state"
    """No state can be built (e.g. an empty message with attachments only)."""


class DecisionFailureReason(StrEnum):
    TIMEOUT = "timeout"
    CIRCUIT_OPEN = "circuit_open"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    BUDGET_BLOCKED = "budget_blocked"
    ERROR = "error"
    """A normalised provider or transport error; see ``error_class``."""
    LOW_CONFIDENCE = "low_confidence"
    NO_BACKEND = "no_backend"
    REAL_DATA_NOT_APPROVED = "real_data_not_approved"
    """Hosted backend refused: dataset-derived state without approval."""


class BackendAttempt(ContractModel):
    """One backend tried for one request, in chain order."""

    backend: PolicyRef = field(Privacy.OPERATIONAL, "Backend name and version.")
    answered: bool = field(Privacy.OPERATIONAL, "True if it returned a valid result.")
    failure_reason: DecisionFailureReason | None = field(
        Privacy.OPERATIONAL, "Set iff not answered.", default=None
    )
    error_class: ErrorClass | None = field(
        Privacy.OPERATIONAL, "Set iff failure_reason is error.", default=None
    )
    latency_ms: NonNegFloat = field(
        Privacy.OPERATIONAL, "Time spent on this backend (0 if never called)."
    )
    overran_deadline: bool = field(
        Privacy.OPERATIONAL,
        "An in-process call that cannot be pre-empted finished after its deadline.",
        default=False,
    )

    @model_validator(mode="after")
    def _check(self) -> BackendAttempt:
        if self.answered == (self.failure_reason is not None):
            raise ValueError("failure_reason is set exactly when not answered")
        if (self.failure_reason == DecisionFailureReason.ERROR) != (
            self.error_class is not None
        ):
            raise ValueError("error_class is set exactly when failure_reason is error")
        return self


class DecisionOutcome(ContractModel):
    """The router cascade's measured result for one request (derived,
    content-free). Unknown never satisfies a mapping rule (P-6): only an
    answered outcome feeds the decision policy."""

    status: DecisionStatus = field(Privacy.OPERATIONAL, "Answered, skipped, failed.")
    question_set_version: Version | None = field(
        Privacy.OPERATIONAL, "Questions asked, if any.", default=None
    )
    result: DecisionResult | None = field(
        Privacy.DERIVED, "Set iff answered.", default=None
    )
    skip_reason: DecisionSkipReason | None = field(
        Privacy.OPERATIONAL, "Set iff skipped.", default=None
    )
    rule_id: Name | None = field(
        Privacy.OPERATIONAL,
        "Gate rule that decided (rules_decisive only).",
        default=None,
    )
    failure_reason: DecisionFailureReason | None = field(
        Privacy.OPERATIONAL, "Set iff failed: the last backend's reason.", default=None
    )
    error_class: ErrorClass | None = field(
        Privacy.OPERATIONAL, "Set iff failure_reason is error.", default=None
    )
    soft_result: DecisionResult | None = field(
        Privacy.DERIVED,
        "Low-confidence answers kept as soft signals (failed low_confidence only, "
        "if configured).",
        default=None,
    )
    attempts: tuple[BackendAttempt, ...] = field(
        Privacy.OPERATIONAL, "Backends tried, in order.", default=()
    )
    total_ms: NonNegFloat = field(
        Privacy.OPERATIONAL, "Wall time of the whole decision step.", default=0.0
    )

    @model_validator(mode="after")
    def _check_status(self) -> DecisionOutcome:
        answered = self.status == DecisionStatus.ANSWERED
        skipped = self.status == DecisionStatus.SKIPPED
        failed = self.status == DecisionStatus.FAILED
        if answered != (self.result is not None):
            raise ValueError("result is set exactly when answered")
        if skipped != (self.skip_reason is not None):
            raise ValueError("skip_reason is set exactly when skipped")
        if failed != (self.failure_reason is not None):
            raise ValueError("failure_reason is set exactly when failed")
        if (self.rule_id is not None) and (
            self.skip_reason != DecisionSkipReason.RULES_DECISIVE
        ):
            raise ValueError("rule_id is only set when rules were decisive")
        if (self.failure_reason == DecisionFailureReason.ERROR) != (
            self.error_class is not None
        ):
            raise ValueError("error_class is set exactly when failure_reason is error")
        if self.soft_result is not None and (
            self.failure_reason != DecisionFailureReason.LOW_CONFIDENCE
        ):
            raise ValueError("soft_result is only kept on a low-confidence failure")
        if skipped and self.attempts:
            raise ValueError("a skipped decision tried no backend")
        if self.result is not None and self.result.cache_hit and self.attempts:
            raise ValueError("a router-cache hit tried no backend")
        return self


class RouterPath(StrEnum):
    """Which path decided the tier (routing.md §7)."""

    FAST_RULES = "fast_rules"
    FAST_CACHE = "fast_cache"
    SLOW_LOCAL = "slow_local"
    SLOW_HOSTED = "slow_hosted"
    FALLBACK_RULES = "fallback_rules"
    FALLBACK_SAFE_TIER = "fallback_safe_tier"


class RouterSummary(ContractModel):
    """The decision router's part of a ``RoutingDecision`` (content-free)."""

    path: RouterPath = field(Privacy.OPERATIONAL, "Path that decided.")
    backend: PolicyRef | None = field(
        Privacy.OPERATIONAL, "Backend whose answers were used, if any.", default=None
    )
    mapped_tier: NonNegInt | None = field(
        Privacy.OPERATIONAL, "Tier the mapping chose, before eligibility.", default=None
    )
    thresholds_fired: tuple[Name, ...] = field(
        Privacy.OPERATIONAL,
        "Mapping rules and criteria that fired, in order (e.g. tau_reason).",
        default=(),
    )
    reasoning_effort: Name | None = field(
        Privacy.OPERATIONAL,
        "Reasoning-effort hint for the target (None = the model's default).",
        default=None,
    )
