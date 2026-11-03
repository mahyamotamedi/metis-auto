"""Pilot selection for P-1 (final plan: "a 20-request pilot first, discarded
from results").

Deterministic: records are ordered by a keyed hash of ``seed`` and the record
ID, then taken round-robin over language groups (so the pilot meets Persian,
English and mixed text, framework's Persian-first rule), skipping a record that
would put any tenant above ``cap`` of the pilot. Pure; IDs in, IDs out.
Traces: FR-EVAL-04, Review Focus 5, ADR-0053.
Status: provisional.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    record_id: str
    tenant: str | None
    language_group: str


def _key(seed: str, record_id: str) -> str:
    return hashlib.blake2b(
        f"{seed}\x1f{record_id}".encode(), digest_size=16
    ).hexdigest()


def select_pilot(
    candidates: Sequence[Candidate], *, size: int, seed: str, cap: float
) -> tuple[str, ...]:
    """Up to ``size`` record IDs. Fewer only if the tenant cap leaves no more."""
    if size <= 0:
        raise ValueError("size must be positive")
    if not seed:
        raise ValueError("seed is required")
    limit = max(1, math.floor(cap * size))
    groups: dict[str, list[Candidate]] = defaultdict(list)
    for c in sorted(candidates, key=lambda c: _key(seed, c.record_id)):
        groups[c.language_group].append(c)
    order = sorted(groups, key=lambda g: (-len(groups[g]), g))
    taken: list[str] = []
    per_tenant: Counter[str] = Counter()
    while len(taken) < size and any(groups.values()):
        for g in order:
            if len(taken) >= size:
                break
            while groups[g]:
                c = groups[g].pop(0)
                tenant = c.tenant or f"__unknown__{c.record_id}"
                if per_tenant[tenant] < limit:
                    per_tenant[tenant] += 1
                    taken.append(c.record_id)
                    break
    return tuple(taken)
