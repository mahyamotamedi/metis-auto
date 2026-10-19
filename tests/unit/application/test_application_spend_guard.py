"""Spend guard (CMP-17): actual cost charged; an uncomputable actual cost
charges the pre-call estimate and stops live calls (ADR-0021). Offline."""

from decimal import Decimal

from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.system import InMemorySpendLedger
from metis_auto.application.pipeline import SpendGuard


def _guard(cap="1.00"):
    ledger = InMemorySpendLedger(ex.usd(cap))
    return SpendGuard(ledger), ledger


def test_allows_within_cap_and_charges_the_actual_cost():
    guard, ledger = _guard()
    estimate = ex.cost_estimate()
    assert guard.allows(estimate)
    guard.charge(ex.computed("0.25"), estimate)
    assert ledger.remaining().amount == Decimal("0.75")
    assert guard.stopped is None and guard.allows(estimate)


def test_uncomputable_cost_charges_the_estimate_and_stops():
    guard, ledger = _guard()
    estimate = ex.cost_estimate()
    guard.charge(ex.not_computed(), estimate)
    assert ledger.remaining().amount == Decimal("1.00") - estimate.cost.amount.amount
    assert guard.stopped is not None and "price_unknown" in guard.stopped
    assert not guard.allows(estimate)
    assert guard.remaining().amount == 0


def test_missing_cost_is_treated_as_uncomputable():
    guard, _ = _guard()
    guard.charge(None, ex.cost_estimate())
    assert guard.stopped is not None
