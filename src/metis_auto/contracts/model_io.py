"""``ModelClient`` input and output (CMP-10; providers.md §1, §3; ADR-0014).

``ModelResult`` is one of: a response, a normalised error, or "no answer"
(a replay or proxy source had nothing for this target). Provider failures are
results, not exceptions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from ._base import (
    ContractModel,
    Fingerprint,
    Identifier,
    Name,
    NonNegFloat,
    PosInt,
    Privacy,
    field,
)
from .context import InputPart
from .request import AttachmentRef
from .tokens import TokenUsage


class AttemptKind(StrEnum):
    """Why an attempt happened (ADR-0013)."""

    PRIMARY = "primary"
    RETRY = "retry"
    FAILOVER = "failover"
    ESCALATION = "escalation"


class ModelInvocation(ContractModel):
    """One call to a model. Built by the pipeline from a ``ContextPlan``."""

    request_id: Identifier = field(Privacy.REFERENCE, "Request.")
    attempt_id: Identifier = field(Privacy.REFERENCE, "This attempt.")
    attempt_kind: AttemptKind = field(Privacy.OPERATIONAL, "Why.")
    model_id: Name = field(Privacy.OPERATIONAL, "Catalogue model.")
    parts: tuple[InputPart, ...] = field(Privacy.CONTENT, "Ordered input.")
    attachments: tuple[AttachmentRef, ...] = field(
        Privacy.CONTENT, "Attachments to send.", default=()
    )
    max_output_tokens: PosInt | None = field(
        Privacy.OPERATIONAL, "Generation limit.", default=None
    )
    timeout_ms: PosInt | None = field(
        Privacy.OPERATIONAL, "Per-attempt timeout.", default=None
    )
    case_id: Identifier | None = field(
        Privacy.REFERENCE, "Replay case, for replay-client lookup.", default=None
    )
    composition_fingerprint: Fingerprint | None = field(
        Privacy.FINGERPRINT, "Ordered-parts fingerprint (replay lookup).", default=None
    )
    effort: Name | None = field(
        Privacy.OPERATIONAL,
        "Reasoning effort or thinking-budget label requested (None = the "
        "provider default). Stage E6: not yet applied by the live adapter.",
        default=None,
    )


class AnswerSource(StrEnum):
    """Which kind of client produced a result (ADR-0014 counterfactual sources)."""

    FAKE = "fake"
    LOGGED = "logged"
    RECORDED = "recorded"
    LIVE = "live"
    NONE = "none"
    """Proxy runs: no answers at all."""


class FinishReason(StrEnum):
    """Normalised by adapters (providers.md §1)."""

    COMPLETE = "complete"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


class ErrorClass(StrEnum):
    """Normalised error taxonomy (providers.md §3)."""

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    CONNECTION = "connection"
    CONTEXT_OVERFLOW = "context_overflow"
    CONTENT_FILTERED = "content_filtered"
    INVALID_REQUEST = "invalid_request"
    AUTH = "auth"
    UNKNOWN = "unknown"


class ModelResponse(ContractModel):
    outcome: Literal["response"] = field(
        Privacy.OPERATIONAL, "Discriminator.", default="response"
    )
    text: str = field(Privacy.CONTENT, "Answer text.")
    finish_reason: FinishReason = field(Privacy.OPERATIONAL, "Normalised.")
    usage: TokenUsage | None = field(
        Privacy.DERIVED, "Provider-reported usage, if any.", default=None
    )
    provider_latency_ms: NonNegFloat | None = field(
        Privacy.OPERATIONAL, "Latency as measured or recorded.", default=None
    )
    provider_model_version: str | None = field(
        Privacy.OPERATIONAL, "Model version the provider reported.", default=None
    )
    time_to_first_token_ms: NonNegFloat | None = field(
        Privacy.OPERATIONAL,
        "Time to the first streamed token, if the client measured it (Stage E6: "
        "no adapter measures it yet).",
        default=None,
    )
    source: AnswerSource = field(Privacy.OPERATIONAL, "Which client kind answered.")


class ModelError(ContractModel):
    outcome: Literal["error"] = field(
        Privacy.OPERATIONAL, "Discriminator.", default="error"
    )
    error_class: ErrorClass = field(Privacy.OPERATIONAL, "Normalised class.")
    retryable: bool = field(Privacy.OPERATIONAL, "Adapter's default for the class.")
    provider_error_code: Name | None = field(
        Privacy.OPERATIONAL, "Provider code, never its message.", default=None
    )
    provider_latency_ms: NonNegFloat | None = field(
        Privacy.OPERATIONAL, "Time until the error.", default=None
    )
    source: AnswerSource = field(Privacy.OPERATIONAL, "Which client kind failed.")


class NoAnswerReason(StrEnum):
    NOT_RECORDED = "not_recorded"
    TARGET_NOT_LOGGED_MODEL = "target_not_logged_model"
    LABEL_UNMAPPED = "label_unmapped"
    PROXY_SOURCE = "proxy_source"


class ModelNoAnswer(ContractModel):
    """The counterfactual source has no answer for this target. Not an error:
    it lowers coverage (ADR-0014) and is never retried or failed over."""

    outcome: Literal["no_answer"] = field(
        Privacy.OPERATIONAL, "Discriminator.", default="no_answer"
    )
    reason: NoAnswerReason = field(Privacy.OPERATIONAL, "Why.")
    source: AnswerSource = field(Privacy.OPERATIONAL, "Which client kind.")


ModelResult = Annotated[
    ModelResponse | ModelError | ModelNoAnswer, Field(discriminator="outcome")
]
