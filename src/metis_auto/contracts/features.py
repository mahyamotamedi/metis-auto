"""Derived request features (CMP-04 output; FR-FEAT-01…05).

The core set is provisional. Experimental features go in ``extra`` until
promoted. Values are derived, never content (FR-FEAT-05).
"""

from __future__ import annotations

from enum import StrEnum

from ._base import (
    ComponentState,
    ContractModel,
    FeatureValue,
    Fingerprint,
    Name,
    NonNegInt,
    Privacy,
    Version,
    field,
)
from .request import Modality, Provenance
from .tokens import TokenCount


class Language(StrEnum):
    """Output of the tested language detector (FR-FEAT-03)."""

    PERSIAN = "fa"
    ENGLISH = "en"
    MIXED = "mixed"
    OTHER = "other"
    UNDETERMINED = "undetermined"


class TurnFeatures(ContractModel):
    """Cheap features of one earlier user turn and who answered it (Demo
    milestone: sticky routing reads them, routing_plan §5). Content-free."""

    language: Language = field(Privacy.DERIVED, "Language of the user turn.")
    has_code: bool = field(Privacy.DERIVED, "Code detected in the user turn.")
    has_coding_intent: bool = field(
        Privacy.DERIVED,
        "The turn asks for code or programming help, with no code in it.",
        default=False,
    )
    length_bucket: NonNegInt = field(Privacy.DERIVED, "Length bucket of the turn.")
    is_greeting: bool = field(Privacy.DERIVED, "Greeting or small talk.")
    producer_state: ComponentState = field(
        Privacy.DERIVED, "State of the answering turn's producer."
    )
    producer: Name | None = field(
        Privacy.OPERATIONAL,
        "Model ID or 'cache' that answered; None if absent, unknown, or no answer.",
        default=None,
    )


class RequestFeatures(ContractModel):
    """Features of one request. None means unknown (the component's state was
    unknown), not zero."""

    feature_set_version: Version = field(Privacy.OPERATIONAL, "Feature-set version.")
    language: Language = field(Privacy.DERIVED, "Language of the current message.")
    message_chars: NonNegInt = field(Privacy.DERIVED, "Message length.")
    message_tokens: TokenCount | None = field(
        Privacy.DERIVED, "Message token estimate, with its method.", default=None
    )
    known_input_tokens: TokenCount | None = field(
        Privacy.DERIVED,
        "Cheap estimate over present components; unknown ones add nothing, so it "
        "is a lower bound. Used for the routing context-fit check.",
        default=None,
    )
    has_code: bool | None = field(Privacy.DERIVED, "Code detected.", default=None)
    has_coding_intent: bool | None = field(
        Privacy.DERIVED,
        "Asks for code or programming help, with no code present (configured "
        "keywords, request cues, and templates).",
        default=None,
    )
    length_bucket: NonNegInt | None = field(
        Privacy.DERIVED,
        "Message length bucket (configured character bounds).",
        default=None,
    )
    is_greeting: bool | None = field(
        Privacy.DERIVED,
        "Greeting or small talk (configured phrase list).",
        default=None,
    )
    attachment_count: NonNegInt | None = field(
        Privacy.DERIVED, "Attachments; None if unknown.", default=None
    )
    attachment_modalities: tuple[Modality, ...] = field(
        Privacy.DERIVED, "Distinct modalities present.", default=()
    )
    turn_depth: NonNegInt | None = field(
        Privacy.DERIVED,
        "User turns before this one; None if history unknown.",
        default=None,
    )
    history_chars: NonNegInt | None = field(
        Privacy.DERIVED, "History size.", default=None
    )
    instructions_state: ComponentState = field(Privacy.DERIVED, "Instructions state.")
    instructions_chars: NonNegInt | None = field(
        Privacy.DERIVED, "Instructions size.", default=None
    )
    instructions_group: Fingerprint | None = field(
        Privacy.FINGERPRINT, "Fingerprint of normalised instructions.", default=None
    )
    retrieved_state: ComponentState = field(Privacy.DERIVED, "Retrieved-context state.")
    retrieved_items: NonNegInt | None = field(
        Privacy.DERIVED, "Retrieved items.", default=None
    )
    retrieved_chars: NonNegInt | None = field(
        Privacy.DERIVED, "Retrieved size.", default=None
    )
    structured_input_state: ComponentState = field(
        Privacy.DERIVED, "Structured-input state (uncertain proxy, A-16)."
    )
    traffic_source_state: ComponentState = field(
        Privacy.DERIVED, "Traffic-source state (reserved, Q-21)."
    )
    traffic_source_kind: Name | None = field(
        Privacy.DERIVED, "Traffic-source kind, if present.", default=None
    )
    traffic_source_provenance: Provenance | None = field(
        Privacy.OPERATIONAL, "Declared or inferred.", default=None
    )
    history_turns: tuple[TurnFeatures, ...] = field(
        Privacy.DERIVED,
        "Earlier user turns, oldest first, with their producers (sticky routing).",
        default=(),
    )
    extra: dict[Name, FeatureValue] = field(
        Privacy.DERIVED,
        "Experimental or measured features (e.g. semantic intent).",
        default_factory=dict,
    )
