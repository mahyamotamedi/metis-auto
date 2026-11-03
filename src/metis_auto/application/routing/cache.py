"""Router-result cache (ADR-XXXX (system-one-decision-router) points 3 and 8).

In process, per run. Key: a keyed fingerprint (ADR-0015) of the state with its
text folded (``[router.cache] normalisation``), the question-set version and
language, the backend name and the **model revision** last seen from that
backend. A value is a content-free ``DecisionResult``; the state itself is
never stored.

Model version rule (owner, 2026-11-02): a backend that reports a revision
different from the last one seen (Jev's ``jev-latest`` alias moving to a new
release) has its cached results dropped, and the change is recorded in
``revision_changes`` and logged, so earlier labels and comparisons made under
the old revision can be marked stale (R6).

Bounded: ``max_entries`` (least recently used dropped first) and ``ttl_s``.
Called by: application.routing.cascade. Config: ``[router.cache]``.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass

from metis_auto.contracts import DecisionResult, Fingerprint
from metis_auto.ports import Clock

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RevisionChange:
    backend: str
    previous: str
    current: str


@dataclass(frozen=True)
class _Entry:
    result: DecisionResult
    stored_ms: float


class RouterResultCache:
    def __init__(self, clock: Clock, *, max_entries: int, ttl_s: float) -> None:
        if max_entries < 1 or ttl_s <= 0:
            raise ValueError("invalid router-cache settings")
        self._clock = clock
        self._max = max_entries
        self._ttl_ms = ttl_s * 1000.0
        self._entries: OrderedDict[tuple[str, str, str], _Entry] = OrderedDict()
        self._revisions: dict[str, str] = {}
        self.revision_changes: list[RevisionChange] = []
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    def revision(self, backend: str) -> str | None:
        """The last revision seen from ``backend``; None before its first answer."""
        return self._revisions.get(backend)

    def get(self, backend: str, key: Fingerprint) -> DecisionResult | None:
        revision = self._revisions.get(backend)
        if revision is None:
            self.misses += 1
            return None
        slot = (backend, revision, key)
        entry = self._entries.get(slot)
        if entry is None:
            self.misses += 1
            return None
        if self._clock.monotonic_ms() - entry.stored_ms > self._ttl_ms:
            del self._entries[slot]
            self.misses += 1
            return None
        self._entries.move_to_end(slot)
        self.hits += 1
        return entry.result

    def observe(self, backend: str, revision: str) -> RevisionChange | None:
        """Record the revision a backend just reported. A change drops that
        backend's entries and is recorded (never silently ignored)."""
        previous = self._revisions.get(backend)
        self._revisions[backend] = revision
        if previous is None or previous == revision:
            return None
        for slot in [s for s in self._entries if s[0] == backend]:
            del self._entries[slot]
        change = RevisionChange(backend, previous, revision)
        self.revision_changes.append(change)
        log.warning(
            "decision backend %s changed revision %s -> %s: its cached results "
            "were dropped; earlier labels and comparisons are stale",
            backend,
            previous,
            revision,
        )
        return change

    def put(self, backend: str, key: Fingerprint, result: DecisionResult) -> None:
        """Store a valid result under the revision it reported (``observe``
        first, so a new revision never mixes with old entries)."""
        self.observe(backend, result.model_revision)
        slot = (backend, result.model_revision, key)
        self._entries[slot] = _Entry(result, self._clock.monotonic_ms())
        self._entries.move_to_end(slot)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)
