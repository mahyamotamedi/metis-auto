"""Spend guard (CMP-17; ADR-0003, attempts.md §5).

Responsibility: before every **live** attempt, allow it only if the pre-call
estimate fits in what is left under the cap; afterwards, charge the actual
cost. Conservative: no cap, an estimate that is "not computed", or a currency
mismatch all block. Fake and replay clients are never checked.
Called by: application.pipeline. Calls: port ``SpendLedger``.
Built by: wiring, which refuses a live client without a cap.
"""

from __future__ import annotations

from metis_auto.contracts import Cost, CostEstimate, CostStatus, Money
from metis_auto.ports import SpendLedger


class SpendGuard:
    def __init__(self, ledger: SpendLedger) -> None:
        self._ledger = ledger

    def remaining(self) -> Money | None:
        return self._ledger.remaining()

    def allows(self, estimate: CostEstimate) -> bool:
        left = self._ledger.remaining()
        amount = estimate.cost.amount
        if (
            left is None
            or amount is None
            or estimate.cost.status != CostStatus.COMPUTED
        ):
            return False
        return amount.currency == left.currency and amount.amount <= left.amount

    def charge(self, cost: Cost | None) -> None:
        # TODO(first live adapter): an uncomputable actual cost must stop the
        # run, since the cap can no longer be enforced.
        if cost is not None and cost.amount is not None:
            self._ledger.charge(cost.amount)
