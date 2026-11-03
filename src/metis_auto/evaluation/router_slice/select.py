"""Seeded, deficit-weighted selection under soft quotas and hard caps (pure).

Used twice by the routing dev slice: once to draw the candidate pool from the
structural index (pass 1), once to pick the slice from the pool's full
features (pass 2). Candidates with the same strata form a group; each step
takes the next candidate of the group that most reduces the remaining
deficits (sum over its strata of ``missing / target``), ties broken by a
seeded hash; once every target is met, groups are drawn in seeded order.
Caps (per session, bot, duplicate family) and ceilings (a maximum count per
stratum value) are hard: a candidate that would break one is skipped, and a
group whose stratum value reached its ceiling is closed whole. Deterministic
for a given seed and input, independent of input order.

Traces: FR-EVAL-04/06 (stratified, leakage-safe evaluation sets),
ADR-0047.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field


def tiebreak(seed: int, purpose: str, key: str) -> bytes:
    """Stable order of ``key`` for ``purpose`` under ``seed``; platform-free."""
    return hashlib.blake2b(f"{seed}|{purpose}|{key}".encode(), digest_size=16).digest()


@dataclass(frozen=True)
class Candidate:
    key: str
    session_id: str
    bot_id: str
    strata: Mapping[str, str]
    """Dimension → value (single-valued strata)."""
    flags: frozenset[str] = frozenset()
    families: tuple[str, ...] = ()
    """Duplicate-family keys; at most ``per_family`` per key are chosen."""


@dataclass(frozen=True)
class Caps:
    per_session: int = 1
    per_bot: int = 10
    per_family: int = 1
    per_bot_exempt: frozenset[str] = frozenset()
    """Bots with no per-bot cap (cohorts with very few bots)."""


@dataclass(frozen=True)
class Targets:
    shares: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    """Dimension → value → target count."""
    minimums: Mapping[str, int] = field(default_factory=dict)
    """Flag → minimum count."""
    ceilings: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    """Dimension → value → maximum count (hard)."""


@dataclass
class Selection:
    chosen: list[Candidate]
    achieved: dict[str, Counter[str]]
    flag_counts: Counter[str]
    available: dict[str, Counter[str]]
    flag_available: Counter[str]
    skipped_by_cap: Counter[str]

    def shortfalls(self, targets: Targets) -> list[tuple[str, str, int, int]]:
        """(dimension or ``flag``, value, target, achieved) where a target was
        not reached."""
        out = []
        for dim, values in targets.shares.items():
            for value, target in values.items():
                got = self.achieved.get(dim, Counter())[value]
                if got < target:
                    out.append((dim, value, target, got))
        for flag, target in targets.minimums.items():
            if self.flag_counts[flag] < target:
                out.append(("flag", flag, target, self.flag_counts[flag]))
        return out


def select(
    candidates: Iterable[Candidate],
    size: int,
    targets: Targets,
    caps: Caps,
    *,
    seed: int,
    purpose: str,
) -> Selection:
    dims = tuple(sorted(set(targets.shares) | set(targets.ceilings)))
    flags = tuple(sorted(targets.minimums))
    groups: dict[tuple, list[tuple[bytes, Candidate]]] = {}
    available: dict[str, Counter[str]] = {d: Counter() for d in dims}
    flag_available: Counter[str] = Counter()
    for c in candidates:
        signature = (
            tuple(c.strata.get(d, "") for d in dims),
            tuple(f in c.flags for f in flags),
        )
        groups.setdefault(signature, []).append((tiebreak(seed, purpose, c.key), c))
        for d in dims:
            available[d][c.strata.get(d, "")] += 1
        flag_available.update(f for f in flags if f in c.flags)
    queues = {sig: sorted(items, key=lambda x: x[0]) for sig, items in groups.items()}
    heads = dict.fromkeys(queues, 0)

    achieved: dict[str, Counter[str]] = {d: Counter() for d in dims}
    flag_counts: Counter[str] = Counter()
    per_session: Counter[str] = Counter()
    per_bot: Counter[str] = Counter()
    per_family: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    chosen: list[Candidate] = []

    def score(signature: tuple) -> float:
        values, has = signature
        total = 0.0
        for d, v in zip(dims, values, strict=True):
            target = targets.shares.get(d, {}).get(v)
            if target:
                total += max(0, target - achieved[d][v]) / target
        for f, present in zip(flags, has, strict=True):
            target = targets.minimums[f]
            if present and target:
                total += max(0, target - flag_counts[f]) / target
        return total

    def at_ceiling(signature: tuple) -> str | None:
        for d, v in zip(dims, signature[0], strict=True):
            cap = targets.ceilings.get(d, {}).get(v)
            if cap is not None and achieved[d][v] >= cap:
                return f"ceiling:{d}={v}"
        return None

    def cap_reason(c: Candidate) -> str | None:
        if per_session[c.session_id] >= caps.per_session:
            return "per_session"
        if c.bot_id not in caps.per_bot_exempt and per_bot[c.bot_id] >= caps.per_bot:
            return "per_bot"
        if any(per_family[f] >= caps.per_family for f in c.families):
            return "per_family"
        return None

    while len(chosen) < size:
        best_sig, best_key = None, None
        for sig, queue in queues.items():
            head = heads[sig]
            if head >= len(queue):
                continue
            key = (-score(sig), queue[head][0])
            if best_key is None or key < best_key:
                best_sig, best_key = sig, key
        if best_sig is None:
            break  # every group is exhausted
        queue = queues[best_sig]
        ceiling = at_ceiling(best_sig)
        if ceiling is not None:
            # Counts only grow, so the whole group stays closed.
            skipped[ceiling] += len(queue) - heads[best_sig]
            heads[best_sig] = len(queue)
            continue
        # The group's score does not depend on which of its members is next, so
        # skipping a capped member keeps this group the best one.
        while heads[best_sig] < len(queue):
            candidate = queue[heads[best_sig]][1]
            heads[best_sig] += 1
            reason = cap_reason(candidate)
            if reason is not None:
                skipped[reason] += 1
                continue
            chosen.append(candidate)
            per_session[candidate.session_id] += 1
            per_bot[candidate.bot_id] += 1
            per_family.update(candidate.families)
            for d in dims:
                achieved[d][candidate.strata.get(d, "")] += 1
            flag_counts.update(f for f in flags if f in candidate.flags)
            break
    return Selection(chosen, achieved, flag_counts, available, flag_available, skipped)


def allocate(
    total: int, weights: Mapping[str, int], capacity: Mapping[str, int]
) -> dict[str, int]:
    """``total`` split in proportion to ``weights``, no key above its
    ``capacity``; what a full key cannot take goes to the others, again in
    proportion. Largest remainder rounding, ties by key: deterministic."""
    out = dict.fromkeys(weights, 0)
    left = total
    open_keys = {k for k, w in weights.items() if w > 0 and capacity.get(k, 0) > 0}
    while left > 0 and open_keys:
        weight = sum(weights[k] for k in open_keys)
        exact = {k: left * weights[k] / weight for k in open_keys}
        share = {k: int(exact[k]) for k in open_keys}
        spare = left - sum(share.values())
        for k in sorted(open_keys, key=lambda k: (share[k] - exact[k], k))[:spare]:
            share[k] += 1
        for k in sorted(open_keys):
            take = min(share[k], capacity[k] - out[k])
            out[k] += take
            left -= take
        open_keys = {k for k in open_keys if out[k] < capacity[k]}
    return out


def split_by_session(
    sessions: Sequence[str], tune_share: float, *, seed: int
) -> dict[str, str]:
    """Session → ``tune`` or ``check``: a seeded order of the distinct sessions,
    the first ``round(n × tune_share)`` are ``tune``. A session never spans both."""
    distinct = sorted(set(sessions), key=lambda s: tiebreak(seed, "split", s))
    n_tune = round(len(distinct) * tune_share)
    return {s: ("tune" if i < n_tune else "check") for i, s in enumerate(distinct)}


def scaled(targets: Targets, factor: float, *, flag_factor: float = 1.0) -> Targets:
    """Targets for a larger draw (the pool): shares scale by ``factor``,
    minimums by ``factor × flag_factor`` (oversampling rare flags). Ceilings
    are dropped: they bind the final draw only, so the pool stays wide."""
    return Targets(
        shares={
            d: {v: max(1, round(n * factor)) for v, n in values.items()}
            for d, values in targets.shares.items()
        },
        minimums={
            f: max(1, round(n * factor * flag_factor))
            for f, n in targets.minimums.items()
        },
    )
