"""Candidate indexes: the swappable part of a cache-candidate experiment
(CMP-23 support; docs/experiments/framework.md §4, caching_plan.md).

Responsibility: hold earlier cases' key material and say which earlier case,
if any, a new case matches. One index per key variant. A new cache strategy
(semantic tier, curated cache, Persian folding, …) implements
``CandidateIndex`` and is named by one ``[experiment.strategy]`` entry; the
harness, events, metrics, and comparison format stay the same.

Built-in (reference) indexes, selected by the variant's unknown treatment:
- ``ExactKeyIndex``: the serving rule (P-6). The key is the sealed keyed
  fingerprint of the variant's components; a component that is unknown makes
  the case ineligible before it reaches the index.
- ``WildcardIndex``: measurement only. Candidates share the message
  fingerprint; every other component matches when equal **or** when either
  side is unknown. It bounds the opportunity hidden by unknown components
  (Q-24); it is never a serving rule.
Status: interface provisional (Stage 8); indexes reference implementations.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from metis_auto.contracts import ComponentState, Fingerprint, KeyComponent, Request


@dataclass(frozen=True)
class CandidateItem:
    """One case's key material for one variant. ``request`` is content and
    stays in memory (a semantic index would embed its message)."""

    case_id: str
    session_ref: str
    components: tuple[KeyComponent, ...]
    model: tuple[ComponentState, str | None]
    key: Fingerprint | None
    """Sealed key for strict variants; None for wildcard."""
    request: Request = field(repr=False, compare=False)


@runtime_checkable
class CandidateIndex(Protocol):
    def lookup(self, item: CandidateItem, *, session_ref: str | None) -> str | None:
        """Case ID of the earliest stored match, or None. ``session_ref``
        restricts matches to that session (session scope); None = any."""
        ...

    def add(self, item: CandidateItem) -> None:
        """Store a case that has a logged answer to serve."""
        ...


IndexFactory = Callable[[Any, Mapping[str, Any]], CandidateIndex]
"""``(variant spec, params) -> CandidateIndex``, one per variant per run."""


def _first(entries: list[CandidateItem], session_ref: str | None) -> str | None:
    for e in entries:
        if session_ref is None or e.session_ref == session_ref:
            return e.case_id
    return None


class ExactKeyIndex:
    def __init__(self) -> None:
        self._by_key: dict[str, list[CandidateItem]] = defaultdict(list)

    def lookup(self, item: CandidateItem, *, session_ref: str | None) -> str | None:
        assert item.key is not None, "strict variants carry a sealed key"
        return _first(self._by_key.get(item.key, []), session_ref)

    def add(self, item: CandidateItem) -> None:
        assert item.key is not None
        self._by_key[item.key].append(item)


def _compatible(a: KeyComponent, b: KeyComponent) -> bool:
    if ComponentState.UNKNOWN in (a.state, b.state):
        return True
    return a.state == b.state and a.fingerprint == b.fingerprint


class WildcardIndex:
    def __init__(self) -> None:
        self._by_message: dict[str | None, list[CandidateItem]] = defaultdict(list)

    @staticmethod
    def _message(item: CandidateItem) -> str | None:
        return next(
            (c.fingerprint for c in item.components if c.component == "message"), None
        )

    def lookup(self, item: CandidateItem, *, session_ref: str | None) -> str | None:
        for e in self._by_message.get(self._message(item), []):
            if session_ref is not None and e.session_ref != session_ref:
                continue
            if not all(
                _compatible(a, b)
                for a, b in zip(item.components, e.components, strict=True)
            ):
                continue
            states = (item.model[0], e.model[0])
            if ComponentState.UNKNOWN not in states and item.model != e.model:
                continue
            return e.case_id
        return None

    def add(self, item: CandidateItem) -> None:
        self._by_message[self._message(item)].append(item)


def exact_index(variant: Any, params: Mapping[str, Any]) -> CandidateIndex:
    """The built-in ``exact`` strategy: strict or wildcard by the variant."""
    return WildcardIndex() if variant.unknown_mode == "wildcard" else ExactKeyIndex()


BUILTIN_INDEXES: dict[str, IndexFactory] = {"exact": exact_index}
