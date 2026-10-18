"""Persistent, cumulative spend ledger (ADR-0018): lifetime total across runs
and instances, per-run cap, warnings, fail-closed on a damaged file. Amounts
are synthetic; no calls are made."""

import json
import logging
from decimal import Decimal

import pytest

from metis_auto.adapters.system import FileSpendLedger, LedgerError
from metis_auto.application.pipeline import SpendGuard
from metis_auto.contracts import Money
from metis_auto.ports import SpendLedger


def usd(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="USD")


def ledger(path, run_id="run-a", lifetime="20", run="1", **kw) -> FileSpendLedger:
    return FileSpendLedger(
        path,
        run_id=run_id,
        lifetime_cap=usd(lifetime),
        run_cap=usd(run) if run else None,
        **kw,
    )


def test_implements_the_port(tmp_path):
    assert isinstance(ledger(tmp_path / "l.jsonl"), SpendLedger)


def test_empty_or_missing_ledger_leaves_the_run_cap(tmp_path):
    book = ledger(tmp_path / "spend" / "l.jsonl")
    assert book.remaining() == usd("1")
    assert book.status().charges == 0


def test_lifetime_total_persists_across_runs_and_instances(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger(path, run_id="run-a").charge(usd("0.75"))
    ledger(path, run_id="run-b").charge(usd("0.5"))
    third = ledger(path, run_id="run-c", lifetime="1.5", run="1")
    status = third.status()
    assert status.lifetime_spent == Decimal("1.25")
    assert status.run_spent == 0
    assert third.remaining() == usd("0.25")  # the lifetime cap binds


def test_the_per_run_cap_counts_only_this_run(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger(path, run_id="run-a").charge(usd("0.9"))
    assert ledger(path, run_id="run-a").remaining() == usd("0.1")
    assert ledger(path, run_id="run-b").remaining() == usd("1")


def test_remaining_never_goes_negative(tmp_path):
    book = ledger(tmp_path / "l.jsonl", run="0.1")
    book.charge(usd("0.3"))  # an actual cost above the estimate
    assert book.remaining() == usd("0")


def test_records_hold_no_content(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger(path).charge(usd("0.001"))
    (record,) = [json.loads(line) for line in path.read_text().splitlines()]
    assert set(record) == {"v", "time", "run_id", "amount", "currency"}
    assert record["amount"] == "0.001"


def test_warnings_at_50_and_80_percent(tmp_path, caplog):
    book = ledger(tmp_path / "l.jsonl", lifetime="10", run="10")
    with caplog.at_level(logging.WARNING):
        book.charge(usd("4"))
        assert not caplog.records
        book.charge(usd("1.5"))  # 55%
        book.charge(usd("1"))  # 65%: no new threshold
        book.charge(usd("2"))  # 85%
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 2
    assert "50%" in messages[0] and "80%" in messages[1]


def test_a_malformed_ledger_fails_closed(tmp_path):
    path = tmp_path / "l.jsonl"
    path.write_text('{"v": 1, "amount": "oops"}\n')
    with pytest.raises(LedgerError):
        ledger(path).remaining()
    with pytest.raises(LedgerError):
        ledger(path).charge(usd("0.01"))


def test_another_currency_in_the_file_fails_closed(tmp_path):
    path = tmp_path / "l.jsonl"
    path.write_text(
        json.dumps(
            {"v": 1, "time": "t", "run_id": "r", "amount": "1", "currency": "EUR"}
        )
        + "\n"
    )
    with pytest.raises(LedgerError):
        ledger(path).remaining()


def test_charges_in_another_currency_or_negative_are_refused(tmp_path):
    book = ledger(tmp_path / "l.jsonl")
    with pytest.raises(ValueError):
        book.charge(Money(amount=Decimal("1"), currency="EUR"))
    with pytest.raises(ValueError):
        book.charge(usd("-1"))


def test_spend_guard_uses_the_tighter_cap(tmp_path):
    book = ledger(tmp_path / "l.jsonl", run="0.5")
    guard = SpendGuard(book)
    assert guard.remaining() == usd("0.5")
    book.charge(usd("0.5"))
    assert guard.remaining() == usd("0")
