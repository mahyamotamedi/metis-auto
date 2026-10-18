"""System ports: ``Clock``, ``IdSource`` (CMP-16), ``SpendLedger`` (CMP-26).

Seeded or fake implementations make replay reproducible and let backoff waits
run instantly in tests. Called by: application (pipeline, measurement, events).
Implemented by: adapters.system. Traces: FR-REQ-02, QA-REPRO, ADR-0003.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from metis_auto.contracts import Identifier, Money, UtcDatetime


@runtime_checkable
class Clock(Protocol):
    def now(self) -> UtcDatetime:
        """Wall time, timezone-aware UTC."""
        ...

    def monotonic_ms(self) -> float:
        """Monotonic milliseconds, for durations only."""
        ...

    def sleep_ms(self, ms: float) -> None:
        """Wait (retry backoff). Fake clocks advance instead of sleeping."""
        ...


@runtime_checkable
class IdSource(Protocol):
    def new_id(self, prefix: str) -> Identifier:
        """A new opaque ID such as ``req-…``; seeded sources are deterministic."""
        ...


@runtime_checkable
class SpendLedger(Protocol):
    """Running total of live spend against a cap (ADR-0003)."""

    def remaining(self) -> Money | None:
        """Cap left; None when no cap is configured (live calls are then refused)."""
        ...

    def charge(self, amount: Money) -> None: ...
