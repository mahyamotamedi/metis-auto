"""Savings decomposition (brief §6, FR-ACCT-04/05, ADR-0020).

Responsibility: split the gap between the premium baseline and what was
actually paid into terms, in a fixed order that sums exactly (Decimal):

    premium baseline        (premium model, full context, brief §5)
  − routing saving          premium − chosen model on the full context
  − compression saving      chosen model: full − sent (compressed) context
  − cache saving            on a hit: the chosen model's cost on the sent
                            context (the whole call avoided); else 0
  − provider-cache saving   on a miss: the cached-input discount the provider
                            reported on the answering call; else 0
  + extra cost              Metis overhead, failed / retried / escalated
                            attempts, and local-vs-reported count differences
  = actually paid

``extra cost`` is defined as the remainder, so the identity holds with real
data; it is shown, never hidden. "Chosen model" is the model that produced
the answer (on a hit: the routing target). Per message, then summed per
session. A term whose inputs are not computed is not computed (never zero).
Pure. Called by: application.accounting; (Demo milestone) the UI via wiring.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from metis_auto.contracts import (
    DECOMPOSITION_ORDER,
    Cost,
    CostCaveat,
    CostStatus,
    DecompositionTerm,
    Money,
    NotComputedReason,
    SavingsDecomposition,
    TermValue,
)

T = DecompositionTerm


def _value(term: DecompositionTerm, amount: Decimal | None, currency: str) -> TermValue:
    if amount is None:
        return TermValue(
            term=term,
            status=CostStatus.NOT_COMPUTED,
            reason=NotComputedReason.COMPONENT_NOT_COMPUTED,
        )
    return TermValue(
        term=term,
        status=CostStatus.COMPUTED,
        amount=Money(amount=amount, currency=currency),
    )


def _amount(cost: Cost | None) -> Decimal | None:
    if cost is None or cost.status != CostStatus.COMPUTED or cost.amount is None:
        return None
    return cost.amount.amount


def decompose_message(
    *,
    premium: Cost,
    chosen_full: Cost,
    chosen_sent: Cost,
    served_from_cache: bool,
    provider_cache_discount: Cost | None,
    actually_paid: Cost,
) -> SavingsDecomposition:
    """One message. ``chosen_full`` / ``chosen_sent``: the chosen model's cost
    on the full and on the sent context, with no provider-cache discount and
    the served answer's output. ``provider_cache_discount``: from
    ``cost.provider_cache_discount`` on the answering call (ignored on a hit).
    ``actually_paid``: the request total (attempts plus overhead)."""
    costs = (premium, chosen_full, chosen_sent, actually_paid)
    currencies = {c.amount.currency for c in costs if c.amount is not None}
    if provider_cache_discount is not None and provider_cache_discount.amount:
        currencies.add(provider_cache_discount.amount.currency)
    if len(currencies) > 1:
        terms = tuple(
            TermValue(
                term=t,
                status=CostStatus.NOT_COMPUTED,
                reason=NotComputedReason.CURRENCY_MISMATCH,
            )
            for t in DECOMPOSITION_ORDER
        )
        return SavingsDecomposition(
            scope="message",
            messages=1,
            cache_hits=int(served_from_cache),
            terms=terms,
            baseline_caveats=premium.caveats,
        )
    currency = currencies.pop() if currencies else "USD"

    p, full, sent, paid = (_amount(c) for c in costs)
    zero = Decimal(0)
    pc = zero if served_from_cache else _amount(provider_cache_discount)
    routing = None if p is None or full is None else p - full
    compression = None if full is None or sent is None else full - sent
    cache = sent if served_from_cache else zero
    parts = (p, routing, compression, cache, pc, paid)
    extra = None
    if all(v is not None for v in parts):
        extra = paid - (p - routing - compression - cache - pc)  # type: ignore[operator]
    values = {
        T.PREMIUM_BASELINE: p,
        T.ROUTING_SAVING: routing,
        T.COMPRESSION_SAVING: compression,
        T.CACHE_SAVING: cache,
        T.PROVIDER_CACHE_SAVING: pc,
        T.EXTRA_COST: extra,
        T.ACTUALLY_PAID: paid,
    }
    return SavingsDecomposition(
        scope="message",
        messages=1,
        cache_hits=int(served_from_cache),
        terms=tuple(_value(t, values[t], currency) for t in DECOMPOSITION_ORDER),
        baseline_caveats=premium.caveats,
        price_table_version=premium.price_table_version
        or actually_paid.price_table_version,
    )


def sum_decompositions(
    items: Sequence[SavingsDecomposition], scope: str = "session"
) -> SavingsDecomposition:
    """Per-session (or any) total: each term summed; not computed if any
    message's term is not computed. The identity still holds exactly."""
    if not items:
        raise ValueError("nothing to sum")
    currencies = {
        t.amount.currency for d in items for t in d.terms if t.amount is not None
    }
    if len(currencies) > 1:
        raise ValueError("decompositions in different currencies")
    currency = currencies.pop() if currencies else "USD"
    terms = []
    for term in DECOMPOSITION_ORDER:
        found = [d.term(term) for d in items]
        if any(t.status != CostStatus.COMPUTED for t in found):
            reasons = {t.reason for t in found if t.reason}
            terms.append(
                TermValue(
                    term=term,
                    status=CostStatus.NOT_COMPUTED,
                    reason=reasons.pop()
                    if len(reasons) == 1
                    else NotComputedReason.COMPONENT_NOT_COMPUTED,
                )
            )
            continue
        total = sum((t.amount.amount for t in found if t.amount), Decimal(0))
        terms.append(_value(term, total, currency))
    versions = {d.price_table_version for d in items if d.price_table_version}
    caveats: dict[CostCaveat, None] = {}
    for d in items:
        caveats.update(dict.fromkeys(d.baseline_caveats))
    return SavingsDecomposition(
        scope=scope,
        messages=sum(d.messages for d in items),
        cache_hits=sum(d.cache_hits for d in items),
        terms=tuple(terms),
        baseline_caveats=tuple(caveats),
        price_table_version=versions.pop() if len(versions) == 1 else None,
    )
