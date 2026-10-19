"""Metrics and aggregates (CMP-23; evaluation.md §6, ADR-0006, ADR-0012).

Responsibility: compute ADR-0006 metrics **from events plus cases**, overall
and per stratum, with sample sizes and intervals, into an
``EvaluationResult``; the same code later serves the dashboard. Hit rate
always comes with hit correctness (here: unmeasured, with the reason); cost
with fidelity and price version; anything that cannot be computed says so.

Inputs are the run's events: ``evaluation_scored`` (per-case baseline costs,
emitted by the runner), ``cache_lookup`` (cache-candidate runs), and
``response_returned`` (pipeline runs). Cases give strata only (opaque
category, turn depth: first or later); references are never read here.
Strata (FR-EVAL-06) used now: ``category``, ``turn_depth``. Language,
length, and component presence strata need the feature extractor's language
detector (Stage 8 plan item, not built).

Called by: evaluation.runner. Status: implemented for the two runner kinds
(Stage 8); judge scores and agreement are TODO (they need a judge and a
Persian-capable embedder, caching_plan.md and routing_plan.md).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from metis_auto.contracts import (
    SPAN_CATEGORY,
    CounterfactualSource,
    EvaluationResult,
    Event,
    ExclusionCount,
    Fidelity,
    Interval,
    LatencyCategory,
    LookupOutcome,
    MetricName,
    MetricState,
    MetricValue,
    ReplayCase,
    ResponseStatus,
    ServedBy,
    StratumKey,
    StratumResult,
)
from metis_auto.domain.accounting import worst_fidelity

USD = "usd"


@dataclass(frozen=True)
class CaseCost:
    amount: Decimal | None
    fidelity: Fidelity | None
    price_version: str | None
    reason: str | None


def case_costs(events: Iterable[Event]) -> dict[str, dict[str, CaseCost]]:
    """baseline → case ID → cost, from ``evaluation_scored`` events."""
    out: dict[str, dict[str, CaseCost]] = defaultdict(dict)
    for e in events:
        if e.event_type != "evaluation_scored" or e.case_id is None:
            continue
        for m in e.payload.metrics:  # type: ignore[union-attr]
            if m.name != MetricName.COST_PER_REQUEST or m.baseline is None:
                continue
            out[m.baseline][e.case_id] = CaseCost(
                Decimal(str(m.value)) if m.value is not None else None,
                m.token_fidelity,
                m.price_table_version,
                m.reason,
            )
    return out


def strata(
    cases: Sequence[ReplayCase],
) -> list[tuple[tuple[StratumKey, ...], list[str]]]:
    """Overall first, then each category and each turn depth."""
    groups: dict[tuple[StratumKey, ...], list[str]] = defaultdict(list)
    for c in cases:
        if c.stratum is not None:
            groups[(StratumKey(dimension="category", value=c.stratum),)].append(
                c.case_id
            )
        depth = "first" if c.turn_index == 0 else "later"
        groups[(StratumKey(dimension="turn_depth", value=depth),)].append(c.case_id)
    ordered = sorted(
        groups.items(), key=lambda kv: (kv[0][0].dimension, kv[0][0].value)
    )
    return [((), [c.case_id for c in cases]), *ordered]


def wilson(hits: int, n: int, z: float = 1.959964) -> Interval | None:
    if n == 0:
        return None
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return Interval(
        low=max(0.0, centre - half),
        high=min(1.0, centre + half),
        level=0.95,
        method="wilson",
    )


def _missing(
    name: MetricName, reason: str, n: int, state=MetricState.UNMEASURED, **kw
) -> MetricValue:
    return MetricValue(name=name, state=state, n=n, reason=reason, **kw)


def money_metric(
    name: MetricName,
    costs: Sequence[CaseCost],
    *,
    baseline: str | None,
    mean: bool = False,
    reason_if_none: str = "no_computed_cases",
    **kw,
) -> MetricValue:
    computed = [c for c in costs if c.amount is not None]
    if not computed:
        return _missing(
            name, reason_if_none, 0, MetricState.NOT_COMPUTED, baseline=baseline, **kw
        )
    total = sum((c.amount for c in computed), Decimal(0))  # type: ignore[misc]
    value = total / len(computed) if mean else total
    versions = sorted({c.price_version for c in computed if c.price_version})
    return MetricValue(
        name=name,
        state=MetricState.MEASURED,
        value=float(value),
        unit=USD,
        n=len(computed),
        baseline=baseline,
        token_fidelity=worst_fidelity(c.fidelity for c in computed if c.fidelity)
        or Fidelity.APPROXIMATION,
        price_table_version="+".join(versions) or "unknown",
        **kw,
    )


def baseline_metrics(
    ids: Sequence[str],
    costs: Mapping[str, Mapping[str, CaseCost]],
    baselines: Sequence[str],
) -> list[MetricValue]:
    out: list[MetricValue] = []
    for b in baselines:
        per_case = [costs.get(b, {}).get(i) for i in ids]
        present = [c for c in per_case if c is not None]
        out.append(money_metric(MetricName.TOTAL_COST, present, baseline=b))
        out.append(
            money_metric(MetricName.COST_PER_REQUEST, present, baseline=b, mean=True)
        )
    return out


# --- cache-candidate runs --------------------------------------------------


def lookups(
    events: Iterable[Event],
) -> dict[tuple[str, str], dict[str, tuple[LookupOutcome, str | None, str | None]]]:
    """(variant, scope) → case ID → (outcome, ineligible reason, matched case)."""
    out: dict[
        tuple[str, str], dict[str, tuple[LookupOutcome, str | None, str | None]]
    ] = defaultdict(dict)
    for e in events:
        if e.event_type != "cache_lookup" or e.case_id is None:
            continue
        r = e.payload.result  # type: ignore[union-attr]
        matched = r.entry_id.removeprefix("entry:") if r.entry_id else None
        reason = r.ineligible_reason.value if r.ineligible_reason else None
        out[(r.key_variant or "", r.scope.value if r.scope else "")][e.case_id] = (
            r.outcome,
            reason,
            matched,
        )
    return out


def answer_coverage(
    ids: Sequence[str], as_logged: Mapping[str, CaseCost]
) -> MetricValue:
    """Cases with a logged answer (the logged source's coverage, ADR-0014),
    from the as-logged events: ``usage_unknown`` means no reference."""
    covered = sum(
        1 for i in ids if i in as_logged and as_logged[i].reason != "usage_unknown"
    )
    return MetricValue(
        name=MetricName.COVERAGE,
        state=MetricState.MEASURED,
        value=covered / len(ids) if ids else 0.0,
        unit="ratio",
        n=len(ids),
        interval=wilson(covered, len(ids)),
    )


def cache_metrics(
    ids: Sequence[str],
    found: Mapping[
        tuple[str, str], Mapping[str, tuple[LookupOutcome, str | None, str | None]]
    ],
    as_logged: Mapping[str, CaseCost],
) -> list[MetricValue]:
    out: list[MetricValue] = [answer_coverage(ids, as_logged)]
    for (variant, scope), per_case in sorted(found.items()):
        hits = [i for i in ids if per_case.get(i, (None,))[0] == LookupOutcome.HIT]
        kw = dict(key_variant=variant, scope=scope)
        out.append(
            MetricValue(
                name=MetricName.CANDIDATE_HIT_RATE,
                state=MetricState.MEASURED,
                value=len(hits) / len(ids) if ids else 0.0,
                unit="ratio",
                n=len(ids),
                interval=wilson(len(hits), len(ids)),
                **kw,
            )
        )
        out.append(
            _missing(MetricName.HIT_CORRECTNESS, "no_quality_signal", len(hits), **kw)
        )
        hit_costs = [as_logged[i] for i in hits if i in as_logged]
        if hits:
            out.append(
                money_metric(
                    MetricName.SAVINGS,
                    hit_costs,
                    baseline="as_logged",
                    reason_if_none="as_logged_not_computed",
                    **kw,
                )
            )
        else:
            out.append(
                _missing(
                    MetricName.SAVINGS,
                    "no_candidate_hits",
                    0,
                    MetricState.NOT_COMPUTED,
                    baseline="as_logged",
                    **kw,
                )
            )
    return out


def variant_table(
    found: Mapping[
        tuple[str, str], Mapping[str, tuple[LookupOutcome, str | None, str | None]]
    ],
    session_of: Mapping[str, str],
) -> dict[str, dict[str, int]]:
    """Content-free per-variant counts derived from ``cache_lookup`` events:
    eligible, ineligible by reason, hits per scope, and cross-session hits
    (a global hit whose case had no same-session match)."""
    table: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    variants_seen = sorted({v for v, _ in found})
    for v in variants_seen:
        session = found.get((v, "session"), {})
        globl = found.get((v, "global"), {})
        row = table[v]
        for case_id, (outcome, reason, matched) in globl.items():
            if outcome == LookupOutcome.INELIGIBLE:
                row[f"ineligible_{reason}"] += 1
                continue
            row["eligible"] += 1
            if outcome == LookupOutcome.HIT:
                row["hits_global"] += 1
                if session.get(case_id, (None,))[0] != LookupOutcome.HIT:
                    row["hits_cross_session"] += 1
                    assert matched is None or session_of.get(matched) != session_of.get(
                        case_id
                    )
        row["hits_session"] = sum(
            1 for o, _, _ in session.values() if o == LookupOutcome.HIT
        )
        row["cases"] = len(globl)
    return {v: dict(r) for v, r in table.items()}


# --- pipeline runs -----------------------------------------------------------


def pipeline_metrics(
    ids: Sequence[str],
    responses: Mapping[str, Event],
    costs: Mapping[str, Mapping[str, CaseCost]],
    baselines: Sequence[str],
    source: CounterfactualSource,
) -> list[MetricValue]:
    got = [responses[i] for i in ids if i in responses]
    metas = [e.payload.metadata for e in got]  # type: ignore[union-attr]
    answered = [e for e in got if e.payload.status == ResponseStatus.OK]  # type: ignore[union-attr]
    out = [
        MetricValue(
            name=MetricName.COVERAGE,
            state=MetricState.MEASURED,
            value=len(answered) / len(ids) if ids else 0.0,
            unit="ratio",
            n=len(ids),
            interval=wilson(len(answered), len(ids)),
        )
    ]
    candidate: dict[str, CaseCost] = {}
    for e in got:
        cost = e.payload.metadata.total_cost  # type: ignore[union-attr]
        candidate[e.case_id or ""] = CaseCost(
            cost.amount.amount if cost.amount else None,
            cost.token_fidelity,
            cost.price_table_version,
            cost.reason.value if cost.reason else None,
        )
    out.append(
        money_metric(MetricName.TOTAL_COST, list(candidate.values()), baseline=None)
    )
    out.append(
        money_metric(
            MetricName.COST_PER_REQUEST,
            list(candidate.values()),
            baseline=None,
            mean=True,
        )
    )
    for b in baselines:
        diffs = []
        for i in ids:
            base, cand = costs.get(b, {}).get(i), candidate.get(i)
            if base and cand and base.amount is not None and cand.amount is not None:
                diffs.append(
                    CaseCost(
                        base.amount - cand.amount,
                        worst_fidelity(f for f in (base.fidelity, cand.fidelity) if f),
                        "+".join(
                            sorted(
                                {
                                    v
                                    for v in (base.price_version, cand.price_version)
                                    if v
                                }
                            )
                        ),
                        None,
                    )
                )
        out.append(money_metric(MetricName.SAVINGS, diffs, baseline=b))
    hits = sum(1 for m in metas if m.served_by == ServedBy.CACHE)
    out.append(
        MetricValue(
            name=MetricName.CANDIDATE_HIT_RATE,
            state=MetricState.MEASURED,
            value=hits / len(ids) if ids else 0.0,
            unit="ratio",
            n=len(ids),
            interval=wilson(hits, len(ids)),
        )
    )
    out.append(_missing(MetricName.HIT_CORRECTNESS, "no_quality_signal", hits))
    overhead = [
        sum(
            s.duration_ms
            for s in m.spans
            if SPAN_CATEGORY[s.span] == LatencyCategory.OVERHEAD
        )
        for m in metas
    ]
    if overhead:
        q = (
            statistics.quantiles(overhead, n=20, method="inclusive")
            if len(overhead) > 1
            else [overhead[0]] * 19
        )
        for name, value in (
            (MetricName.OVERHEAD_LATENCY_P50, statistics.median(overhead)),
            (MetricName.OVERHEAD_LATENCY_P95, q[18]),
        ):
            out.append(
                MetricValue(
                    name=name,
                    state=MetricState.MEASURED,
                    value=value,
                    unit="ms",
                    n=len(overhead),
                )
            )
    live_like = source in (CounterfactualSource.LIVE, CounterfactualSource.RECORDED)
    out.append(
        _missing(
            MetricName.MODEL_LATENCY,
            "not_aggregated_yet" if live_like else "offline_source",
            len(got),
        )
    )
    return out


def result(
    *,
    run_id: str,
    experiment_id: str,
    source: CounterfactualSource,
    cases: Sequence[ReplayCase],
    covered: int,
    baselines: Sequence[str],
    exclusions: Sequence[ExclusionCount],
    per_stratum: Callable[[Sequence[str]], list[MetricValue]],
    declared: Sequence[MetricName] = (),
) -> EvaluationResult:
    results = []
    for key, ids in strata(cases):
        metrics = per_stratum(ids)
        if not key:
            produced = {m.name for m in metrics}
            metrics += [
                _missing(name, "not_produced_by_runner", 0)
                for name in declared
                if name not in produced
            ]
        results.append(
            StratumResult(stratum=key, n_cases=len(ids), metrics=tuple(metrics))
        )
    return EvaluationResult(
        run_id=run_id,
        experiment_id=experiment_id,
        counterfactual_source=source,
        cases_total=len(cases),
        cases_covered=covered,
        baselines=tuple(baselines),
        results=tuple(results),
        exclusions=tuple(exclusions),
    )
