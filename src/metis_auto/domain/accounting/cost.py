"""Cost from usage and the price table (CMP-09).

Responsibility: turn ``TokenUsage`` and versioned prices into ``Cost`` with
its provenance, total a request's costs, and make the spend guard's pre-call
estimate. Pure; prices are data (``PriceTable``), never code.
Called by: application.pipeline (attempts, totals, avoided cost, spend guard).
Config: ``AccountingConfig``. Traces: FR-ACCT-01…06, ADR-0002, ADR-0006 pt 3.

Status: skeleton. Input and output prices only. TODO(Stage 7): cached-input
and reasoning prices, effective dates, chat-template overhead, the final
price schema (contracts.md O-3).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from metis_auto.contracts import (
    CatalogueEntry,
    ContractModel,
    Cost,
    CostBasis,
    CostEstimate,
    CostStatus,
    Fidelity,
    Money,
    NotComputedReason,
    PriceEntry,
    PriceTable,
    TokenCount,
    TokenType,
    TokenUsage,
)

from .tokens import worst_fidelity


class AccountingConfig(ContractModel):
    currency: str = "USD"
    """Currency of totals when there is nothing to add (e.g. no overhead)."""


def not_computed(reason: NotComputedReason, basis: CostBasis) -> Cost:
    return Cost(status=CostStatus.NOT_COMPUTED, basis=basis, reason=reason)


def _price(prices: PriceTable, ref: str, token_type: TokenType) -> PriceEntry | None:
    return next(
        (
            p
            for p in prices.entries
            if p.price_ref == ref and p.token_type == token_type
        ),
        None,
    )


def cost_of(
    usage: TokenUsage | None,
    target: CatalogueEntry,
    prices: PriceTable,
    basis: CostBasis = CostBasis.ACTUAL,
) -> Cost:
    """Cost of one call's usage on ``target``."""
    if usage is None or usage.output is None:
        return not_computed(NotComputedReason.USAGE_UNKNOWN, basis)
    if target.price_ref is None:
        return not_computed(NotComputedReason.PRICE_UNKNOWN, basis)
    pairs = [
        (_price(prices, target.price_ref, TokenType.INPUT), usage.input),
        (_price(prices, target.price_ref, TokenType.OUTPUT), usage.output),
    ]
    if any(p is None or p.amount is None for p, _ in pairs):
        return not_computed(NotComputedReason.PRICE_UNKNOWN, basis)
    if len({p.currency for p, _ in pairs}) != 1:
        return not_computed(NotComputedReason.CURRENCY_MISMATCH, basis)
    amount = sum(
        (Decimal(count.tokens) * p.amount / p.per_tokens for p, count in pairs),
        Decimal(0),
    )
    return Cost(
        status=CostStatus.COMPUTED,
        basis=basis,
        amount=Money(amount=amount, currency=pairs[0][0].currency),
        price_table_version=prices.version,
        price_refs=(target.price_ref,),
        token_fidelity=worst_fidelity(c.fidelity for _, c in pairs),
    )


def total_cost(
    costs: Sequence[Cost],
    basis: CostBasis,
    prices: PriceTable,
    config: AccountingConfig,
) -> Cost:
    """Sum of costs (FR-ACCT-03). Not computed if any part is not computed."""
    if any(c.status != CostStatus.COMPUTED for c in costs):
        return not_computed(NotComputedReason.COMPONENT_NOT_COMPUTED, basis)
    currencies = {c.amount.currency for c in costs if c.amount is not None}
    if len(currencies) > 1:
        return not_computed(NotComputedReason.CURRENCY_MISMATCH, basis)
    currency = currencies.pop() if currencies else config.currency
    amount = sum((c.amount.amount for c in costs if c.amount), Decimal(0))
    return Cost(
        status=CostStatus.COMPUTED,
        basis=basis,
        amount=Money(amount=amount, currency=currency),
        price_table_version=prices.version,
        price_refs=tuple(dict.fromkeys(r for c in costs for r in c.price_refs)),
        token_fidelity=worst_fidelity(
            c.token_fidelity for c in costs if c.token_fidelity
        ),
    )


def pre_call_estimate(
    target: CatalogueEntry,
    input_tokens: TokenCount,
    assumed_output_tokens: int,
    prices: PriceTable,
) -> CostEstimate:
    """Estimate for the spend guard: counted input plus the configured maximum
    output (attempts.md §5)."""
    assumed = TokenCount(
        tokens=assumed_output_tokens,
        fidelity=Fidelity.APPROXIMATION,
        method="assumed_max_output",
    )
    usage = TokenUsage(model_id=target.model_id, input=input_tokens, output=assumed)
    return CostEstimate(
        model_id=target.model_id,
        input_tokens=input_tokens,
        assumed_output_tokens=assumed_output_tokens,
        cost=cost_of(usage, target, prices, CostBasis.PRE_CALL_ESTIMATE),
    )
