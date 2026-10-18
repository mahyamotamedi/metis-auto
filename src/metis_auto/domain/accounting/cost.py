"""Cost from usage and the price table (CMP-09).

Responsibility: turn ``TokenUsage`` and versioned prices into ``Cost`` with
its provenance and caveats, total a request's costs, make the spend guard's
pre-call estimate, and price the provider-cache discount. Pure; prices are
data (``PriceTable``), never code.
Called by: application.pipeline (attempts, totals, avoided cost, spend guard),
application.accounting, domain.accounting.baseline and .savings.
Config: ``AccountingConfig``. Traces: FR-ACCT-01…06, ADR-0002, ADR-0006 pt 3,
ADR-0020.

What is billed (token_accounting.md §3–§4):
- uncached input (``input − cached_input − cache_write``) at the input price;
  cached input at the cached-input price; cache writes at the cache-write
  price (matching ``cache_write_ttl``); output (which includes reasoning) at
  the output price;
- the **context tier** is chosen by the call's input tokens and prices every
  token type of the call;
- a price that a non-zero count needs but the table lacks → "not computed".
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from metis_auto.contracts import (
    CatalogueEntry,
    ContractModel,
    Cost,
    CostBasis,
    CostCaveat,
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

from .tokens import sum_counts, worst_fidelity

HIDDEN_REASONING = "hidden_reasoning_billed_as_output"
"""Catalogue capability: the model emits hidden reasoning tokens that are
billed as output (verified with a source, e.g. ``gpt-5-nano``)."""


class AccountingConfig(ContractModel):
    currency: str = "USD"
    """Currency of totals when there is nothing to add (e.g. no overhead)."""


def not_computed(reason: NotComputedReason, basis: CostBasis) -> Cost:
    return Cost(status=CostStatus.NOT_COMPUTED, basis=basis, reason=reason)


def bills_hidden_reasoning(target: CatalogueEntry) -> bool:
    return any(c.name == HIDDEN_REASONING and c.verified for c in target.capabilities)


def _rows(prices: PriceTable, ref: str, input_tokens: int) -> list[PriceEntry]:
    """Rows of ``ref`` whose context tier applies to ``input_tokens``."""
    return [p for p in prices.entries if p.price_ref == ref and p.covers(input_tokens)]


def _price(
    rows: Sequence[PriceEntry], token_type: TokenType, ttl: str | None = None
) -> PriceEntry | None:
    return next(
        (
            p
            for p in rows
            if p.token_type == token_type
            and (token_type != TokenType.CACHE_WRITE or p.cache_ttl == ttl)
        ),
        None,
    )


def _tier_uncertain(prices: PriceTable, ref: str, input_tokens: int) -> bool:
    """Input above a row's bound but within its uncertain extension."""
    return any(
        p.price_ref == ref
        and p.max_input_tokens is not None
        and p.max_input_tokens_uncertain_up_to is not None
        and p.max_input_tokens < input_tokens <= p.max_input_tokens_uncertain_up_to
        for p in prices.entries
    )


def _caveats(
    usage: TokenUsage,
    target: CatalogueEntry,
    prices: PriceTable,
    rows: Sequence[PriceEntry],
) -> tuple[CostCaveat, ...]:
    found: list[CostCaveat] = []
    assert usage.output is not None
    if (
        bills_hidden_reasoning(target)
        and usage.reasoning is None
        and usage.output.fidelity != Fidelity.PROVIDER_REPORTED
    ):
        found.append(CostCaveat.REASONING_NOT_COUNTED)
    overhead = usage.template_overhead
    if overhead and overhead.tokens and overhead.fidelity == Fidelity.APPROXIMATION:
        found.append(CostCaveat.TEMPLATE_OVERHEAD_APPROXIMATED)
    assert target.price_ref is not None
    if _tier_uncertain(prices, target.price_ref, usage.input.tokens):
        found.append(CostCaveat.CONTEXT_TIER_BOUNDARY_UNCERTAIN)
    if (
        usage.input.fidelity == Fidelity.PROVIDER_REPORTED
        and usage.cached_input is None
        and _price(rows, TokenType.CACHED_INPUT) is not None
    ):
        found.append(CostCaveat.CACHED_INPUT_NOT_REPORTED)
    return tuple(found)


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
    rows = _rows(prices, target.price_ref, usage.input.tokens)
    cached = usage.cached_input.tokens if usage.cached_input else 0
    written = usage.cache_write.tokens if usage.cache_write else 0
    parts: list[tuple[PriceEntry | None, int]] = [
        (_price(rows, TokenType.INPUT), usage.input.tokens - cached - written),
        (_price(rows, TokenType.OUTPUT), usage.output.tokens),
    ]
    if cached:
        parts.append((_price(rows, TokenType.CACHED_INPUT), cached))
    if written:
        ttl = usage.cache_write_ttl
        parts.append((_price(rows, TokenType.CACHE_WRITE, ttl), written))
    if any(p is None or p.amount is None for p, _ in parts):
        return not_computed(NotComputedReason.PRICE_UNKNOWN, basis)
    priced = [(p, n) for p, n in parts if p is not None]
    if len({p.currency for p, _ in priced}) != 1:
        return not_computed(NotComputedReason.CURRENCY_MISMATCH, basis)
    amount = sum(
        (Decimal(n) * p.amount / p.per_tokens for p, n in priced if p.amount),
        Decimal(0),
    )
    counts = (usage.input, usage.output, usage.cached_input, usage.cache_write)
    return Cost(
        status=CostStatus.COMPUTED,
        basis=basis,
        amount=Money(amount=amount, currency=priced[0][0].currency),
        price_table_version=prices.version,
        price_refs=(target.price_ref,),
        token_fidelity=worst_fidelity(c.fidelity for c in counts if c is not None),
        price_tier=priced[0][0].tier,
        caveats=_caveats(usage, target, prices, rows),
    )


def provider_cache_discount(
    usage: TokenUsage | None, target: CatalogueEntry, prices: PriceTable
) -> Cost:
    """What the provider cache saved on one call: the cost with cached input
    and cache writes priced as ordinary input, minus the actual cost. Zero
    when nothing was cached; negative when cache writes cost more than they
    saved (brief §6, "provider-cache saving")."""
    basis = CostBasis.AVOIDED_ESTIMATE
    actual = cost_of(usage, target, prices, basis)
    if usage is None or actual.status != CostStatus.COMPUTED:
        return actual
    plain = cost_of(
        usage.model_copy(
            update={"cached_input": None, "cache_write": None, "cache_write_ttl": None}
        ),
        target,
        prices,
        basis,
    )
    if plain.status != CostStatus.COMPUTED:
        return plain
    assert plain.amount is not None and actual.amount is not None
    return actual.model_copy(
        update={
            "amount": Money(
                amount=plain.amount.amount - actual.amount.amount,
                currency=actual.amount.currency,
            )
        }
    )


def total_cost(
    costs: Sequence[Cost],
    basis: CostBasis,
    prices: PriceTable,
    config: AccountingConfig,
) -> Cost:
    """Sum of costs (FR-ACCT-03). Not computed if any part is not computed.
    Caveats are the union of the parts' caveats."""
    if any(c.status != CostStatus.COMPUTED for c in costs):
        return not_computed(NotComputedReason.COMPONENT_NOT_COMPUTED, basis)
    currencies = {c.amount.currency for c in costs if c.amount is not None}
    if len(currencies) > 1:
        return not_computed(NotComputedReason.CURRENCY_MISMATCH, basis)
    currency = currencies.pop() if currencies else config.currency
    amount = sum((c.amount.amount for c in costs if c.amount), Decimal(0))
    tiers = {c.price_tier for c in costs if c.price_tier}
    return Cost(
        status=CostStatus.COMPUTED,
        basis=basis,
        amount=Money(amount=amount, currency=currency),
        price_table_version=prices.version,
        price_refs=tuple(dict.fromkeys(r for c in costs for r in c.price_refs)),
        token_fidelity=worst_fidelity(
            c.token_fidelity for c in costs if c.token_fidelity
        ),
        price_tier=tiers.pop() if len(tiers) == 1 else None,
        caveats=tuple(dict.fromkeys(v for c in costs for v in c.caveats)),
    )


def pre_call_estimate(
    target: CatalogueEntry,
    input_tokens: TokenCount,
    assumed_output_tokens: int,
    prices: PriceTable,
    template_overhead: TokenCount | None = None,
) -> CostEstimate:
    """Estimate for the spend guard: counted input (plus the chat-template
    overhead when known) and the configured maximum output, which bounds
    hidden reasoning too (attempts.md §5)."""
    assumed = TokenCount(
        tokens=assumed_output_tokens,
        fidelity=Fidelity.APPROXIMATION,
        method="assumed_max_output",
    )
    billed_input = sum_counts(c for c in (input_tokens, template_overhead) if c)
    assert billed_input is not None
    usage = TokenUsage(
        model_id=target.model_id,
        input=billed_input,
        output=assumed,
        template_overhead=template_overhead,
    )
    return CostEstimate(
        model_id=target.model_id,
        input_tokens=billed_input,
        assumed_output_tokens=assumed_output_tokens,
        cost=cost_of(usage, target, prices, CostBasis.PRE_CALL_ESTIMATE),
    )
