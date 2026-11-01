"""Controlled selection of the 300 records and their reserves (pure, deterministic).

Not a Cartesian product. The primary-intent × cohort table is exact (``joint_quotas``);
inside each cell a greedy pass favours whichever strata are furthest below their
marginal quotas, then a swap pass improves the fit. Every ordering is explicit and
ties break on ``blake2b(seed|request_id)``, so results do not depend on the platform,
locale, hash randomisation or input row order (ADR-0028).
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from metis_auto.evaluation.golden.allocation import joint_quotas
from metis_auto.evaluation.golden.config import SOFT_MARGINS, GoldenConfig


@dataclass(frozen=True)
class Candidate:
    request_id: str
    session_id: str
    bot_id: str
    intent: str
    cohort: str
    strata: tuple[tuple[str, str], ...]
    """(margin, key) for each soft margin, in ``SOFT_MARGINS`` order."""
    tags: frozenset[str]
    family: str
    near_family: str

    @property
    def cell(self) -> tuple[str, str]:
        return (self.intent, self.cohort)

    @property
    def signature(self) -> tuple:
        return (self.strata, tuple(sorted(self.tags)))


@dataclass
class Selection:
    primary: list[tuple[Candidate, str]] = field(default_factory=list)
    """(candidate, rationale code), in selection-rank order."""
    reserves: list[tuple[Candidate, str]] = field(default_factory=list)
    """(candidate, cell key), in reserve-rank order."""
    joint: dict[tuple[str, str], int] = field(default_factory=dict)
    moves: list[dict] = field(default_factory=list)
    pool_size: int = 0


def seeded_rank(seed: int, request_id: str) -> str:
    return hashlib.blake2b(f"{seed}|{request_id}".encode(), digest_size=16).hexdigest()


def distinct_pool(cands: Iterable[Candidate], seed: int) -> list[Candidate]:
    """One candidate per exact family and per near family, lowest seeded rank first."""
    ordered = sorted(
        cands, key=lambda c: (seeded_rank(seed, c.request_id), c.request_id)
    )
    fam: set[str] = set()
    near: set[str] = set()
    out = []
    for c in ordered:
        if c.family in fam or c.near_family in near:
            continue
        fam.add(c.family)
        near.add(c.near_family)
        out.append(c)
    return out


class _State:
    def __init__(self, cfg: GoldenConfig, pool: list[Candidate]):
        raw = cfg.raw
        self.quotas = {m: cfg.quotas(m) for m in SOFT_MARGINS}
        self.coverage = {k: v["minimum"] for k, v in raw["coverage"].items()}
        self.w = raw["selection"]["weights"]
        self.new_bot = raw["selection"]["new_bot_bonus"]
        self.bot_penalty = raw["selection"]["bot_load_penalty"]
        self.got: dict[str, Counter] = {m: Counter() for m in SOFT_MARGINS}
        self.cov = Counter()
        self.sessions: set[str] = set()
        self.families: set[str] = set()
        self.near: set[str] = set()
        self.bots = Counter()
        self.cohorts = Counter()
        cohort_bots = defaultdict(set)
        for c in pool:
            cohort_bots[c.cohort].add(c.bot_id)
        waive = raw["caps"]["waive_per_bot_if_cohort_bots_at_most"]
        self.waived = {k for k, v in cohort_bots.items() if len(v) <= waive}
        self.per_bot = raw["caps"]["per_bot"]
        self.cohort_cap = raw["caps"]["single_account_cohort_max"]
        self.remaining = raw["cohorts"]["remaining"]

    def allowed(self, c: Candidate) -> bool:
        if (
            c.session_id in self.sessions
            or c.family in self.families
            or c.near_family in self.near
        ):
            return False
        if c.cohort not in self.waived and self.bots[c.bot_id] >= self.per_bot:
            return False
        return not (
            c.cohort != self.remaining and self.cohorts[c.cohort] >= self.cohort_cap
        )

    def add(self, c: Candidate) -> None:
        self._bump(c, 1)
        self.sessions.add(c.session_id)
        self.families.add(c.family)
        self.near.add(c.near_family)

    def remove(self, c: Candidate) -> None:
        self._bump(c, -1)
        self.sessions.discard(c.session_id)
        self.families.discard(c.family)
        self.near.discard(c.near_family)

    def _bump(self, c: Candidate, d: int) -> None:
        for margin, key in c.strata:
            self.got[margin][key] += d
        for tag in c.tags:
            self.cov[tag] += d
        self.bots[c.bot_id] += d
        self.cohorts[c.cohort] += d

    def gain(self, strata, tags, bot_id: str) -> float:
        """How much one more of this signature helps; larger is better."""
        score = 0.0
        for margin, key in strata:
            quota = self.quotas[margin].get(key, 0)
            have = self.got[margin][key]
            weight = self.w[margin]
            if have < quota:
                score += weight * (quota - have) / quota
            else:
                score -= weight * (have - quota + 1) / max(quota, 5)
        for tag, need in self.coverage.items():
            if tag in tags and self.cov[tag] < need:
                score += self.w["coverage"] * (need - self.cov[tag]) / need
        if self.bots[bot_id] == 0:
            score += self.new_bot
        return score - self.bot_penalty * self.bots[bot_id]

    def objective(self) -> float:
        total = 0.0
        for margin in SOFT_MARGINS:
            for key, quota in self.quotas[margin].items():
                gap = abs(self.got[margin][key] - quota)
                total += self.w[margin] * gap / max(quota, 1)
        for tag, need in self.coverage.items():
            gap = max(0, need - self.cov[tag])
            total += self.w["coverage"] * gap / need
        return total


def _index(pool: list[Candidate]) -> dict[tuple, dict[tuple, list[Candidate]]]:
    """Cell → signature → candidates in seeded order (pool order is seeded)."""
    index: dict[tuple, dict[tuple, list[Candidate]]] = {}
    for c in pool:
        index.setdefault(c.cell, {}).setdefault(c.signature, []).append(c)
    return index


def _best(state: _State, by_sig: Mapping[tuple, list[Candidate]]) -> Candidate | None:
    """Best allowed candidate; signatures compared on score, then a stable key."""
    best, best_key = None, None
    for sig in sorted(by_sig, key=repr):
        first = next((c for c in by_sig[sig] if state.allowed(c)), None)
        if first is None:
            continue
        key = (-state.gain(sig[0], frozenset(sig[1]), first.bot_id), repr(sig))
        if best_key is None or key < best_key:
            best, best_key = first, key
    return best


def select(
    candidates: Iterable[Candidate],
    cfg: GoldenConfig,
    exclude: frozenset[str] = frozenset(),
) -> Selection:
    seed, total = cfg.seed, cfg.total
    pool = distinct_pool((c for c in candidates if c.request_id not in exclude), seed)
    population = Counter(c.cell for c in pool)
    joint = joint_quotas(
        dict(population), cfg.quotas("primary_intent"), cfg.quotas("cohort")
    )
    index = _index(pool)
    state = _State(cfg, pool)
    out = Selection(joint=joint, pool_size=len(pool))
    chosen: dict[str, tuple[Candidate, str]] = {}

    # Smallest cells first, because they have the fewest alternatives.
    missing: list[tuple[tuple[str, str], int]] = []
    for cell, quota in sorted(joint.items(), key=lambda kv: (kv[1], kv[0])):
        got = 0
        while got < quota:
            c = _best(state, index.get(cell, {}))
            if c is None:
                break
            state.add(c)
            chosen[c.request_id] = (c, "cell_quota")
            got += 1
        if got < quota:
            missing.append((cell, quota - got))

    # Undersupplied cells: same cohort first, then any cohort; every move is logged.
    for cell, short in missing:
        for scope, code in (("same_cohort", "moved_same_cohort"), ("any", "moved_any")):
            while short > 0:
                c = _fallback(state, index, cell, scope)
                if c is None:
                    break
                state.add(c)
                chosen[c.request_id] = (c, code)
                out.moves.append(
                    {"from_cell": list(cell), "to_cell": list(c.cell), "rule": scope}
                )
                short -= 1
        if short:
            out.moves.append({"from_cell": list(cell), "unfilled": short})

    _improve(state, chosen, index, cfg.raw["selection"]["improvement_passes"])
    ordered = sorted(
        chosen.values(),
        key=lambda t: (seeded_rank(seed, t[0].request_id), t[0].request_id),
    )
    out.primary = ordered[:total]
    out.reserves = _reserves(pool, chosen, joint, cfg, state)
    return out


def _fallback(state, index, cell, scope) -> Candidate | None:
    best, best_key = None, None
    for other in sorted(index):
        if other == cell or (scope == "same_cohort" and other[1] != cell[1]):
            continue
        c = _best(state, index[other])
        if c is None:
            continue
        key = (-state.gain(c.strata, c.tags, c.bot_id), other)
        if best_key is None or key < best_key:
            best, best_key = c, key
    return best


def _improve(state: _State, chosen, index, passes: int) -> None:
    """Same-cell swaps that lower the marginal gap. Cells stay exact."""
    for _ in range(passes):
        improved = False
        for rid in sorted(chosen):
            cur, code = chosen[rid]
            base = state.objective()
            state.remove(cur)
            best, best_obj = None, base - 1e-12
            for sig in sorted(index.get(cur.cell, {}), key=repr):
                cand = next((c for c in index[cur.cell][sig] if state.allowed(c)), None)
                if cand is None or cand.request_id == rid:
                    continue
                state.add(cand)
                obj = state.objective()
                state.remove(cand)
                if obj < best_obj:
                    best, best_obj = cand, obj
            if best is None:
                state.add(cur)
                continue
            state.add(best)
            del chosen[rid]
            chosen[best.request_id] = (best, code)
            improved = True
        if not improved:
            return


def _reserves(pool, chosen, joint, cfg: GoldenConfig, state: _State):
    """Ranked alternates per cell, about half of each quota, up to ``reserve_max``."""
    limit = cfg.raw["dataset"]["reserve_max"]
    by_cell: dict[tuple, list[Candidate]] = defaultdict(list)
    used_sessions = set(state.sessions)
    used_fam, used_near = set(state.families), set(state.near)
    for c in pool:
        if c.request_id not in chosen:
            by_cell[c.cell].append(c)
    want = {cell: math.ceil(q / 2) for cell, q in joint.items()}
    out: list[tuple[Candidate, str]] = []
    # Round robin over cells keeps every cell represented if the limit is reached.
    level = 0
    open_cells = sorted(want)
    pointers = dict.fromkeys(open_cells, 0)
    while open_cells and len(out) < limit:
        for cell in list(open_cells):
            if len(out) >= limit:
                break
            if level >= want[cell]:
                open_cells.remove(cell)
                continue
            items = by_cell[cell]
            i = pointers[cell]
            while i < len(items) and (
                items[i].session_id in used_sessions
                or items[i].family in used_fam
                or items[i].near_family in used_near
            ):
                i += 1
            pointers[cell] = i + 1
            if i >= len(items):
                open_cells.remove(cell)
                continue
            c = items[i]
            used_sessions.add(c.session_id)
            used_fam.add(c.family)
            used_near.add(c.near_family)
            out.append((c, f"{cell[0]}|{cell[1]}"))
        level += 1
    return out


def design_weights(
    eligible_by_cell: Mapping[tuple[str, str], int],
    sampled_by_cell: Mapping[tuple[str, str], int],
) -> tuple[dict[tuple[str, str], float], float]:
    """N_cell / n_cell over eligible requests, and the uncovered population share."""
    total = sum(eligible_by_cell.values())
    weights = {
        cell: eligible_by_cell.get(cell, 0) / n
        for cell, n in sampled_by_cell.items()
        if n > 0
    }
    uncovered = sum(
        n for cell, n in eligible_by_cell.items() if sampled_by_cell.get(cell, 0) == 0
    )
    return weights, (uncovered / total if total else 0.0)


def plan_swaps(
    reviewed_intent: Mapping[str, str],
    record_cell_intent: Mapping[str, str],
    reserves: Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Records whose reviewed intent leaves their cell → first reserve of that cell.

    ``reserves`` are (request_id, cell intent) in rank order. A record with no
    reserve left is simply not in the output; the caller reports the shortfall.
    """
    queue: dict[str, list[str]] = defaultdict(list)
    for rid, intent in reserves:
        queue[intent].append(rid)
    swaps = []
    for record in sorted(reviewed_intent):
        cell_intent = record_cell_intent[record]
        if reviewed_intent[record] != cell_intent and queue[cell_intent]:
            swaps.append((record, queue[cell_intent].pop(0)))
    return swaps
