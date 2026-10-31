# ruff: noqa: E501  (long caveat and table-header strings; wrapping them hurts reading)
"""The comparison report: paired effects, coverage, scenarios, open items
(Stage E6; framework §1, §0.1, §6; FR-EVAL-06, -08, -09).

Assembles what E1 to E5 produce into one feature-only report, with no
dashboard and no text:

- **Effects** (claims): per language slice (Persian first, then every other
  language separately, then ``all`` labelled "dominated_by_persian") and per
  candidate versus the reference: paired quality difference and paired cost
  ratio, each with a session-cluster bootstrap interval, and the
  non-inferiority flag against a configured δ. A slice below the configured
  minimum n, or with an unset minimum, shows **no value**, only ``insufficient``
  and why. Quality from a slice whose judge gate has not passed is marked
  ``unvalidated`` and cannot reach the non-inferiority flag.
- **Descriptive per-model table** (E4 comparison): values with n and a
  sufficiency label, no ranking claim; quality, cost, latency and time to first
  token are separate columns.
- **Coverage**: the sampling plan (population, drawn, over-budget), the
  population, sample and *weighted* shares side by side (allocation is not
  weighting), quotas, run completion and halts, judge and image exclusions.
- **Scenarios**: the E2 cost rows by model and scenario; unset ones are
  ``not_evaluated`` with their reasons.
- **Open items**: every configured-or-not decision the report depends on, so
  an unset value is visible, not hidden.

Every number carries its provenance (measured, estimated, simulated; input-only
costs are lower bounds). ``price_table_version``, its age and the counterfactual
source are in the header. Pure: it returns data and strings; the caller writes
files. Status: provisional (Stage E6). Not run on real data: none exists.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from metis_auto.evaluation.comparison import (
    PRIMARY_LANGUAGE,
    Estimate,
    OutcomeTable,
    non_inferiority,
    paired_effect,
)
from metis_auto.evaluation.costing import PriceAge, ScenarioCost
from metis_auto.evaluation.judging import GateResult, JudgeRun, gated_tables
from metis_auto.evaluation.sampling import (
    ComparisonRow,
    RunResult,
    SamplingPlan,
    SamplingUnit,
    comparison_table,
    slice_counts,
)
from metis_auto.evaluation.sampling.tables import BootstrapSettings

OVERALL_NOTE = "dominated_by_persian"


@dataclass(frozen=True)
class EffectRow:
    language: str
    note: str | None
    candidate: str
    reference: str
    n_requests: int
    label: str
    """``rankable`` or ``descriptive`` (sufficiency only; never a winner)."""
    label_reason: str | None
    quality_status: str
    """``validated`` or ``unvalidated`` (the Persian gate, per language)."""
    gate_reason: str | None
    quality_diff: Estimate
    cost_ratio: Estimate
    non_inferiority: str
    """``established``, ``not_established`` or ``not_evaluated``."""
    non_inferiority_reason: str | None
    delta: float | None
    p_value: float | None
    provenance: str


@dataclass(frozen=True)
class ScenarioLine:
    model_id: str
    effort: str | None
    output_scenario: str | None
    cache_scenario: str | None
    state: str
    reason: str | None
    provenance: str | None
    total_usd: Decimal | None
    reading: str
    """``lower_bound_input_only`` for the input-only row, ``scenario`` for a
    computed scenario row, ``not_evaluated`` otherwise."""


@dataclass(frozen=True)
class OpenItem:
    item: str
    state: str
    """``set``, ``unset`` or ``not_evaluated``."""
    reason: str | None


@dataclass(frozen=True)
class ComparisonReport:
    report_id: str
    generated_on: date
    price_table_version: str
    price_age: PriceAge
    counterfactual_sources: tuple[str, ...]
    provenance: str
    judge_id: str | None
    judge_instruction_language: str | None
    reference: str
    effects: tuple[EffectRow, ...]
    descriptive: tuple[ComparisonRow, ...]
    coverage: Mapping[str, object]
    scenarios: tuple[ScenarioLine, ...]
    open_items: tuple[OpenItem, ...]
    caveats: tuple[str, ...] = field(default_factory=tuple)


def _scenario_lines(rows: Sequence[ScenarioCost]) -> tuple[ScenarioLine, ...]:
    lines = []
    for r in rows:
        if r.state != "computed":
            reading = "not_evaluated"
        elif r.output_scenario == "input_only":
            reading = "lower_bound_input_only"
        else:
            reading = "scenario"
        lines.append(
            ScenarioLine(
                r.model_id,
                r.effort,
                r.output_scenario,
                r.cache_scenario,
                r.state,
                r.reason,
                r.provenance,
                r.total_usd,
                reading,
            )
        )
    return tuple(lines)


def _slices(table: OutcomeTable) -> list[tuple[str, str | None]]:
    languages = sorted(
        {r.language for r in table.requests}, key=lambda v: (v != PRIMARY_LANGUAGE, v)
    )
    return [
        (lang, "primary slice" if lang == PRIMARY_LANGUAGE else "separate slice")
        for lang in languages
    ] + [("all", OVERALL_NOTE)]


def build_comparison_report(
    *,
    report_id: str,
    generated_on: date,
    table: OutcomeTable,
    gate_results: Mapping[str, GateResult],
    reference: str,
    candidates: Sequence[str],
    delta: float | None,
    min_n: int | None,
    bootstrap: BootstrapSettings | None,
    price_age: PriceAge,
    price_table_version: str,
    run: RunResult,
    plan: SamplingPlan,
    units: Mapping[str, SamplingUnit],
    judge: JudgeRun | None,
    scenarios: Sequence[ScenarioCost],
    image_exclusions: Mapping[str, int] | None = None,
) -> ComparisonReport:
    if bootstrap is None:
        # intervals need n_boot, a seed and a level: all caller decisions
        boot_args = None
    else:
        boot_args = {
            "n_boot": bootstrap.n_boot,
            "seed": bootstrap.seed,
            "level": bootstrap.level,
        }
    tables = gated_tables(table, gate_results)
    effects: list[EffectRow] = []
    for language, note in _slices(table):
        sub = tables[language]
        gate = gate_results.get(language)
        for candidate in candidates:
            cand = {
                r.request_id: candidate for r in sub.requests if candidate in r.outcomes
            }
            ref = {
                r.request_id: reference for r in sub.requests if reference in r.outcomes
            }
            if boot_args is None:
                insufficient = Estimate(
                    "insufficient", 0, sub.provenance, reason="bootstrap_unset"
                )
                quality_diff = cost_ratio = insufficient
                ni_state, ni_reason, p_value = "not_evaluated", "bootstrap_unset", None
            else:
                quality_diff = paired_effect(
                    sub, cand, ref, quantity="quality_diff", min_n=min_n, **boot_args
                )
                cost_ratio = paired_effect(
                    sub, cand, ref, quantity="cost_ratio", min_n=min_n, **boot_args
                )
                ni = non_inferiority(
                    sub, cand, ref, delta=delta, min_n=min_n, **boot_args
                )
                if ni.non_inferior is None:
                    ni_state, ni_reason = "not_evaluated", ni.estimate.reason
                else:
                    ni_state = "established" if ni.non_inferior else "not_established"
                    ni_reason = None
                p_value = ni.p_value
            effects.append(
                EffectRow(
                    language=language,
                    note=note,
                    candidate=candidate,
                    reference=reference,
                    n_requests=quality_diff.n,
                    label="rankable" if quality_diff.measured else "descriptive",
                    label_reason=None if quality_diff.measured else quality_diff.reason,
                    quality_status="validated"
                    if sub.quality_validated
                    else "unvalidated",
                    gate_reason=None
                    if sub.quality_validated
                    else (gate.reason if gate else "no_gate_result"),
                    quality_diff=quality_diff,
                    cost_ratio=cost_ratio,
                    non_inferiority=ni_state,
                    non_inferiority_reason=ni_reason,
                    delta=delta,
                    p_value=p_value,
                    provenance=sub.provenance,
                )
            )
    shares = {
        dim: [
            dataclasses.asdict(r)
            for r in slice_counts(plan, list(units.values()), dim, min_n=min_n)
        ]
        for dim in ("language",)
    }
    coverage: dict[str, object] = {
        "sampling": {
            "state": plan.state,
            "reason": plan.reason,
            "population": plan.population,
            "requested_total": plan.requested_total,
            "achieved_total": plan.achieved_total,
            "over_budget_by": plan.over_budget_by,
            "quotas": [dataclasses.asdict(q) for q in plan.quotas],
            "shares_by_slice": shares,
            "note": "sample_share is the allocation; weighted_share applies the stored weights and recovers the population; neither is the other",
        },
        "run": {
            "planned_calls": run.planned_calls,
            "executed_calls": run.executed_calls,
            "skipped_calls": run.skipped_calls,
            "halts": [dataclasses.asdict(h) for h in run.halts],
            "sources": list(run.sources),
            "stop_rules": dict(run.stop_rules),
        },
        "judge": None
        if judge is None
        else {
            "judged": len(judge.judged),
            "excluded_by_reason": dict(judge.excluded_by_reason),
            "cost_usd_total": str(judge.cost_usd_total),
            "cost_kind": judge.cost_kind,
        },
        "image_exclusions": dict(image_exclusions or {}),
    }
    open_items = [
        OpenItem(
            "delta",
            "set" if delta is not None else "unset",
            None if delta is not None else "delta_unset",
        ),
        OpenItem(
            "min_n",
            "set" if min_n is not None else "unset",
            None if min_n is not None else "min_n_unset",
        ),
        OpenItem(
            "bootstrap",
            "set" if bootstrap else "unset",
            None if bootstrap else "bootstrap_unset",
        ),
        OpenItem(
            "price_max_age",
            "set" if price_age.max_age_days is not None else "unset",
            price_age.reason,
        ),
    ]
    for language, result in sorted(gate_results.items()):
        open_items.append(
            OpenItem(
                f"judge_gate:{language}",
                "set" if result.validated else "not_evaluated",
                result.reason,
            )
        )
    if plan.state != "planned":
        open_items.append(OpenItem("sampling_plan", "unset", plan.reason))
    return ComparisonReport(
        report_id=report_id,
        generated_on=generated_on,
        price_table_version=price_table_version,
        price_age=price_age,
        counterfactual_sources=run.sources,
        provenance=table.provenance,
        judge_id=judge.judge_id if judge else None,
        judge_instruction_language=judge.instruction_language if judge else None,
        reference=reference,
        effects=tuple(effects),
        descriptive=tuple(comparison_table(run, units, min_n=min_n, boot=bootstrap)),
        coverage=coverage,
        scenarios=_scenario_lines(scenarios),
        open_items=tuple(open_items),
        caveats=(
            "feature-only: no text, no per-case value, no hash",
            "Persian-only slices are primary; other languages are separate and never pooled into Persian",
            "a slice below the configured minimum n shows no value, only why",
            "quality scores are unvalidated unless that language's judge gate passed",
            "costs: input-only rows are lower bounds; scenario rows are simulated or estimated as labelled; only live or recorded runs are measured",
            "price table is a historical snapshot; its age and max-age status are in the header",
        ),
    )
