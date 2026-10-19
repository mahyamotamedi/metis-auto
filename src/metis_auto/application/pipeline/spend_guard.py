"""Spend guard (CMP-17; ADR-0003, ADR-0018, ADR-0021, attempts.md §5).

Responsibility: before every **live** attempt, allow it only if the pre-call
estimate fits in what is left under the cap; afterwards, charge the actual
cost. Conservative: no cap, an estimate that is "not computed", or a currency
mismatch all block. Fake and replay clients are never checked.

An actual cost that cannot be computed (a live error with no reported usage,
or a missing price) would leave the ledger unable to enforce the cap. The
guard then charges the attempt's **pre-call estimate** (the best figure there
is, never zero) and **stops**: every later live attempt in this run is
blocked (ADR-0021).
Called by: application.pipeline. Calls: port ``SpendLedger``.
Built by: wiring, which refuses a live client without a cap.
"""

from __future__ import annotations

import logging

from metis_auto.contracts import Cost, CostEstimate, CostStatus, Money
from metis_auto.ports import SpendLedger

log = logging.getLogger(__name__)


class SpendGuard:
    def __init__(self, ledger: SpendLedger) -> None:
        self._ledger = ledger
        self._stopped: str | None = None

    @property
    def stopped(self) -> str | None:
        """Why live calls are stopped for this run; None while they may go on."""
        return self._stopped

    def remaining(self) -> Money | None:
        left = self._ledger.remaining()
        if self._stopped is not None and left is not None:
            return Money(amount=0, currency=left.currency)
        return left

    def allows(self, estimate: CostEstimate) -> bool:
        if self._stopped is not None:
            return False
        left = self._ledger.remaining()
        amount = estimate.cost.amount
        if (
            left is None
            or amount is None
            or estimate.cost.status != CostStatus.COMPUTED
        ):
            return False
        return amount.currency == left.currency and amount.amount <= left.amount

    def charge(self, cost: Cost | None, estimate: CostEstimate) -> None:
        """Charge an allowed attempt: its actual cost, or, when that is not
        computed, its pre-call estimate, and then stop live calls."""
        if (
            cost is not None
            and cost.status == CostStatus.COMPUTED
            and cost.amount is not None
        ):
            self._ledger.charge(cost.amount)
            return
        fallback = estimate.cost.amount
        if fallback is None:  # allows() never passes such an estimate
            raise RuntimeError("cannot charge an attempt with no estimate")
        self._ledger.charge(fallback)
        reason = cost.reason if cost is not None else None
        self._stopped = (
            "actual cost not computed"
            + (f" ({reason.value})" if reason is not None else "")
            + "; charged the pre-call estimate and stopped live calls for this run"
        )
        log.warning("spend guard: %s", self._stopped)
