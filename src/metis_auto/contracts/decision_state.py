"""The state sent to a System-One decision backend
(ADR-0047; QA-PRIV).

``DecisionState`` is **content**: it holds a truncated copy of the user's
message and, optionally, of the previous user turn. It exists only in memory on
the request path (and in git-ignored recordings); it never appears in events,
run records, logs or reports (tested). It never carries instructions or
retrieved text: only derived labels about them.

Its own module because it reads ``features.Language`` while ``features`` reads
``decision`` (no import cycle).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from ._base import (
    Component,
    ComponentState,
    ContractModel,
    Name,
    NonNegInt,
    Privacy,
    field,
)
from .features import Language
from .request import Modality


class LastAssistantTurnKind(StrEnum):
    """A derived label for the turn before the current message."""

    NONE = "none"
    """No earlier assistant turn (first turn)."""
    ANSWER = "answer"
    """An ordinary answer."""
    STRUCTURED_INPUT = "structured_input"
    """The assistant showed a form or input widget (proxy, A-16)."""
    UNKNOWN = "unknown"
    """History unknown."""


class DecisionState(ContractModel):
    """The minimised state for one decision call. Content (in memory only)."""

    message: str = field(
        Privacy.CONTENT,
        "The current user message, truncated to the configured length.",
    )
    message_truncated: bool = field(
        Privacy.DERIVED, "The message was cut to fit.", default=False
    )
    previous_user_turn: Component[str] = field(
        Privacy.CONTENT,
        "The previous user turn, truncated; absent on a first turn, unknown if "
        "history is unknown.",
        default_factory=Component[str].unknown,
    )
    previous_user_turn_truncated: bool = field(
        Privacy.DERIVED, "The previous turn was cut to fit.", default=False
    )
    last_assistant_turn_kind: LastAssistantTurnKind = field(
        Privacy.DERIVED, "Derived label for the last assistant turn."
    )
    retrieved_state: ComponentState = field(
        Privacy.DERIVED, "Whether retrieved context is present (never its text)."
    )
    attachment_modalities: tuple[Modality, ...] = field(
        Privacy.DERIVED, "Attachment modalities present.", default=()
    )
    language: Language = field(Privacy.DERIVED, "Detected language of the message.")
    turn_depth: NonNegInt | None = field(
        Privacy.DERIVED, "User turns before this one; None if unknown."
    )
    bot_role_class: Name | None = field(
        Privacy.DERIVED,
        "Derived class of the bot's role (a code); never instruction text.",
        default=None,
    )
    dataset_derived: bool = field(
        Privacy.OPERATIONAL,
        "Built from a dataset record (replay, dev slice): hosted backends refuse it "
        "unless router.real_data_approved is set for the run.",
        default=False,
    )

    @model_validator(mode="after")
    def _check(self) -> DecisionState:
        if not self.message.strip():
            raise ValueError("a decision state needs a non-empty message")
        first_turn = self.turn_depth == 0
        if first_turn and self.previous_user_turn.state == ComponentState.PRESENT:
            raise ValueError("a first turn has no previous user turn")
        return self
