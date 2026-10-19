"""Money, cost, pre-call estimates, baseline estimates, and savings
(FR-ACCT-02…06, ADR-0002, ADR-0020).

A cost is either computed (with price-table version, token fidelity, and any
caveats) or explicitly not computed with a reason. Never zero as a stand-in
for unknown.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints, model_validator

from ._base import ContractModel, Name, NonNegInt, Privacy, Version, field
from .tokens import Fidelity, TokenCount, TokenUsage

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


class CostCaveat(StrEnum):
    """Why a computed cost may differ from the bill (token_accounting.md §5).
    Shown with the figure; never silently dropped."""

    REASONING_NOT_COUNTED = "reasoning_not_counted"
    """Lower bound: a reasoning model's output was counted from the visible
    answer, so hidden reasoning tokens (billed as output) are missing."""
    ANSWER_LENGTH_ASSUMED = "answer_length_assumed"
    """Baseline estimate: another model's answer stands in for this model's
    (same text, re-counted with this model's tokenizer)."""
    TEMPLATE_OVERHEAD_APPROXIMATED = "template_overhead_approximated"
    """Counted input includes chat-template framing that is not verified for
    this model."""
    CONTEXT_TIER_BOUNDARY_UNCERTAIN = "context_tier_boundary_uncertain"
    """Input lies where the price source's tier bound is ambiguous; the more
    expensive tier was used."""
    CACHED_INPUT_NOT_REPORTED = "cached_input_not_reported"
    """Provider usage had no cached-token count; all input priced uncached
    (an upper bound)."""


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
    price_tier: Name | None = field(
        Privacy.OPERATIONAL, "Context tier used, when prices are tiered.", default=None
    )
    caveats: tuple[CostCaveat, ...] = field(
        Privacy.OPERATIONAL,
        "Known ways the figure may differ from the bill.",
        default=(),
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


class AccountedUsage(ContractModel):
    """Tokens and cost of one call, actual or estimated: what the accounting
    service reports for "this request and answer on this model" (MP Stage 7).
    A baseline estimate names its baseline (brief §5)."""

    model_id: Name = field(Privacy.OPERATIONAL, "Catalogue model.")
    usage: TokenUsage = field(Privacy.DERIVED, "Input, output, total, with fidelity.")
    cost: Cost = field(Privacy.OPERATIONAL, "Cost with provenance and caveats.")
    baseline: Name | None = field(
        Privacy.OPERATIONAL,
        "Baseline ID when this is a baseline estimate.",
        default=None,
    )

    @model_validator(mode="after")
    def _check(self) -> AccountedUsage:
        if self.usage.model_id != self.model_id:
            raise ValueError("usage is for a different model")
        if (self.baseline is not None) != (
            self.cost.basis == CostBasis.BASELINE_ESTIMATE
        ):
            raise ValueError("a baseline estimate names its baseline, and only it")
        return self


class DecompositionTerm(StrEnum):
    """Terms of the savings decomposition, in their fixed order (brief §6)."""

    PREMIUM_BASELINE = "premium_baseline"
    ROUTING_SAVING = "routing_saving"
    COMPRESSION_SAVING = "compression_saving"
    CACHE_SAVING = "cache_saving"
    PROVIDER_CACHE_SAVING = "provider_cache_saving"
    EXTRA_COST = "extra_cost"
    ACTUALLY_PAID = "actually_paid"


DECOMPOSITION_ORDER: tuple[DecompositionTerm, ...] = tuple(DecompositionTerm)
"""premium − routing − compression − cache − provider cache + extra = paid."""


class TermValue(ContractModel):
    """One term: an amount, or not computed with a reason."""

    term: DecompositionTerm = field(Privacy.OPERATIONAL, "Which term.")
    status: CostStatus = field(Privacy.OPERATIONAL, "Computed or not.")
    amount: Money | None = field(Privacy.OPERATIONAL, "Set iff computed.", default=None)
    reason: NotComputedReason | None = field(
        Privacy.OPERATIONAL, "Set iff not computed.", default=None
    )

    @model_validator(mode="after")
    def _check(self) -> TermValue:
        if (self.status == CostStatus.COMPUTED) != (self.amount is not None):
            raise ValueError("amount is set exactly when computed")
        if (self.status == CostStatus.NOT_COMPUTED) != (self.reason is not None):
            raise ValueError("reason is set exactly when not computed")
        return self


class SavingsDecomposition(ContractModel):
    """Where the money went, per message or per session (brief §6, ADR-0020).

    ``premium_baseline − routing_saving − compression_saving − cache_saving −
    provider_cache_saving + extra_cost = actually_paid``, exactly (Decimal).
    ``extra_cost`` holds Metis overhead, failed, retried, and escalated
    attempts, and differences between local and provider-reported counts, so
    the identity holds with real data. The validator checks it.
    """

    scope: Name = field(Privacy.OPERATIONAL, "message or session.")
    messages: NonNegInt = field(Privacy.OPERATIONAL, "Messages summed (1 or more).")
    cache_hits: NonNegInt = field(Privacy.OPERATIONAL, "Messages served from cache.")
    terms: tuple[TermValue, ...] = field(
        Privacy.OPERATIONAL, "One per DecompositionTerm, in DECOMPOSITION_ORDER."
    )
    baseline_caveats: tuple[CostCaveat, ...] = field(
        Privacy.OPERATIONAL, "Caveats of the premium estimate.", default=()
    )
    price_table_version: Version | None = field(
        Privacy.OPERATIONAL, "Price table used.", default=None
    )

    @model_validator(mode="after")
    def _check(self) -> SavingsDecomposition:
        if tuple(t.term for t in self.terms) != DECOMPOSITION_ORDER:
            raise ValueError("terms must follow DECOMPOSITION_ORDER")
        if all(t.status == CostStatus.COMPUTED for t in self.terms):
            amounts = {t.term: t.amount for t in self.terms}
            if len({m.currency for m in amounts.values() if m}) != 1:
                raise ValueError("all terms must share one currency")
            a = {k: m.amount for k, m in amounts.items() if m}
            T = DecompositionTerm
            lhs = (
                a[T.PREMIUM_BASELINE]
                - a[T.ROUTING_SAVING]
                - a[T.COMPRESSION_SAVING]
                - a[T.CACHE_SAVING]
                - a[T.PROVIDER_CACHE_SAVING]
                + a[T.EXTRA_COST]
            )
            if lhs != a[T.ACTUALLY_PAID]:
                raise ValueError("decomposition does not sum to actually_paid")
        return self

    def term(self, term: DecompositionTerm) -> TermValue:
        return next(t for t in self.terms if t.term == term)
