# ruff: noqa: E501  (long caveat and table-header strings; wrapping them hurts reading)
"""Render a ``ComparisonReport`` to JSON-safe data and Markdown (Stage E6).

Pure: returns a dict and strings; the caller writes
``reports/<area>/<id>/report.json`` and ``report.md`` (feature-only files).
Every estimate is printed with its state, n and provenance; a value withheld
for insufficiency is printed as the reason, never as a number. Status:
provisional (Stage E6).
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from metis_auto.evaluation.comparison import Estimate

from .report import ComparisonReport


def to_plain(value: Any) -> Any:
    """Dataclasses, mappings and sequences as JSON-safe data."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: to_plain(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float) and value in (float("inf"), float("-inf")):
        return "inf" if value > 0 else "-inf"
    return value


def _est(e: Estimate) -> str:
    if not e.measured or e.value is None:
        return f"— ({e.state}: {e.reason}) [n={e.n}, {e.provenance}]"
    text = f"{e.value:.4g}"
    if e.interval is not None:
        text += f" [{e.interval[0]:.4g}, {e.interval[1]:.4g}]"
    return f"{text} [n={e.n}, {e.provenance}]"


def _table(header: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_none_\n"
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def to_markdown(report: ComparisonReport) -> str:
    age = report.price_age
    out = [
        f"# Comparison report: {report.report_id}\n",
        f"Generated {report.generated_on.isoformat()}. Feature-only (no text, no hash, no per-case value).\n",
        "## Header\n",
        f"- price table `{report.price_table_version}`, checked {age.checked_on}, "
        f"age {age.age_days} days, max age `{age.max_age_days}`: **{age.state}**"
        f"{f' ({age.reason})' if age.reason else ''}. {age.consequence}",
        f"- counterfactual source(s): {', '.join(report.counterfactual_sources) or 'none'}",
        f"- provenance: {report.provenance}",
        f"- judge: {report.judge_id or 'none'}"
        f"{f' (instructions: {report.judge_instruction_language})' if report.judge_instruction_language else ''}",
        f"- reference: `{report.reference}`\n",
        "## Effects versus the reference (claims)\n",
        "Persian-only first; other languages separate; `all` is dominated by Persian. "
        "A slice below the minimum n shows no value.\n",
    ]
    out.append(
        _table(
            [
                "slice",
                "candidate",
                "label",
                "quality diff (paired)",
                "cost ratio (paired)",
                "quality",
                "non-inferiority",
                "provenance",
            ],
            [
                [
                    f"{e.language}{f' ({e.note})' if e.note else ''}",
                    e.candidate,
                    f"{e.label}" + (f" ({e.label_reason})" if e.label_reason else ""),
                    _est(e.quality_diff),
                    _est(e.cost_ratio),
                    e.quality_status + (f" ({e.gate_reason})" if e.gate_reason else ""),
                    f"{e.non_inferiority}"
                    + (
                        f" ({e.non_inferiority_reason})"
                        if e.non_inferiority_reason
                        else ""
                    )
                    + (f", delta={e.delta}" if e.delta is not None else ""),
                    e.provenance,
                ]
                for e in report.effects
            ],
        )
    )
    out.append("## Per-model table (descriptive; no ranking claim)\n")
    out.append(
        _table(
            [
                "language",
                "model",
                "effort",
                "n calls",
                "label",
                "cost mean USD",
                "latency ms",
                "ttft ms",
                "quality",
                "provenance",
            ],
            [
                [
                    r.language,
                    r.model_id,
                    str(r.effort),
                    str(r.n_calls),
                    r.label + (f" ({r.label_reason})" if r.label_reason else ""),
                    _est(r.cost_mean_usd),
                    _est(r.latency_total_ms),
                    _est(r.ttft_ms),
                    _est(r.quality),
                    r.provenance,
                ]
                for r in report.descriptive
            ],
        )
    )
    sampling = report.coverage["sampling"]
    run = report.coverage["run"]
    plan_reason = f" ({sampling['reason']})" if sampling["reason"] else ""
    out += [
        "## Coverage\n",
        f"- sampling plan: {sampling['state']}"
        f"{plan_reason}; "
        f"population {sampling['population']}, drawn {sampling['achieved_total']} of {sampling['requested_total']}, "
        f"over budget by {sampling['over_budget_by']}",
        f"- {sampling['note']}",
        f"- run: {run['executed_calls']} of {run['planned_calls']} calls executed, {run['skipped_calls']} skipped; halts: {run['halts'] or 'none'}",
        f"- judge: {report.coverage['judge']}",
        f"- image exclusions: {report.coverage['image_exclusions'] or 'none'}\n",
    ]
    slices = sampling["shares_by_slice"].get("language", [])
    out.append(
        _table(
            [
                "language",
                "population",
                "drawn",
                "population share",
                "sample share (allocation)",
                "weighted share",
                "sufficiency",
            ],
            [
                [
                    s["value"],
                    str(s["population"]),
                    str(s["selected"]),
                    f"{s['population_share']:.3f}",
                    f"{s['sample_share']:.3f}",
                    f"{s['weighted_share']:.3f}",
                    s["sufficiency"]
                    + (
                        f" ({s['sufficiency_reason']})"
                        if s["sufficiency_reason"]
                        else ""
                    ),
                ]
                for s in slices
            ],
        )
    )
    out.append("## Scenario sensitivity (E2)\n")
    out.append(
        _table(
            [
                "model",
                "effort",
                "output scenario",
                "cache scenario",
                "state",
                "total USD",
                "reading",
                "provenance",
            ],
            [
                [
                    s.model_id,
                    str(s.effort),
                    str(s.output_scenario),
                    str(s.cache_scenario),
                    s.state + (f" ({s.reason})" if s.reason else ""),
                    "—" if s.total_usd is None else str(s.total_usd),
                    s.reading,
                    str(s.provenance),
                ]
                for s in report.scenarios
            ],
        )
    )
    out.append("## Open items\n")
    out.append(
        _table(
            ["item", "state", "reason"],
            [[o.item, o.state, str(o.reason)] for o in report.open_items],
        )
    )
    out.append("## Caveats\n")
    out += [f"- {c}" for c in report.caveats]
    return "\n".join(out) + "\n"
