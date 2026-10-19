"""Logged sessions and replay cases (CMP-18 output; FR-REQ-03…06, FR-DATA-06).

These contracts hold what logged data *may* have, generically. Dataset quirks
(field names, role names, where instructions are logged, export ceilings) are
handled by each dataset's loader, which records them as flags here. Nothing in
this module is used on the online path.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import JsonValue, model_validator

from ._base import (
    Component,
    ContractModel,
    Identifier,
    LoggedTimestamp,
    Name,
    NonNegInt,
    Privacy,
    field,
)
from .measurement import ComponentName
from .request import AttachmentRef, Request, RetrievedContext, Role


class DataQualityFlag(ContractModel):
    """A loader's warning about a component, e.g. possibly truncated (A-14).
    Flags are codes documented by each loader; policies never read them."""

    component: ComponentName = field(Privacy.OPERATIONAL, "Affected component.")
    flag: Name = field(Privacy.OPERATIONAL, "e.g. possibly_truncated.")


class LoggedMessage(ContractModel):
    """One logged message. Every metadata field is tri-state: a loader sets
    only what its dataset actually records."""

    position: NonNegInt = field(
        Privacy.OPERATIONAL, "Index in the session's log order."
    )
    role: Role = field(Privacy.DERIVED, "Mapped by the loader to a generic role.")
    text: str = field(Privacy.CONTENT, "Message text.")
    message_ref: Identifier | None = field(
        Privacy.REFERENCE, "Opaque message ID, if the dataset has one.", default=None
    )
    logged_timestamp: LoggedTimestamp | None = field(
        Privacy.OPERATIONAL, "Naive; timezone unknown (A-06).", default=None
    )
    model_label: Component[str] = field(
        Privacy.OPERATIONAL,
        "Logged model label; not a billing entity (A-07).",
        default_factory=Component[str].unknown,
    )
    provider_label: Component[str] = field(
        Privacy.OPERATIONAL,
        "Logged provider label.",
        default_factory=Component[str].unknown,
    )
    instructions: Component[str] = field(
        Privacy.CONTENT, "Logged instructions.", default_factory=Component[str].unknown
    )
    retrieved: Component[RetrievedContext] = field(
        Privacy.CONTENT,
        "Logged retrieved context.",
        default_factory=Component[RetrievedContext].unknown,
    )
    attachments: Component[tuple[AttachmentRef, ...]] = field(
        Privacy.CONTENT,
        "Logged attachments.",
        default_factory=Component[tuple[AttachmentRef, ...]].unknown,
    )
    structured_input: Component[dict[str, JsonValue]] = field(
        Privacy.CONTENT,
        "Logged structured-input configuration (uncertain proxy, A-16).",
        default_factory=Component[dict[str, JsonValue]].unknown,
    )
    quality_flags: tuple[DataQualityFlag, ...] = field(
        Privacy.OPERATIONAL,
        "Loader warnings about this message, e.g. possibly truncated (A-14).",
        default=(),
    )


class Session(ContractModel):
    """A logged conversation, in log order."""

    session_ref: Identifier = field(
        Privacy.REFERENCE, "Opaque or keyed reference, never the raw dataset ID."
    )
    dataset: Name = field(Privacy.OPERATIONAL, "Dataset ID, e.g. sample_v1.")
    stratum: Identifier | None = field(
        Privacy.REFERENCE,
        "Opaque category stratum; never interpreted (A-02).",
        default=None,
    )
    logged_created_at: LoggedTimestamp | None = field(
        Privacy.OPERATIONAL, "Naive session creation time, if logged.", default=None
    )
    messages: tuple[LoggedMessage, ...] = field(
        Privacy.CONTENT, "Messages in log order."
    )

    @model_validator(mode="after")
    def _ordered(self) -> Session:
        positions = [m.position for m in self.messages]
        if positions != sorted(set(positions)):
            raise ValueError("message positions must be unique and increasing")
        return self


class PairingMethod(StrEnum):
    REQUEST_ID = "request_id"
    """The dataset links answers to requests explicitly."""
    HEURISTIC_ARRAY_ORDER = "heuristic_array_order"
    """Latest preceding user message by log order (A-04)."""


class PairingFlag(StrEnum):
    """Pairing quality (FR-REQ-03). ``no_preceding_user`` never becomes a case:
    it is counted as an exclusion (FR-EVAL-08)."""

    CLEAN = "clean"
    MULTIPLE_ANSWERS = "multiple_answers"
    NO_PRECEDING_USER = "no_preceding_user"
    SKIPPED_CONSECUTIVE_USER = "skipped_consecutive_user"
    """A user message followed by another user message before any answer."""
    UNANSWERED = "unanswered"
    """A user message with no answer after it (the log ends first). Stage 8."""


class Reference(ContractModel):
    """A logged answer paired with a case. Visible to metrics only, never to
    the pipeline (FR-REQ-06)."""

    position: NonNegInt = field(Privacy.OPERATIONAL, "Position of the logged answer.")
    text: str = field(Privacy.CONTENT, "Logged answer text.")
    model_label: Component[str] = field(
        Privacy.OPERATIONAL,
        "Label of the model that answered.",
        default_factory=Component[str].unknown,
    )
    provider_label: Component[str] = field(
        Privacy.OPERATIONAL, "Provider label.", default_factory=Component[str].unknown
    )
    logged_timestamp: LoggedTimestamp | None = field(
        Privacy.OPERATIONAL, "Naive timestamp.", default=None
    )


class ReplayCase(ContractModel):
    """One replayable request as it would have been seen at its turn."""

    case_id: Identifier = field(Privacy.REFERENCE, "Minted by the case builder.")
    session_ref: Identifier = field(Privacy.REFERENCE, "Session.")
    turn_index: NonNegInt = field(Privacy.OPERATIONAL, "User turn within the session.")
    request: Request = field(Privacy.CONTENT, "Only what came before this turn.")
    references: tuple[Reference, ...] = field(
        Privacy.CONTENT, "Paired logged answers; may be empty or several."
    )
    pairing_method: PairingMethod = field(Privacy.OPERATIONAL, "How pairs were formed.")
    pairing_flag: PairingFlag = field(Privacy.OPERATIONAL, "Pairing quality.")
    logged_timestamp: LoggedTimestamp | None = field(
        Privacy.OPERATIONAL, "Naive time of the user message.", default=None
    )
    stratum: Identifier | None = field(
        Privacy.REFERENCE, "Opaque stratum.", default=None
    )
    quality_flags: tuple[DataQualityFlag, ...] = field(
        Privacy.OPERATIONAL, "Loader warnings.", default=()
    )

    @model_validator(mode="after")
    def _check(self) -> ReplayCase:
        if self.pairing_flag == PairingFlag.NO_PRECEDING_USER:
            raise ValueError("an answer with no preceding user message is an exclusion")
        if self.request.session_ref not in (None, self.session_ref):
            raise ValueError("request.session_ref must match the case")
        clean = self.pairing_flag == PairingFlag.CLEAN
        if clean and len(self.references) > 1:
            raise ValueError("several references means multiple_answers, not clean")
        return self
