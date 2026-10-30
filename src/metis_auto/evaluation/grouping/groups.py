"""Duplicate-prompt groups and leakage-safe splits (CMP-21/23; evaluation
framework §0.3, §8 pitfalls 8 and 20; ADR-0015).

Responsibility: group items whose text is the same after a named treatment
(``domain.caching.normalise``), and split items into named parts (for
example fit and test) so that no duplicate group and no session is spread
over two parts. Group IDs derive from content, so they are **keyed
fingerprints** (purpose ``dup_group``, ADR-0015 point 1); an item whose text
is empty after treatment is never grouped (unknown never matches, ADR-0011).
Outputs are content-free: IDs, counts, and part names. Pure: no I/O.
Split fractions have no default and are supplied by the caller (config); a
split assigns whole connected components (items linked by a shared session or
a shared duplicate group), so realised item shares can differ from the
fractions, and the result reports them.
Called by: evaluation code and experiments (not wired into the runner yet).
Calls: application.measurement (Fingerprinter), domain.caching.
Status: provisional (Stage E0).
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from metis_auto.application.measurement import Fingerprinter
from metis_auto.domain.caching import normalise

_EPSILON = 1e-9


@dataclass(frozen=True)
class TextItem:
    """One item to group. ``item_id`` and ``session_ref`` are opaque IDs."""

    item_id: str
    session_ref: str
    text: str


def _check_ids(items: Sequence[TextItem]) -> None:
    ids = [i.item_id for i in items]
    if len(set(ids)) != len(ids):
        raise ValueError("item_id values must be unique")


def duplicate_groups(
    items: Sequence[TextItem], treatment: str, fingerprinter: Fingerprinter
) -> dict[str, str]:
    """item_id → group fingerprint. Items with the same treated text share a
    group; an item with empty treated text gets a group of its own."""
    _check_ids(items)
    groups: dict[str, str] = {}
    for item in items:
        treated = normalise(item.text, treatment)
        if treated:
            groups[item.item_id] = fingerprinter.fingerprint("dup_group", treated)
        else:
            groups[item.item_id] = fingerprinter.fingerprint(
                "dup_group_unique", item.item_id
            )
    return groups


@dataclass(frozen=True)
class DuplicateSummary:
    """Content-free counts of a grouping."""

    items: int
    groups: int
    repeated_groups: int
    items_in_repeated_groups: int
    largest_group: int
    groups_crossing_sessions: int


def duplicate_summary(
    items: Sequence[TextItem], groups: Mapping[str, str]
) -> DuplicateSummary:
    members: dict[str, list[TextItem]] = defaultdict(list)
    for item in items:
        members[groups[item.item_id]].append(item)
    repeated = [g for g in members.values() if len(g) > 1]
    return DuplicateSummary(
        items=len(items),
        groups=len(members),
        repeated_groups=len(repeated),
        items_in_repeated_groups=sum(len(g) for g in repeated),
        largest_group=max((len(g) for g in members.values()), default=0),
        groups_crossing_sessions=sum(
            1 for g in repeated if len({i.session_ref for i in g}) > 1
        ),
    )


@dataclass(frozen=True)
class SplitResult:
    """A leakage-safe split. ``assignment`` maps item_id → part name."""

    assignment: dict[str, str]
    items_per_part: dict[str, int]
    components_per_part: dict[str, int]
    components: int
    requested_fractions: dict[str, float]
    treatment: str
    seed: str


def _components(
    items: Sequence[TextItem], groups: Mapping[str, str]
) -> list[list[int]]:
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    first_by_key: dict[tuple[str, str], int] = {}
    for index, item in enumerate(items):
        for key in (("s", item.session_ref), ("g", groups[item.item_id])):
            if key in first_by_key:
                union(index, first_by_key[key])
            else:
                first_by_key[key] = index
    by_root: dict[int, list[int]] = defaultdict(list)
    for index in range(len(items)):
        by_root[find(index)].append(index)
    return list(by_root.values())


def leakage_safe_split(
    items: Sequence[TextItem],
    treatment: str,
    fingerprinter: Fingerprinter,
    fractions: Mapping[str, float],
    seed: str,
) -> SplitResult:
    """Assign each connected component to a part by a deterministic hash of the
    seed and the component's smallest group fingerprint. ``fractions`` (part →
    share of components, summing to 1) has no default."""
    if not fractions or any(f < 0 for f in fractions.values()):
        raise ValueError("fractions must be non-empty and non-negative")
    if abs(sum(fractions.values()) - 1.0) > _EPSILON:
        raise ValueError("fractions must sum to 1")
    if not seed:
        raise ValueError("a seed is required")
    groups = duplicate_groups(items, treatment, fingerprinter)
    parts = list(fractions)
    assignment: dict[str, str] = {}
    items_per_part: Counter[str] = Counter()
    components_per_part: Counter[str] = Counter()
    components = _components(items, groups)
    for members in components:
        key = min(groups[items[i].item_id] for i in members)
        digest = hashlib.sha256(f"{seed}\x1f{key}".encode()).hexdigest()
        point = int(digest[:16], 16) / 2**64
        cumulative = 0.0
        chosen = parts[-1]
        for part in parts:
            cumulative += fractions[part]
            if point < cumulative:
                chosen = part
                break
        components_per_part[chosen] += 1
        for i in members:
            assignment[items[i].item_id] = chosen
            items_per_part[chosen] += 1
    return SplitResult(
        assignment=assignment,
        items_per_part={p: items_per_part[p] for p in parts},
        components_per_part={p: components_per_part[p] for p in parts},
        components=len(components),
        requested_fractions=dict(fractions),
        treatment=treatment,
        seed=seed,
    )
