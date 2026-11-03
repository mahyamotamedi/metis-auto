"""Per-backend circuit breaker of the decision router (FR-FAIL-05,
ADR-0047).

Closed: calls go through; a failure is remembered for ``window_s``. When
``failure_threshold`` failures fall inside the window the circuit **opens**:
the backend is skipped (``circuit_open``) for ``cooldown_s``. Then it is
**half open**: one trial call; success closes it, failure opens it again.

A failure is a call that returned a ``DecisionError`` (timeout, transport or
provider error, invalid response). Not calling a backend (unavailable, spend
guard, approval refused, no time left) is not a failure of the backend.
Time comes from the ``Clock`` port, so tests drive it with a fake clock.
Called by: application.routing.cascade. Config: ``[router.circuit]``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from metis_auto.contracts.events import CircuitState
from metis_auto.ports import Clock


@dataclass
class _Circuit:
    failures: deque[float] = field(default_factory=deque)
    opened_at: float | None = None
    trial_running: bool = False


class CircuitBreaker:
    def __init__(
        self,
        clock: Clock,
        *,
        failure_threshold: int,
        window_s: float,
        cooldown_s: float,
    ) -> None:
        if failure_threshold < 1 or window_s <= 0 or cooldown_s <= 0:
            raise ValueError("invalid circuit-breaker settings")
        self._clock = clock
        self._threshold = failure_threshold
        self._window_ms = window_s * 1000.0
        self._cooldown_ms = cooldown_s * 1000.0
        self._circuits: dict[str, _Circuit] = {}

    def _get(self, backend: str) -> _Circuit:
        return self._circuits.setdefault(backend, _Circuit())

    def state(self, backend: str) -> CircuitState:
        c = self._get(backend)
        if c.opened_at is None:
            return CircuitState.CLOSED
        if self._clock.monotonic_ms() - c.opened_at >= self._cooldown_ms:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def allows(self, backend: str) -> bool:
        """True if a call may go to ``backend`` now. In half-open state only
        one trial is let through until its result is recorded."""
        state = self.state(backend)
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.OPEN:
            return False
        c = self._get(backend)
        if c.trial_running:
            return False
        c.trial_running = True
        return True

    def record_success(self, backend: str) -> None:
        c = self._get(backend)
        c.failures.clear()
        c.opened_at = None
        c.trial_running = False

    def record_failure(self, backend: str) -> None:
        c = self._get(backend)
        now = self._clock.monotonic_ms()
        if c.opened_at is not None:  # a half-open trial failed
            c.opened_at = now
            c.trial_running = False
            return
        c.failures.append(now)
        while c.failures and now - c.failures[0] > self._window_ms:
            c.failures.popleft()
        if len(c.failures) >= self._threshold:
            c.opened_at = now
            c.failures.clear()
