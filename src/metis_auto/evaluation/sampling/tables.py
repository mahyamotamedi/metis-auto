"""From a run to calibration data and the per-model comparison (Stage E4;
framework §0.7, §2.2, §6).

``usage_records`` turns reported usage into E2 ``UsageRecord``s (the cost-model
fit); ``outcome_table`` turns it into an E1 ``OutcomeTable`` (cost per request
and model, quality when supplied); ``comparison_table`` is the Persian-first
per-model table with quality, cost, latency, n and uncertainty as separate
columns and no combined score; ``population_total`` applies the stored
selection weights (population totals), kept apart from allocation.

Only the first call of each (case, model, effort) is used (``repeat_index`` 0),
so the repeat subset does not tilt a comparison; repeats are for variance.
Provenance is the run's: ``measured`` only for live or recorded answers,
``simulated`` for fakes. Quality is ``not_evaluated`` until scores are
supplied, and carries whether they are validated (§0.4). Pure.
Status: provisional (Stage E4).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from metis_auto.evaluation.comparison.stats import cluster_bootstrap
from metis_auto.evaluation.comparison.types import (
    PRIMARY_LANGUAGE,
    Estimate,
    EvalRequest,
    Outcome,
    OutcomeTable,
    not_measured,
    sufficient,
)
from metis_auto.evaluation.costing import (
    UsageRecord,
    empirical_quantile,
    min_n_for_quantile,
)

from .allocation import SamplingPlan, SamplingUnit
from .runner import CallRecord, RunResult

Key = tuple[str, str, str | None]
"""(case_id, model_id, effort)"""


@dataclass(frozen=True)
class BootstrapSettings:
    n_boot: int
    seed: int | str
    level: float


def model_key(model_id: str, effort: str | None) -> str:
    return model_id if effort is None else f"{model_id}@{effort}"


def _first_calls(result: RunResult) -> list[CallRecord]:
    return [r for r in result.records if r.repeat_index == 0]


def usage_records(
    result: RunResult, units: Mapping[str, SamplingUnit]
) -> list[UsageRecord]:
    """Reported usage as ``UsageRecord``s for the E2 estimators (all repeats)."""
    out = []
    for r in result.records:
        if r.outcome != "response" or r.input_tokens is None or r.output_tokens is None:
            continue
        unit = units[r.case_id]
        logged = unit.numeric.get("logged_answer_chars")
        out.append(
            UsageRecord(
                request_id=f"{r.case_id}#{r.repeat_index}",
                session_ref=r.session_ref,
                model_id=r.model_id,
                effort=r.effort,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                reasoning_tokens=r.reasoning_tokens,
                cached_input_tokens=r.cached_input_tokens,
                visible_output_chars=r.answer_chars,
                logged_answer_chars=None if logged is None else int(logged),
                strata=dict(unit.strata),
            )
        )
    return out


def outcome_table(
    result: RunResult,
    units: Mapping[str, SamplingUnit],
    *,
    quality_by_call: Mapping[Key, float] | None = None,
    quality_provenance: str = "estimated",
    quality_validated: bool = False,
) -> OutcomeTable:
    """One E1 request per case with an outcome per (model, effort). Cost comes
    from reported usage; quality only if supplied (E5), else None, which E1
    treats as incomplete (the oracle and non-inferiority then say so)."""
    by_case: dict[str, dict[str, Outcome]] = defaultdict(dict)
    for r in _first_calls(result):
        cost = None if r.cost_usd is None else float(r.cost_usd)
        quality = (quality_by_call or {}).get((r.case_id, r.model_id, r.effort))
        by_case[r.case_id][model_key(r.model_id, r.effort)] = Outcome(cost, quality)
    provenance = _run_provenance(result)
    requests = tuple(
        EvalRequest(
            case_id,
            units[case_id].session_ref,
            units[case_id].strata.get("language", "unknown"),
            outcomes,
        )
        for case_id, outcomes in by_case.items()
    )
    return OutcomeTable(requests, provenance, quality_provenance, quality_validated)


def _run_provenance(result: RunResult) -> str:
    kinds = {r.provenance for r in result.records}
    if not kinds:
        return "simulated"
    return "measured" if kinds == {"measured"} else "simulated"


@dataclass(frozen=True)
class ComparisonRow:
    language: str
    model_id: str
    effort: str | None
    n_calls: int
    n_answered: int
    error_share: float | None
    cost_mean_usd: Estimate
    cost_median_usd: Estimate
    latency_total_ms: Estimate
    ttft_ms: Estimate
    quality: Estimate
    label: str
    """``rankable`` only if n meets the configured minimum, else
    ``descriptive`` (values shown, no ranking claim)."""
    label_reason: str | None
    provenance: str


def _mean_estimate(
    values: Sequence[tuple[str, float]],
    provenance: str,
    boot: BootstrapSettings | None,
    reason: str,
) -> Estimate:
    if not values:
        return not_measured("not_evaluated", reason, 0, provenance)
    point = sum(v for _, v in values) / len(values)
    if boot is None:
        return Estimate("measured", len(values), provenance, value=point, method="mean")
    result = cluster_bootstrap(
        values,
        lambda x: x[0],
        lambda xs: sum(v for _, v in xs) / len(xs) if xs else None,
        n_boot=boot.n_boot,
        seed=boot.seed,
        level=boot.level,
    )
    interval = (
        None if result.low is None or result.high is None else (result.low, result.high)
    )
    return Estimate(
        "measured",
        len(values),
        provenance,
        value=point,
        interval=interval,
        level=boot.level if interval else None,
        method="mean_cluster_bootstrap" if interval else "mean",
    )


def _median_estimate(values: Sequence[float], provenance: str) -> Estimate:
    if not values:
        return not_measured("not_evaluated", "no_cost_reported", 0, provenance)
    if len(values) < min_n_for_quantile(0.5):
        return not_measured(
            "insufficient", "quantile_not_identifiable", len(values), provenance
        )
    value = empirical_quantile(values, 0.5)
    assert value is not None
    return Estimate("measured", len(values), provenance, value=value, method="median")


def comparison_table(
    result: RunResult,
    units: Mapping[str, SamplingUnit],
    *,
    min_n: int | None,
    boot: BootstrapSettings | None = None,
    quality_by_call: Mapping[Key, float] | None = None,
    quality_validated: bool = False,
) -> list[ComparisonRow]:
    """Persian first, then each other language separately, one row per model
    and effort. Columns are separate; there is no combined score."""
    provenance = _run_provenance(result)
    groups: dict[tuple[str, str, str | None], list[CallRecord]] = defaultdict(list)
    for r in _first_calls(result):
        language = units[r.case_id].strata.get("language", "unknown")
        groups[(language, r.model_id, r.effort)].append(r)
    rows = []
    order = sorted(
        groups, key=lambda k: (k[0] != PRIMARY_LANGUAGE, k[0], k[1], k[2] or "")
    )
    for language, model_id, effort in order:
        calls = groups[(language, model_id, effort)]
        answered = [c for c in calls if c.outcome == "response"]
        costs = [
            (c.session_ref, float(c.cost_usd))
            for c in answered
            if c.cost_usd is not None
        ]
        latencies = [
            (c.session_ref, c.latency_ms) for c in answered if c.latency_ms is not None
        ]
        scored = [
            (c.session_ref, (quality_by_call or {})[(c.case_id, c.model_id, c.effort)])
            for c in answered
            if (c.case_id, c.model_id, c.effort) in (quality_by_call or {})
        ]
        if quality_by_call is None or not scored:
            quality = not_measured("not_evaluated", "no_judge_scores", 0, "estimated")
        else:
            quality = _mean_estimate(
                scored,
                "measured" if quality_validated else "estimated",
                boot,
                "no_judge_scores",
            )
            quality = Estimate(
                quality.state,
                quality.n,
                quality.provenance,
                value=quality.value,
                interval=quality.interval,
                level=quality.level,
                method=quality.method,
                reason=quality.reason,
                extra={"validated": "yes" if quality_validated else "no"},
            )
        ok, reason = sufficient(len(calls), min_n)
        rows.append(
            ComparisonRow(
                language=language,
                model_id=model_id,
                effort=effort,
                n_calls=len(calls),
                n_answered=len(answered),
                error_share=(len(calls) - len(answered)) / len(calls)
                if calls
                else None,
                cost_mean_usd=_mean_estimate(
                    costs, provenance, boot, "no_cost_reported"
                ),
                cost_median_usd=_median_estimate([v for _, v in costs], provenance),
                latency_total_ms=_mean_estimate(
                    latencies, provenance, boot, "no_latency_reported"
                ),
                ttft_ms=_mean_estimate(
                    [
                        (c.session_ref, c.ttft_ms)
                        for c in answered
                        if c.ttft_ms is not None
                    ],
                    provenance,
                    boot,
                    "ttft_not_reported",
                ),
                quality=quality,
                label="rankable" if ok else "descriptive",
                label_reason=reason,
                provenance=provenance,
            )
        )
    return rows


def population_total(
    result: RunResult, plan: SamplingPlan, model_id: str, effort: str | None = None
) -> Estimate:
    """Population-level total cost for one (model, effort): the sum over the
    drawn units of weight × cost (a Horvitz-Thompson style total). Needs a cost
    for every drawn unit; otherwise it says so. Allocation does not enter."""
    weights = {s.case_id: s.weight for s in plan.selected}
    provenance = _run_provenance(result)
    cost_of_case: dict[str, Decimal | None] = {}
    for r in _first_calls(result):
        if r.model_id == model_id and r.effort == effort:
            cost_of_case[r.case_id] = r.cost_usd
    missing = [c for c in weights if cost_of_case.get(c) is None]
    if missing:
        return not_measured(
            "not_evaluated",
            "cost_missing_for_drawn_units",
            len(weights) - len(missing),
            provenance,
        )
    total = sum(float(weights[c]) * float(cost_of_case[c]) for c in weights)  # type: ignore[arg-type]
    return Estimate(
        "measured", len(weights), provenance, value=total, method="weighted_total"
    )
