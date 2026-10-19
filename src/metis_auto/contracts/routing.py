"""The routing decision (CMP-05 output; FR-ROUTE-01…06, routing.md)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from ._base import ContractModel, Name, NonNegInt, PolicyRef, PosInt, Privacy, field


class ExclusionReason(StrEnum):
    """Why the shared eligibility filter removed a model (routing.md §1.3)."""

    MODALITY_UNSUPPORTED = "modality_unsupported"
    CAPABILITY_UNVERIFIED = "capability_unverified"
    CONTEXT_TOO_SMALL = "context_too_small"
    CONTEXT_LIMIT_UNKNOWN = "context_limit_unknown"
    BELOW_MIN_WINDOW = "below_min_window"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


class Exclusion(ContractModel):
    model_id: Name = field(Privacy.OPERATIONAL, "Excluded model.")
    reason: ExclusionReason = field(Privacy.OPERATIONAL, "Why.")


class RoutingFlag(StrEnum):
    UNKNOWN_PRICE_SELECTED = "unknown_price_selected"
    REROUTED = "rerouted"
    REQUESTED_MODEL_IGNORED = "requested_model_ignored"
    REQUESTED_MODEL_HONOURED = "requested_model_honoured"


NO_ELIGIBLE_MODEL = "no_eligible_model"


class RoutingDecision(ContractModel):
    """The chosen target and why (FR-ROUTE-02). Content-free."""

    target_model_id: Name | None = field(
        Privacy.OPERATIONAL, "Chosen model; None if nothing was eligible."
    )
    equivalence_group: Name | None = field(
        Privacy.OPERATIONAL, "Target's failover group; a cache-key component."
    )
    tier: NonNegInt | None = field(Privacy.OPERATIONAL, "Target's tier.")
    eligible: tuple[Name, ...] = field(Privacy.OPERATIONAL, "Eligible models.")
    exclusions: tuple[Exclusion, ...] = field(
        Privacy.OPERATIONAL, "Excluded models and reasons.", default=()
    )
    chain: tuple[Name, ...] = field(
        Privacy.OPERATIONAL,
        "Escalation targets after the target, in order (ADR-0013).",
        default=(),
    )
    policy: PolicyRef = field(Privacy.OPERATIONAL, "Policy name and version.")
    reason_code: Name = field(
        Privacy.OPERATIONAL, "Machine-readable reason, e.g. a rule ID."
    )
    features_used: tuple[Name, ...] = field(
        Privacy.OPERATIONAL, "Names of the features the policy read.", default=()
    )
    min_context_window: PosInt | None = field(
        Privacy.OPERATIONAL, "Constraint applied on a re-route.", default=None
    )
    flags: tuple[RoutingFlag, ...] = field(Privacy.OPERATIONAL, "Flags.", default=())
    anchor_model_id: Name | None = field(
        Privacy.OPERATIONAL,
        "Sticky routing: the session's anchor model before this request, if any.",
        default=None,
    )

    @model_validator(mode="after")
    def _check_target(self) -> RoutingDecision:
        if self.target_model_id is None:
            if self.reason_code != NO_ELIGIBLE_MODEL:
                raise ValueError(
                    f"no target requires reason_code {NO_ELIGIBLE_MODEL!r}"
                )
            if self.equivalence_group is not None or self.tier is not None:
                raise ValueError("no target means no group or tier")
        elif self.equivalence_group is None or self.tier is None:
            raise ValueError("a target needs its equivalence group and tier")
        elif self.target_model_id not in self.eligible:
            raise ValueError("the target must be eligible (routing.md §1)")
        return self
