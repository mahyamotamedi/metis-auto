"""Stratified sampler: allocation, selection, weights (Stage E4; framework §5,
§0.2).

**Allocation** decides how many units are drawn per cell, and may deliberately
oversample minority languages (per-cell floor, per-language quota, proportional
remainder). **Weights** rescale the drawn sample to the population: each
selected unit carries its selection probability ``k/N`` of its cell and the
inverse weight ``N/k``. The two are stored separately. Per-stratum comparisons
use the sample as drawn; population totals use the weights.

Rules: floors and quotas come first and are never silently trimmed or topped
up: if they exceed ``total`` the plan reports ``over_budget_by``; a quota that
the population cannot meet is reported ``unmet`` with the achieved n. Rare
cells (population below ``pool_below_n``) are pooled with the siblings that
share the first dimension's value. Selection within a cell is deterministic:
units are ordered by a hash of the seed, the cell and the case ID. Units are
replay cases, so turns of one session may both be drawn (stated; weights treat
units as independent).
Nothing is set by default (config.py); an unset ``total``, ``dimensions`` or
``seed`` gives ``not_evaluated`` with the reason. Pure.
Status: provisional (Stage E4).
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction

from metis_auto.evaluation.comparison.types import sufficient

from .config import AllocationConfig

POOLED = "*pooled*"


@dataclass(frozen=True)
class SamplingUnit:
    """One drawable replay case: opaque IDs, strata, numeric features."""

    case_id: str
    session_ref: str
    strata: Mapping[str, str]
    numeric: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CellAllocation:
    label: str
    cell: tuple[tuple[str, str], ...]
    population: int
    allocated: int
    achieved: int
    reasons: tuple[str, ...]
    pooled: bool


@dataclass(frozen=True)
class QuotaOutcome:
    value: str
    requested: int
    achieved: int
    status: str
    """``met`` or ``unmet``."""
    reason: str | None


@dataclass(frozen=True)
class Selection:
    case_id: str
    cell: str
    selection_probability: float
    weight: float


@dataclass(frozen=True)
class SamplingPlan:
    state: str
    """``planned`` or ``not_evaluated``."""
    reason: str | None
    population: int
    requested_total: int | None
    achieved_total: int
    over_budget_by: int
    cells: tuple[CellAllocation, ...]
    quotas: tuple[QuotaOutcome, ...]
    selected: tuple[Selection, ...]

    def selected_ids(self) -> tuple[str, ...]:
        return tuple(s.case_id for s in self.selected)


def _not_evaluated(reason: str, population: int) -> SamplingPlan:
    return SamplingPlan("not_evaluated", reason, population, None, 0, 0, (), (), ())


def _label(cell: tuple[tuple[str, str], ...]) -> str:
    return "|".join(f"{d}={v}" for d, v in cell)


def _apportion(
    amount: int, weights: Mapping[str, int], caps: Mapping[str, int]
) -> dict[str, int]:
    """Largest-remainder split of ``amount`` by ``weights``, each key capped."""
    extra = {k: 0 for k in weights}
    remaining = amount
    while remaining > 0:
        open_ = {k: w for k, w in weights.items() if extra[k] < caps[k] and w > 0}
        if not open_:
            break
        total_w = sum(open_.values())
        # exact fractions: equal remainders must tie, not differ by float noise
        shares = {k: Fraction(remaining * w, total_w) for k, w in open_.items()}
        given = 0
        for k in open_:
            part = min(shares[k].numerator // shares[k].denominator, caps[k] - extra[k])
            extra[k] += part
            given += part
        remaining -= given
        if remaining <= 0:
            break
        order = sorted(
            open_,
            key=lambda k: (
                -(shares[k] - (shares[k].numerator // shares[k].denominator)),
                k,
            ),
        )
        progress = given > 0
        for k in order:
            if remaining <= 0:
                break
            if extra[k] < caps[k]:
                extra[k] += 1
                remaining -= 1
                progress = True
        if not progress:
            break
    return extra


def plan_sample(
    units: Sequence[SamplingUnit], config: AllocationConfig
) -> SamplingPlan:
    n = len(units)
    if not config.dimensions:
        return _not_evaluated("dimensions_unset", n)
    if config.total is None:
        return _not_evaluated("total_unset", n)
    if not config.seed:
        return _not_evaluated("seed_unset", n)
    if config.quotas and "language" not in config.dimensions:
        return _not_evaluated("quota_needs_language_dimension", n)
    dims = config.dimensions

    def raw_cell(unit: SamplingUnit) -> tuple[tuple[str, str], ...]:
        return tuple((d, unit.strata.get(d, "unknown")) for d in dims)

    counts = Counter(raw_cell(u) for u in units)
    pooled_cell: dict[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]] = {}
    pooled_flag: set[tuple[tuple[str, str], ...]] = set()
    for cell, count in counts.items():
        if config.pool_below_n is not None and count < config.pool_below_n:
            first = cell[0]
            target = (
                (first, *((d, POOLED) for d in dims[1:])) if len(dims) > 1 else cell
            )
            pooled_cell[cell] = target
            pooled_flag.add(target)
        else:
            pooled_cell[cell] = cell
    members: dict[tuple[tuple[str, str], ...], list[SamplingUnit]] = defaultdict(list)
    for unit in units:
        members[pooled_cell[raw_cell(unit)]].append(unit)
    cells = sorted(members, key=_label)
    population = {_label(c): len(members[c]) for c in cells}
    labels = {_label(c): c for c in cells}
    allocated = {
        lab: min(config.floor_per_cell or 0, population[lab]) for lab in labels
    }
    reasons: dict[str, list[str]] = {lab: [] for lab in labels}
    for lab, k in allocated.items():
        if k:
            reasons[lab].append("floor")

    quota_requested: dict[str, int] = dict(config.quotas or {})
    for value, requested in sorted(quota_requested.items()):
        in_value = [lab for lab, c in labels.items() if ("language", value) in c]
        target = min(requested, sum(population[lab] for lab in in_value))
        deficit = target - sum(allocated[lab] for lab in in_value)
        if deficit > 0:
            extra = _apportion(
                deficit,
                {lab: population[lab] for lab in in_value},
                {lab: population[lab] - allocated[lab] for lab in in_value},
            )
            for lab, k in extra.items():
                if k:
                    allocated[lab] += k
                    reasons[lab].append("quota")

    required = sum(allocated.values())
    over_budget = max(0, required - config.total)
    remaining = max(0, config.total - required)
    extra = _apportion(
        remaining, population, {lab: population[lab] - allocated[lab] for lab in labels}
    )
    for lab, k in extra.items():
        if k:
            allocated[lab] += k
            reasons[lab].append("proportional")

    selected: list[Selection] = []
    cell_results: list[CellAllocation] = []
    for cell in cells:
        lab = _label(cell)
        ordered = sorted(
            members[cell],
            key=lambda u: hashlib.sha256(
                f"{config.seed}\x1f{lab}\x1f{u.case_id}".encode()
            ).hexdigest(),
        )
        take = ordered[: allocated[lab]]
        k, big_n = len(take), population[lab]
        for unit in take:
            selected.append(Selection(unit.case_id, lab, k / big_n, big_n / k))
        cell_results.append(
            CellAllocation(
                label=lab,
                cell=cell,
                population=big_n,
                allocated=allocated[lab],
                achieved=k,
                reasons=tuple(reasons[lab]),
                pooled=cell in pooled_flag,
            )
        )
    by_language = Counter(
        dict(c.cell).get("language") for c in cell_results for _ in range(c.achieved)
    )
    quotas = tuple(
        QuotaOutcome(
            value,
            requested,
            by_language.get(value, 0),
            "met" if by_language.get(value, 0) >= requested else "unmet",
            None
            if by_language.get(value, 0) >= requested
            else "population_smaller_than_quota",
        )
        for value, requested in sorted(quota_requested.items())
    )
    return SamplingPlan(
        state="planned",
        reason=None,
        population=n,
        requested_total=config.total,
        achieved_total=len(selected),
        over_budget_by=over_budget,
        cells=tuple(cell_results),
        quotas=quotas,
        selected=tuple(selected),
    )


@dataclass(frozen=True)
class SliceCount:
    value: str
    population: int
    selected: int
    population_share: float
    sample_share: float
    weighted_share: float
    sufficiency: str
    """``sufficient`` or ``insufficient`` (reason in ``sufficiency_reason``)."""
    sufficiency_reason: str | None


def slice_counts(
    plan: SamplingPlan,
    units: Sequence[SamplingUnit],
    dimension: str,
    *,
    min_n: int | None,
) -> tuple[SliceCount, ...]:
    """Per value of ``dimension``: population, drawn n, and the three shares:
    the population's, the sample's (allocation) and the weighted sample's
    (which recovers the population's). Printed before any run."""
    pop = Counter(u.strata.get(dimension, "unknown") for u in units)
    by_case = {u.case_id: u for u in units}
    drawn: Counter[str] = Counter()
    weighted: Counter[str] = Counter()
    for s in plan.selected:
        value = by_case[s.case_id].strata.get(dimension, "unknown")
        drawn[value] += 1
        weighted[value] += s.weight
    total_pop, total_drawn = sum(pop.values()), sum(drawn.values())
    total_weight = sum(weighted.values())
    rows = []
    for value in sorted(pop, key=lambda v: (v != "fa", v)):
        ok, reason = sufficient(drawn[value], min_n)
        rows.append(
            SliceCount(
                value,
                pop[value],
                drawn[value],
                pop[value] / total_pop if total_pop else 0.0,
                drawn[value] / total_drawn if total_drawn else 0.0,
                weighted[value] / total_weight if total_weight else 0.0,
                "sufficient" if ok else "insufficient",
                reason,
            )
        )
    return tuple(rows)
