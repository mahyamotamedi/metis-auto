"""Clocks. ``SystemClock`` for real runs; ``FakeClock`` for reproducible
tests (time moves only when told, and on ``sleep_ms``). Implements
``ports.Clock``. Status: stable."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> float:
        return time.monotonic() * 1000.0

    def sleep_ms(self, ms: float) -> None:
        time.sleep(ms / 1000.0)


class FakeClock:
    def __init__(self, start: datetime, step_ms: float = 0.0) -> None:
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware UTC")
        self._start = start
        self._elapsed = 0.0
        self._step = step_ms
        """Added on every monotonic read, so spans have a known duration."""

    def now(self) -> datetime:
        return self._start + timedelta(milliseconds=self._elapsed)

    def monotonic_ms(self) -> float:
        self._elapsed += self._step
        return self._elapsed

    def sleep_ms(self, ms: float) -> None:
        self._elapsed += ms

    def advance(self, ms: float) -> None:
        self._elapsed += ms
