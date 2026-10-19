"""The incoming request and its components (FR-REQ-01…05, P-6, P-8).

Generic on purpose (FR-DATA-06): no dataset field names, role names, or
quirks. The sample loader maps its format onto these types (ADR-0008).
The pipeline mints ``request_id``; it is not part of the caller's request.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import JsonValue, StringConstraints, model_validator

from ._base import (
    Component,
    ComponentState,
    ContractModel,
    Fingerprint,
    Identifier,
    Name,
    NonNegInt,
    PosInt,
    Privacy,
    field,
)


class Role(StrEnum):
    """Generic conversation roles. Datasets' own names (e.g. ``bot``) are
    mapped by their loader."""

    USER = "user"
    ASSISTANT = "assistant"


CACHE_PRODUCER = "cache"
"""``Turn.producer`` value for an answer served from cache (sticky routing)."""


class Turn(ContractModel):
    """One earlier message in the conversation history.

    ``producer`` (Demo milestone, A-64): who produced an assistant turn, a
    catalogue model ID or ``cache``, so a stateless policy can read a session's
    routing history from the request (P-8; sticky routing, routing_plan §5).
    Unknown by default (e.g. logged history); absent for a user turn. It is
    metadata, not content: it is not part of the history fingerprint.
    """

    role: Role = field(Privacy.DERIVED, "Who wrote the message.")
    text: str = field(Privacy.CONTENT, "Message text.")
    producer: Component[Name] = field(
        Privacy.OPERATIONAL,
        "Assistant turns: the model ID or 'cache' that produced it.",
        default_factory=Component[Name].unknown,
    )

    @model_validator(mode="after")
    def _user_turn_has_no_producer(self) -> Turn:
        if self.role == Role.USER and self.producer.state == ComponentState.PRESENT:
            raise ValueError("a user turn has no producer (absent or unknown)")
        return self


class RetrievedItem(ContractModel):
    """One retrieved-context string, with optional retrieval metadata
    (FR-OBS-04: document IDs and scores only if the caller supplies them)."""

    text: str = field(Privacy.CONTENT, "Retrieved text.")
    document_ref: Identifier | None = field(
        Privacy.REFERENCE, "Opaque document ID from the caller.", default=None
    )
    score: float | None = field(Privacy.DERIVED, "Retrieval score.", default=None)


class RetrievedContext(ContractModel):
    """Retrieved context (RAG) in the order the caller supplied it."""

    items: tuple[RetrievedItem, ...] = field(
        Privacy.CONTENT,
        "Ordered items; at least one (no items = absent, O-4).",
        min_length=1,
    )
    query: Component[str] = field(
        Privacy.CONTENT,
        "Retrieval query, if known.",
        default_factory=Component[str].unknown,
    )


class Modality(StrEnum):
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    OTHER = "other"


class AttachmentRef(ContractModel):
    """A reference to an attachment. Content is never inspected (NG-07)."""

    modality: Modality = field(Privacy.DERIVED, "Kind of attachment.")
    media_type: str | None = field(
        Privacy.DERIVED, "MIME type, if known.", default=None, max_length=128
    )
    locator: str | None = field(
        Privacy.CONTENT,
        "URI or inline payload; may reveal content, so it stays in memory.",
        default=None,
    )
    size_bytes: NonNegInt | None = field(
        Privacy.DERIVED, "Size, if known.", default=None
    )
    fingerprint: Fingerprint | None = field(
        Privacy.FINGERPRINT,
        "Keyed fingerprint of the content, if computed.",
        default=None,
    )


TrafficSourceKind = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
KNOWN_TRAFFIC_SOURCES: tuple[str, ...] = ("embedded_bot", "direct_user")
"""Initial values of the open enumeration (ADR-0016). New values are config."""


class Provenance(StrEnum):
    DECLARED = "declared"
    """Stated by the caller or gateway (e.g. from the API key type)."""
    INFERRED = "inferred"
    """From a heuristic. Analysis only; never chooses a serving scope."""


class TrafficSource(ContractModel):
    """Where the request comes from. **Reserved** (Q-21, ADR-0016, proposed):
    recorded and stratified, but it does not affect serving."""

    kind: TrafficSourceKind = field(Privacy.DERIVED, "e.g. embedded_bot, direct_user.")
    provenance: Provenance = field(Privacy.OPERATIONAL, "Declared or inferred.")


class Request(ContractModel):
    """What Metis answers: the current message plus optional components.

    Every optional component defaults to **unknown**, the conservative state:
    unknown never matches a cache key and never counts as "no context" (P-6).
    Callers that know a component is absent must say so.

    ``message`` may be empty or whitespace-only only when attachments are present
    (an attachment-only message, decided 2026-10-18).
    """

    message: str = field(
        Privacy.CONTENT,
        "The current user message; empty only if attachments are present.",
    )
    history: Component[tuple[Turn, ...]] = field(
        Privacy.CONTENT,
        "Earlier turns, oldest first, supplied by the caller (P-8).",
        default_factory=Component[tuple[Turn, ...]].unknown,
    )
    instructions: Component[str] = field(
        Privacy.CONTENT,
        "System-level text; not proven to be the provider system prompt (A-03).",
        default_factory=Component[str].unknown,
    )
    retrieved: Component[RetrievedContext] = field(
        Privacy.CONTENT,
        "Retrieved context (RAG).",
        default_factory=Component[RetrievedContext].unknown,
    )
    attachments: Component[tuple[AttachmentRef, ...]] = field(
        Privacy.CONTENT,
        "Attachment references.",
        default_factory=Component[tuple[AttachmentRef, ...]].unknown,
    )
    structured_input: Component[dict[str, JsonValue]] = field(
        Privacy.CONTENT,
        "Structured-input configuration, opaque to Metis (C-03).",
        default_factory=Component[dict[str, JsonValue]].unknown,
    )
    traffic_source: Component[TrafficSource] = field(
        Privacy.DERIVED,
        "Reserved (Q-21). Recorded and stratified only; no serving effect.",
        default_factory=Component[TrafficSource].unknown,
    )
    session_ref: Identifier | None = field(
        Privacy.REFERENCE, "Opaque conversation reference.", default=None
    )
    user_ref: Identifier | None = field(
        Privacy.REFERENCE, "Privacy-safe user reference (ADR-0007).", default=None
    )
    caller_request_ref: Identifier | None = field(
        Privacy.REFERENCE, "The caller's own correlation ID, echoed back.", default=None
    )
    requested_model: Name | None = field(
        Privacy.OPERATIONAL,
        "Model the caller asked for (FR-ROUTE-06, open).",
        default=None,
    )
    deadline_ms: PosInt | None = field(
        Privacy.OPERATIONAL, "Time budget for the whole request.", default=None
    )

    @model_validator(mode="after")
    def _message_or_attachments(self) -> Request:
        if (
            not self.message.strip()
            and self.attachments.state != ComponentState.PRESENT
        ):
            raise ValueError(
                "an empty message needs attachments present (attachment-only message)"
            )
        return self
