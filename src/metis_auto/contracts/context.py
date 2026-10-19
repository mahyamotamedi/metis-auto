"""The context plan for one target model (CMP-07; FR-CTX-01…04).

The plan holds content (the input parts). Its composition record does not,
and is what ``context_built`` events carry.
"""

from __future__ import annotations

from enum import StrEnum

from ._base import (
    ComponentState,
    ContractModel,
    Fingerprint,
    Name,
    NonNegInt,
    PolicyRef,
    PosInt,
    Privacy,
    field,
)
from .measurement import ComponentName
from .tokens import TokenCount


class PartRole(StrEnum):
    """Generic roles of input parts. Adapters map them to provider formats."""

    INSTRUCTIONS = "instructions"
    USER = "user"
    ASSISTANT = "assistant"
    RETRIEVED = "retrieved"


class InputPart(ContractModel):
    """One ordered piece of model input."""

    role: PartRole = field(Privacy.DERIVED, "Generic role.")
    text: str = field(Privacy.CONTENT, "The text.")
    component: ComponentName = field(Privacy.OPERATIONAL, "Source component.")
    item_index: NonNegInt | None = field(
        Privacy.DERIVED, "Index within the component (turn, item).", default=None
    )


class ContextAction(StrEnum):
    KEPT = "kept"
    TRIMMED = "trimmed"
    SUMMARISED = "summarised"
    COMPRESSED = "compressed"
    """Text kept but shortened by a compressor (e.g. LLMLingua-2)."""
    DROPPED = "dropped"
    NOT_APPLICABLE = "not_applicable"
    """The component was absent or unknown."""


class ComponentComposition(ContractModel):
    """What happened to one component (one row of the composition record)."""

    component: ComponentName = field(Privacy.OPERATIONAL, "Which component.")
    state: ComponentState = field(Privacy.DERIVED, "State in the request.")
    action: ContextAction = field(Privacy.OPERATIONAL, "What the policy did.")
    fingerprint: Fingerprint | None = field(
        Privacy.FINGERPRINT, "Fingerprint of what was sent.", default=None
    )
    tokens: TokenCount | None = field(
        Privacy.DERIVED, "Tokens sent, with the target's tokenizer.", default=None
    )
    items_total: NonNegInt | None = field(
        Privacy.DERIVED, "Items before.", default=None
    )
    items_kept: NonNegInt | None = field(Privacy.DERIVED, "Items after.", default=None)


class OverflowOutcome(StrEnum):
    FITS = "fits"
    TRIMMED_TO_FIT = "trimmed_to_fit"
    REROUTE_REQUESTED = "reroute_requested"
    REJECTED = "rejected"


class CompositionRecord(ContractModel):
    """Content-free record of one model input (FR-CTX-01)."""

    model_id: Name = field(Privacy.OPERATIONAL, "Target model.")
    strategy: PolicyRef = field(Privacy.OPERATIONAL, "Context policy and version.")
    components: tuple[ComponentComposition, ...] = field(
        Privacy.DERIVED, "One row per component."
    )
    input_tokens: TokenCount | None = field(
        Privacy.DERIVED, "Total input tokens.", default=None
    )
    reserved_output_tokens: NonNegInt | None = field(
        Privacy.OPERATIONAL, "Output tokens reserved.", default=None
    )
    context_window: PosInt | None = field(
        Privacy.OPERATIONAL, "Target window; None if unknown.", default=None
    )
    overflow: OverflowOutcome = field(Privacy.OPERATIONAL, "Overflow outcome.")
    composition_fingerprint: Fingerprint | None = field(
        Privacy.FINGERPRINT,
        "Fingerprint of the ordered parts; a replay-lookup key (ADR-0014).",
        default=None,
    )


class ContextPlan(ContractModel):
    """Ordered input parts for one target, plus their record."""

    model_id: Name = field(Privacy.OPERATIONAL, "Target model.")
    parts: tuple[InputPart, ...] = field(Privacy.CONTENT, "Ordered input.")
    record: CompositionRecord = field(Privacy.DERIVED, "Composition record.")
