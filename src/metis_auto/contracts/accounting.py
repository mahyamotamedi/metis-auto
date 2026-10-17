"""Money, cost, pre-call estimates, and savings (FR-ACCT-02…06, ADR-0002).

A cost is either computed (with price-table version and token fidelity) or
explicitly not computed with a reason. Never zero as a stand-in for unknown.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints, model_validator

from ._base import ContractModel, Name, NonNegInt, Privacy, Version, field
from .tokens import Fidelity, TokenCount

Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class Money(ContractModel):
    """An amount in one currency. Decimal, never float."""

    amount: Decimal = field(Privacy.OPERATIONAL, "Amount; may be negative for savings.")
    currency: Currency = field(Privacy.OPERATIONAL, "ISO 4217 code.")


class CostStatus(StrEnum):
    COMPUTED = "computed"
    NOT_COMPUTED = "not_computed"


class NotComputedReason(StrEnum):
    PRICE_UNKNOWN = "price_unknown"
    MODEL_UNMAPPED = "model_unmapped"
    USAGE_UNKNOWN = "usage_unknown"
    BASELINE_UNSET = "baseline_unset"
    CURRENCY_MISMATCH = "currency_mismatch"
    COMPONENT_NOT_COMPUTED = "component_not_computed"


class CostBasis(StrEnum):
    """What the cost describes."""

    ACTUAL = "actual"
    """From usage of calls that happened (reported or counted)."""
    PRE_CALL_ESTIMATE = "pre_call_estimate"
    """Before a call, for the spend cap (FR-ACCT-06)."""
    AVOIDED_ESTIMATE = "avoided_estimate"
    """Counterfactual cost avoided by a cache hit (FR-ACCT-04)."""
    BASELINE_ESTIMATE = "baseline_estimate"
    """A baseline's cost on the same composition (FR-ACCT-05)."""


class Cost(ContractModel):
    """A cost figure with its provenance (ADR-0006 point 3)."""

    status: CostStatus = field(Privacy.OPERATIONAL, "Computed or not computed.")
    basis: CostBasis = field(Privacy.OPERATIONAL, "What the figure describes.")
    amount: Money | None = field(Privacy.OPERATIONAL, "Set iff computed.", default=None)
    reason: NotComputedReason | None = field(
        Privacy.OPERATIONAL, "Set iff not computed.", default=None
    )
    price_table_version: Version | None = field(
        Privacy.OPERATIONAL, "Price table used; required when computed.", default=None
    )
    price_refs: tuple[Name, ...] = field(
        Privacy.OPERATIONAL, "Price entries used.", default=()
    )
    token_fidelity: Fidelity | None = field(
        Privacy.OPERATIONAL, "Worst fidelity among the counts used.", default=None
    )

    @model_validator(mode="after")
    def _check_status(self) -> Cost:
        if self.status == CostStatus.COMPUTED:
            if self.amount is None or self.price_table_version is None:
                raise ValueError("a computed cost needs amount and price_table_version")
            if self.reason is not None:
                raise ValueError("a computed cost has no not-computed reason")
        elif self.amount is not None or self.reason is None:
            raise ValueError("a not-computed cost has a reason and no amount")
        return self


class CostEstimate(ContractModel):
    """Pre-call estimate the spend guard compares with the cap (CMP-17)."""

    model_id: Name = field(Privacy.OPERATIONAL, "Target model.")
    input_tokens: TokenCount = field(Privacy.DERIVED, "Counted input for the plan.")
    assumed_output_tokens: NonNegInt = field(
        Privacy.OPERATIONAL, "Configured maximum output tokens assumed."
    )
    cost: Cost = field(Privacy.OPERATIONAL, "Estimated cost (basis pre_call_estimate).")


class Savings(ContractModel):
    """Baseline cost minus actual cost, for one baseline (FR-ACCT-05)."""

    baseline: Name = field(Privacy.OPERATIONAL, "Baseline ID, e.g. as_logged, premium.")
    status: CostStatus = field(Privacy.OPERATIONAL, "Computed only if both costs are.")
    amount: Money | None = field(Privacy.OPERATIONAL, "Set iff computed.", default=None)
    baseline_cost: Cost = field(Privacy.OPERATIONAL, "The baseline's cost.")
    actual_cost: Cost = field(Privacy.OPERATIONAL, "The candidate's cost.")

    @model_validator(mode="after")
    def _check_status(self) -> Savings:
        both = all(
            c.status == CostStatus.COMPUTED
            for c in (self.baseline_cost, self.actual_cost)
        )
        if (self.status == CostStatus.COMPUTED) != both:
            raise ValueError("savings are computed exactly when both costs are")
        if (self.amount is not None) != (self.status == CostStatus.COMPUTED):
            raise ValueError("amount must be set exactly when computed")
        return self
