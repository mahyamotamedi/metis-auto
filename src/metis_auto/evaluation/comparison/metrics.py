"""Cost-quality comparison metrics (Stage E1; framework §1, §0.1, §6).

Pareto front, quality at matched cost, cost at matched quality, PGR / APGR
(RouteLLM-style), CPT, oracle headroom captured, paired effects with a session
cluster bootstrap, non-inferiority against a configurable δ, and the language
slicing rule (Persian-only primary, overall secondary and labelled, minority
slices separate, a slice below the minimum n never ranked or called
significant).

Every function returns an ``Estimate`` that says whether it is measured, why
not, its n and provenance. No threshold has a default: ``min_n``, ``min_gap``,
``delta``, the bootstrap size, level and seed are arguments (config). An unset
value gives ``not_evaluated`` or ``insufficient`` with the reason. Curves are
interpolated linearly: a convention, stated here, not a claim about the shape of
a router's trade-off. RouteLLM's exact APGR grid is *[verify]* against the
paper; this uses ``n_points`` evenly spaced call shares including both ends.
Pure, stdlib only. Status: provisional (Stage E1).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .stats import BootstrapResult, cluster_bootstrap
from .types import (
    PRIMARY_LANGUAGE,
    Estimate,
    OutcomeTable,
    not_measured,
    sufficient,
)

Point = tuple[float, float]


# --- fronts and curves --------------------------------------------------------


def pareto_front(
    points: Sequence[tuple[str, float, float]],
) -> list[tuple[str, float, float]]:
    """Non-dominated (label, cost, quality) points: lower cost and higher
    quality are better. Sorted by cost."""
    front = []
    for label, cost, quality in points:
        dominated = any(
            c <= cost and q >= quality and (c < cost or q > quality)
            for other, c, q in points
            if other != label or (c, q) != (cost, quality)
        )
        if not dominated:
            front.append((label, cost, quality))
    return sorted(front, key=lambda p: (p[1], -p[2], p[0]))


def _front_points(curve: Sequence[Point]) -> list[Point]:
    labelled = [(str(i), c, q) for i, (c, q) in enumerate(curve)]
    return [(c, q) for _, c, q in pareto_front(labelled)]


def _interpolate(points: Sequence[Point], x: float) -> float | None:
    """Linear interpolation of y at x over points sorted by x; None outside."""
    ordered = sorted(points)
    if not ordered or x < ordered[0][0] or x > ordered[-1][0]:
        return None
    best = [y for px, y in ordered if px == x]
    if best:
        return max(best)
    for (x0, y0), (x1, y1) in zip(ordered, ordered[1:], strict=False):
        if x0 < x < x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


def quality_at_cost(
    curve: Sequence[Point], target_cost: float, *, n: int, provenance: str
) -> Estimate:
    """The candidate's quality at a given mean cost, read off the
    non-dominated part of its (cost, quality) sweep."""
    value = _interpolate(_front_points(curve), target_cost)
    if value is None:
        return not_measured("undefined", "target_outside_curve", n, provenance)
    return Estimate("measured", n, provenance, value=value, method="linear_interp")


def cost_at_quality(
    curve: Sequence[Point], target_quality: float, *, n: int, provenance: str
) -> Estimate:
    """The least mean cost at which the candidate reaches ``target_quality``
    (the CPT idea applied to cost), from the non-dominated part of its sweep."""
    front = _front_points(curve)
    if not front or target_quality > max(q for _, q in front):
        return not_measured("undefined", "target_not_reached", n, provenance)
    for index, (cost, quality) in enumerate(front):
        if quality >= target_quality:
            if index == 0:
                return Estimate("measured", n, provenance, value=cost)
            c0, q0 = front[index - 1]
            fraction = (target_quality - q0) / (quality - q0)
            return Estimate(
                "measured",
                n,
                provenance,
                value=c0 + (cost - c0) * fraction,
                method="linear_interp",
            )
    return not_measured("undefined", "target_not_reached", n, provenance)


def cpt(
    call_curve: Sequence[Point], target_performance: float, *, n: int, provenance: str
) -> Estimate:
    """Call-performance threshold: the least share of calls to the strong
    model at which a router's (share, performance) curve reaches the target."""
    ordered = sorted(call_curve)
    for index, (share, performance) in enumerate(ordered):
        if performance >= target_performance:
            if index == 0:
                return Estimate("measured", n, provenance, value=share)
            s0, p0 = ordered[index - 1]
            fraction = (target_performance - p0) / (performance - p0)
            return Estimate(
                "measured",
                n,
                provenance,
                value=s0 + (share - s0) * fraction,
                method="linear_interp",
            )
    return not_measured("undefined", "target_not_reached", n, provenance)


# --- recovery and headroom ----------------------------------------------------


def _gap_guard(
    gap: float, min_gap: float | None, n: int, provenance: str
) -> Estimate | None:
    if min_gap is None:
        return not_measured("not_evaluated", "min_gap_unset", n, provenance)
    if abs(gap) < min_gap:
        return Estimate(
            "undefined",
            n,
            provenance,
            reason="gap_below_minimum",
            extra={"gap": gap},
        )
    return None


def pgr(
    quality_router: float,
    quality_weak: float,
    quality_strong: float,
    *,
    min_gap: float | None,
    n: int,
    provenance: str,
) -> Estimate:
    """Performance gap recovered: (router − weak) / (strong − weak). Undefined
    when the weak–strong gap is below ``min_gap``; the gap is always reported."""
    gap = quality_strong - quality_weak
    blocked = _gap_guard(gap, min_gap, n, provenance)
    if blocked is not None:
        return blocked
    return Estimate(
        "measured",
        n,
        provenance,
        value=(quality_router - quality_weak) / gap,
        extra={"gap": gap},
    )


def apgr(
    call_curve: Sequence[Point],
    quality_weak: float,
    quality_strong: float,
    *,
    n_points: int,
    min_gap: float | None,
    n: int,
    provenance: str,
) -> Estimate:
    """Average PGR over ``n_points`` evenly spaced strong-call shares from 0 to
    1 (both included), reading the router's (share, performance) curve by
    linear interpolation. The curve must span 0 to 1."""
    if n_points < 2:
        raise ValueError("n_points must be at least 2")
    gap = quality_strong - quality_weak
    blocked = _gap_guard(gap, min_gap, n, provenance)
    if blocked is not None:
        return blocked
    total = 0.0
    for i in range(n_points):
        performance = _interpolate(call_curve, i / (n_points - 1))
        if performance is None:
            return not_measured(
                "undefined", "curve_does_not_span_0_to_1", n, provenance
            )
        total += (performance - quality_weak) / gap
    return Estimate(
        "measured",
        n,
        provenance,
        value=total / n_points,
        method=f"mean_of_{n_points}_points",
        extra={"gap": gap},
    )


def oracle_headroom(
    cost_premium: float,
    cost_router: float,
    cost_oracle: float,
    *,
    min_gap: float | None,
    n: int,
    provenance: str,
) -> Estimate:
    """Share of the available saving captured:
    (premium − router) / (premium − oracle)."""
    gap = cost_premium - cost_oracle
    blocked = _gap_guard(gap, min_gap, n, provenance)
    if blocked is not None:
        return blocked
    return Estimate(
        "measured",
        n,
        provenance,
        value=(cost_premium - cost_router) / gap,
        extra={"gap": gap},
    )


# --- paired effects and non-inferiority --------------------------------------


@dataclass(frozen=True)
class _Pair:
    session: str
    cand_cost: float
    ref_cost: float
    cand_quality: float
    ref_quality: float


def _pairs(
    table: OutcomeTable, candidate: Mapping[str, str], reference: Mapping[str, str]
) -> list[_Pair]:
    pairs = []
    for request in table.requests:
        a = request.outcomes.get(candidate.get(request.request_id, ""))
        b = request.outcomes.get(reference.get(request.request_id, ""))
        if a is None or b is None or not (a.complete and b.complete):
            continue
        assert a.cost is not None and b.cost is not None
        assert a.quality is not None and b.quality is not None
        pairs.append(_Pair(request.session_ref, a.cost, b.cost, a.quality, b.quality))
    return pairs


def _paired(
    table: OutcomeTable,
    candidate: Mapping[str, str],
    reference: Mapping[str, str],
    *,
    quantity: str,
    min_n: int | None,
    n_boot: int,
    seed: int | str,
    level: float,
) -> tuple[Estimate, BootstrapResult | None]:
    statistics: dict[str, Callable[[Sequence[_Pair]], float | None]] = {
        "quality_diff": lambda ps: (
            sum(p.cand_quality - p.ref_quality for p in ps) / len(ps) if ps else None
        ),
        "cost_ratio": lambda ps: (
            sum(p.cand_cost for p in ps) / total
            if ps and (total := sum(p.ref_cost for p in ps)) > 0
            else None
        ),
    }
    if quantity not in statistics:
        raise ValueError(f"quantity must be one of {sorted(statistics)}")
    pairs = _pairs(table, candidate, reference)
    ok, reason = sufficient(len(pairs), min_n)
    if not ok:
        assert reason is not None
        return not_measured("insufficient", reason, len(pairs), table.provenance), None
    result = cluster_bootstrap(
        pairs,
        lambda p: p.session,
        statistics[quantity],
        n_boot=n_boot,
        seed=seed,
        level=level,
    )
    if result.point is None or result.low is None or result.high is None:
        return not_measured(
            "undefined", "statistic_undefined", len(pairs), table.provenance
        ), result
    return (
        Estimate(
            "measured",
            len(pairs),
            table.provenance,
            value=result.point,
            interval=(result.low, result.high),
            level=level,
            method="cluster_bootstrap_percentile",
            extra={"clusters": float(result.n_clusters)},
        ),
        result,
    )


def paired_effect(
    table: OutcomeTable,
    candidate: Mapping[str, str],
    reference: Mapping[str, str],
    *,
    quantity: str,
    min_n: int | None,
    n_boot: int,
    seed: int | str,
    level: float,
) -> Estimate:
    """Paired candidate-vs-reference effect over requests where both have a
    complete outcome: ``quality_diff`` (mean of candidate − reference) or
    ``cost_ratio`` (candidate total / reference total), with a session cluster
    bootstrap interval."""
    return _paired(
        table,
        candidate,
        reference,
        quantity=quantity,
        min_n=min_n,
        n_boot=n_boot,
        seed=seed,
        level=level,
    )[0]


@dataclass(frozen=True)
class NonInferiority:
    estimate: Estimate
    """The paired quality difference (candidate − reference)."""
    delta: float | None
    non_inferior: bool | None
    """True iff the interval's lower bound exceeds −δ; None if not evaluated."""
    p_value: float | None
    """One-sided bootstrap p-value for H0: difference ≤ −δ (resolution
    1/n_boot); the input to a multiple-comparison correction."""


def non_inferiority(
    table: OutcomeTable,
    candidate: Mapping[str, str],
    reference: Mapping[str, str],
    *,
    delta: float | None,
    min_n: int | None,
    n_boot: int,
    seed: int | str,
    level: float,
) -> NonInferiority:
    """Is the candidate's quality within δ of the reference? Not evaluated when
    δ is unset or the quality scores are not validated (§0.4)."""
    if not table.quality_validated:
        est = not_measured("not_evaluated", "unvalidated_quality", 0, table.provenance)
        return NonInferiority(est, delta, None, None)
    if delta is None:
        est = not_measured("not_evaluated", "delta_unset", 0, table.provenance)
        return NonInferiority(est, None, None, None)
    if delta < 0:
        raise ValueError("delta must not be negative")
    est, boot = _paired(
        table,
        candidate,
        reference,
        quantity="quality_diff",
        min_n=min_n,
        n_boot=n_boot,
        seed=seed,
        level=level,
    )
    if not est.measured or boot is None or est.interval is None:
        return NonInferiority(est, delta, None, None)
    below = sum(1 for r in boot.replicates if r <= -delta)
    return NonInferiority(
        est, delta, est.interval[0] > -delta, below / len(boot.replicates)
    )


# --- language slicing ---------------------------------------------------------


@dataclass(frozen=True)
class LanguageSlices:
    primary: Estimate
    """Persian only: the primary slice (§0.1)."""
    overall: Estimate
    others: Mapping[str, Estimate]
    """Each other language separately; never pooled into Persian."""
    overall_label: str = "dominated_by_persian"


def by_language(
    table: OutcomeTable,
    metric: Callable[[OutcomeTable], Estimate],
    *,
    min_n: int | None,
) -> LanguageSlices:
    """Apply ``metric`` to the Persian slice, the whole table, and every other
    language. A slice with fewer requests than ``min_n`` (or an unset minimum)
    becomes ``insufficient`` with no value, so it cannot be ranked or cited."""

    def one(sub: OutcomeTable) -> Estimate:
        ok, reason = sufficient(len(sub.requests), min_n)
        if not ok:
            assert reason is not None
            return not_measured(
                "insufficient", reason, len(sub.requests), sub.provenance
            )
        return metric(sub)

    languages = sorted({r.language for r in table.requests} - {PRIMARY_LANGUAGE})
    return LanguageSlices(
        primary=one(table.language(PRIMARY_LANGUAGE)),
        overall=one(table),
        others={lang: one(table.language(lang)) for lang in languages},
    )


def rank_estimates(
    estimates: Mapping[str, Estimate], *, higher_is_better: bool
) -> list[str]:
    """Labels ordered by value, only among estimates that allow claims (measured,
    with an interval). Ranking is by point value; it asserts no significance."""
    eligible = {
        k: e.value
        for k, e in estimates.items()
        if e.claims_allowed and e.value is not None
    }
    sign = -1.0 if higher_is_better else 1.0
    return sorted(eligible, key=lambda k: (sign * eligible[k], k))
