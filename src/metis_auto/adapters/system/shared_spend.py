"""One shared spend total across the team's machines (decision 7 of the
master-plan coverage review: "sum the four ledgers before each paid run").

Each machine keeps its own append-only ledger (``FileSpendLedger``, ADR-0018);
nothing here edits or deletes one.

- ``summarise_ledger`` reads a ledger **read-only** and returns a content-free
  summary: machine label, total, number of charges, per-run totals (run IDs
  are operational names), the newest charge time and the file's sha256. It
  holds no prompt, answer or key, so it can be shared and committed.
- ``merge_summaries`` sums the newest summary per machine into the team total.
- ``SharedSpendLedger`` implements ``ports.SpendLedger`` over this machine's
  ledger: what is left is the smaller of the local ledger's own ``remaining()``
  and ``ceiling − (other machines' total + this machine's total)``. Charges go
  to the local ledger only. It **fails closed**: a missing machine, a summary
  older than ``max_age`` or a summary of this machine itself among the
  "others" refuses (``SharedSpendError``) instead of guessing a total.

Built by: wiring (paid benchmark runs). Traces: ADR-0003, ADR-0018,
ADR-0053, decision 7. Status: provisional.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from metis_auto.contracts import Money

SUMMARY_FORMAT = "ledger-summary-v1"


class SharedSpendError(RuntimeError):
    """The shared total cannot be trusted; paid calls must not start."""


@dataclass(frozen=True)
class LedgerSummary:
    machine: str
    currency: str
    total: Decimal
    charges: int
    by_run: dict[str, Decimal] = field(default_factory=dict)
    newest_charge: str | None = None
    created_at: str = ""
    ledger_sha256: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "format": SUMMARY_FORMAT,
            "machine": self.machine,
            "currency": self.currency,
            "total": str(self.total),
            "charges": self.charges,
            "by_run": {k: str(v) for k, v in sorted(self.by_run.items())},
            "newest_charge": self.newest_charge,
            "created_at": self.created_at,
            "ledger_sha256": self.ledger_sha256,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LedgerSummary:
        if data.get("format") != SUMMARY_FORMAT:
            raise SharedSpendError("not a ledger-summary-v1 file")
        try:
            return cls(
                machine=str(data["machine"]),
                currency=str(data["currency"]),
                total=Decimal(data["total"]),
                charges=int(data["charges"]),
                by_run={k: Decimal(v) for k, v in data.get("by_run", {}).items()},
                newest_charge=data.get("newest_charge"),
                created_at=str(data["created_at"]),
                ledger_sha256=data.get("ledger_sha256"),
            )
        except (KeyError, ValueError, InvalidOperation, TypeError) as exc:
            raise SharedSpendError(f"malformed ledger summary: {exc}") from None


def summarise_ledger(
    path: Path, *, machine: str, currency: str, created_at: datetime
) -> LedgerSummary:
    """Read-only. A missing ledger is a machine that has spent nothing."""
    if not machine.strip():
        raise ValueError("machine label is required")
    total = Decimal(0)
    by_run: dict[str, Decimal] = {}
    count = 0
    newest: str | None = None
    raw = b""
    if Path(path).exists():
        raw = Path(path).read_bytes()
        for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                amount = Decimal(record["amount"])
                if record["currency"] != currency:
                    raise ValueError
            except (ValueError, KeyError, TypeError, InvalidOperation):
                raise SharedSpendError(
                    f"ledger line {number} is malformed or in another currency"
                ) from None
            total += amount
            count += 1
            run = str(record.get("run_id", ""))
            by_run[run] = by_run.get(run, Decimal(0)) + amount
            t = record.get("time")
            if isinstance(t, str) and (newest is None or t > newest):
                newest = t
    return LedgerSummary(
        machine=machine,
        currency=currency,
        total=total,
        charges=count,
        by_run=by_run,
        newest_charge=newest,
        created_at=created_at.isoformat(),
        ledger_sha256=hashlib.sha256(raw).hexdigest() if raw else None,
    )


def merge_summaries(summaries: Iterable[LedgerSummary]) -> dict[str, Any]:
    """The newest summary per machine and their sum (content-free)."""
    newest: dict[str, LedgerSummary] = {}
    currencies = set()
    for s in summaries:
        currencies.add(s.currency)
        old = newest.get(s.machine)
        if old is None or s.created_at > old.created_at:
            newest[s.machine] = s
    if len(currencies) > 1:
        raise SharedSpendError("summaries use different currencies")
    total = sum((s.total for s in newest.values()), Decimal(0))
    return {
        "machines": {
            m: {"total": str(s.total), "charges": s.charges, "created_at": s.created_at}
            for m, s in sorted(newest.items())
        },
        "team_total": str(total),
        "currency": currencies.pop() if currencies else None,
    }


class _LocalLedger(Protocol):
    def remaining(self) -> Money: ...

    def charge(self, amount: Money) -> None: ...

    def status(self) -> Any: ...


class SharedSpendLedger:
    """``ports.SpendLedger``: this machine's ledger, bounded by the team total."""

    def __init__(
        self,
        local: _LocalLedger,
        *,
        machine: str,
        others: Sequence[LedgerSummary],
        expected_machines: Sequence[str],
        ceiling: Money,
        now: datetime,
        max_age: timedelta,
    ) -> None:
        names = {s.machine for s in others}
        if machine in names:
            raise SharedSpendError(
                "this machine's own summary is among the others: it would be "
                "counted twice"
            )
        missing = sorted(set(expected_machines) - {machine} - names)
        if missing:
            raise SharedSpendError(f"no ledger summary from: {', '.join(missing)}")
        for s in others:
            if s.currency != ceiling.currency:
                raise SharedSpendError(f"{s.machine}: currency differs")
            age = now - datetime.fromisoformat(s.created_at)
            if age > max_age:
                raise SharedSpendError(
                    f"{s.machine}: summary is {age} old (limit {max_age})"
                )
        newest: dict[str, LedgerSummary] = {}
        for s in others:
            if s.machine not in newest or s.created_at > newest[s.machine].created_at:
                newest[s.machine] = s
        self._local = local
        self._others_total = sum((s.total for s in newest.values()), Decimal(0))
        self._ceiling = ceiling

    @property
    def others_total(self) -> Decimal:
        return self._others_total

    def team_total(self) -> Decimal:
        return self._others_total + self._local.status().lifetime_spent

    def remaining(self) -> Money:
        local_left = self._local.remaining()
        shared_left = self._ceiling.amount - self.team_total()
        left = max(min(local_left.amount, shared_left), Decimal(0))
        return Money(amount=left, currency=self._ceiling.currency)

    def charge(self, amount: Money) -> None:
        self._local.charge(amount)
