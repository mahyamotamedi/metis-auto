"""In-memory spend ledger for one run (CMP-26, ADR-0003).

Responsibility: track live spend against a per-run cap. No cap means
``remaining()`` is None, and the spend guard then blocks live calls.
Implements ``ports.SpendLedger``. Status: provisional; a cumulative ledger
(file or database) comes with the first multi-run live budget.
"""

from __future__ import annotations

from metis_auto.contracts import Money


class InMemorySpendLedger:
    def __init__(self, cap: Money | None) -> None:
        self._cap = cap
        self._spent = Money(amount=0, currency=cap.currency) if cap else None

    def remaining(self) -> Money | None:
        if self._cap is None or self._spent is None:
            return None
        return Money(
            amount=self._cap.amount - self._spent.amount, currency=self._cap.currency
        )

    def charge(self, amount: Money) -> None:
        if self._spent is None:
            raise RuntimeError("no spending cap configured; live spend is refused")
        if amount.currency != self._spent.currency:
            raise ValueError("charge currency differs from the cap currency")
        self._spent = Money(
            amount=self._spent.amount + amount.amount, currency=self._spent.currency
        )
