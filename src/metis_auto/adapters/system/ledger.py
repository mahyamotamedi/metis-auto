"""Spend ledgers (CMP-26; ADR-0003, ADR-0018).

Responsibility: track live spend against caps. Implements ``ports.SpendLedger``.

- ``InMemorySpendLedger``: one run, one cap; tests and offline tools.
- ``FileSpendLedger``: the **persistent, cumulative** ledger for live calls.
  An append-only JSON Lines file shared by every run on this machine (and the
  container, through a bind mount). ``remaining()`` is the smaller of what is
  left under the lifetime cap (all runs) and under the per-run cap (this
  run's ``run_id``). Fails closed: an unreadable or malformed ledger raises,
  so no live call can proceed on a total it cannot trust.

Records hold amounts, currency, time, and the run ID only: no content.
Deleting the file resets the lifetime total, so it must never be deleted
(docs/guides/local_development.md); the Metis dashboard's own limit is the
second safety net (brief §1, Q-29).
Built by: wiring (``wiring.from_settings``). Called by: application.pipeline
via the spend guard.
"""

from __future__ import annotations

import fcntl
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from metis_auto.contracts import Money

LEDGER_FORMAT = 1
log = logging.getLogger(__name__)


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


class LedgerError(RuntimeError):
    """The ledger cannot be trusted; live calls must stop."""


@dataclass(frozen=True)
class BudgetStatus:
    """Content-free budget summary for scripts and the future cost panel."""

    currency: str
    lifetime_spent: Decimal
    lifetime_cap: Decimal
    run_spent: Decimal
    run_cap: Decimal | None
    charges: int

    @property
    def lifetime_fraction(self) -> float:
        return float(self.lifetime_spent / self.lifetime_cap)


class FileSpendLedger:
    """Cumulative ledger in an append-only JSON Lines file.

    One line per charge: ``{"v": 1, "time": ISO-UTC, "run_id": ..., "amount":
    "0.0012", "currency": "USD"}``. Amounts are decimal strings. Reads take a
    shared lock and charges an exclusive one (POSIX ``flock``), so concurrent
    runs on one machine see a consistent total.
    """

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        lifetime_cap: Money,
        run_cap: Money | None = None,
        warn_at: Sequence[float] = (0.5, 0.8),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if run_cap is not None and run_cap.currency != lifetime_cap.currency:
            raise ValueError("run cap and lifetime cap use different currencies")
        self._path = Path(path)
        self._run_id = run_id
        self._lifetime_cap = lifetime_cap
        self._run_cap = run_cap
        self._warn_at = tuple(sorted(warn_at))
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def path(self) -> Path:
        return self._path

    def remaining(self) -> Money:
        status = self.status()
        left = status.lifetime_cap - status.lifetime_spent
        if status.run_cap is not None:
            left = min(left, status.run_cap - status.run_spent)
        return Money(amount=max(left, Decimal(0)), currency=status.currency)

    def charge(self, amount: Money) -> None:
        currency = self._lifetime_cap.currency
        if amount.currency != currency:
            raise ValueError("charge currency differs from the cap currency")
        if amount.amount < 0:
            raise ValueError("a charge cannot be negative")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.seek(0)
                before = self._summarise(handle.read()).lifetime_spent
                record = {
                    "v": LEDGER_FORMAT,
                    "time": self._now().isoformat(),
                    "run_id": self._run_id,
                    "amount": str(amount.amount),
                    "currency": currency,
                }
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
        self._warn_on_crossing(before, before + amount.amount)

    def status(self) -> BudgetStatus:
        if not self._path.exists():
            return self._summarise("")
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                fcntl.flock(handle, fcntl.LOCK_SH)
                try:
                    text = handle.read()
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError as exc:
            raise LedgerError(f"spend ledger unreadable: {self._path}") from exc
        return self._summarise(text)

    def _summarise(self, text: str) -> BudgetStatus:
        currency = self._lifetime_cap.currency
        lifetime = run = Decimal(0)
        count = 0
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                value = Decimal(record["amount"])
                if record["v"] != LEDGER_FORMAT or record["currency"] != currency:
                    raise ValueError
            except (ValueError, KeyError, TypeError, InvalidOperation):
                raise LedgerError(
                    f"spend ledger {self._path} line {number} is malformed or in "
                    "another currency; live calls are refused until it is fixed"
                ) from None
            lifetime += value
            count += 1
            if record.get("run_id") == self._run_id:
                run += value
        return BudgetStatus(
            currency=currency,
            lifetime_spent=lifetime,
            lifetime_cap=self._lifetime_cap.amount,
            run_spent=run,
            run_cap=self._run_cap.amount if self._run_cap else None,
            charges=count,
        )

    def _warn_on_crossing(self, before: Decimal, after: Decimal) -> None:
        cap = self._lifetime_cap.amount
        for fraction in self._warn_at:
            threshold = cap * Decimal(str(fraction))
            if before < threshold <= after:
                log.warning(
                    "live spend passed %d%% of the lifetime budget: %s of %s %s",
                    round(fraction * 100),
                    after,
                    cap,
                    self._lifetime_cap.currency,
                )
