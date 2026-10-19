"""Comparison format (CMP-24; docs/experiments/framework.md §6).

Responsibility: put several runs' ``EvaluationResult``s side by side in one
shape, whatever the runner kind or strategy: **one row per run × key
variant × scope × baseline**, one column per metric, for one stratum
(overall by default). A cell is the value with its n and interval, or the
state and reason (``unmeasured: no_quality_signal``); "not computed" never
shows as zero. Rows carry the manifest facts a reader needs to know whether
two rows are comparable (source, data hash, config hash, key ID, assumption).
Called by: scripts/compare_runs.py, scripts/run_experiment.py.
Status: provisional (Stage 8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from metis_auto.contracts import EvaluationResult, MetricState, MetricValue, RunManifest


@dataclass
class ComparisonRow:
    experiment_id: str
    run_id: str
    source: str
    composition: str
    data_hash: str | None
    config_hash: str | None
    key_id: str | None
    key_variant: str | None
    scope: str | None
    baseline: str | None
    n_cases: int
    cells: dict[str, str] = field(default_factory=dict)


def cell(m: MetricValue) -> str:
    if m.state != MetricState.MEASURED:
        return f"{m.state.value}: {m.reason}"
    assert m.value is not None
    if m.unit == "ratio":
        text = f"{m.value:.3f}"
    elif m.unit == "usd":
        text = f"{m.value:.6f} USD"
    elif m.unit == "ms":
        text = f"{m.value:.2f} ms"
    else:
        text = f"{m.value:g}"
    text += f" (n={m.n}"
    if m.interval is not None:
        text += f", {m.interval.low:.3f}–{m.interval.high:.3f}"
    return text + ")"


def rows(
    runs: Sequence[tuple[RunManifest, EvaluationResult]],
    stratum: tuple[tuple[str, str], ...] = (),
) -> list[ComparisonRow]:
    out: dict[tuple, ComparisonRow] = {}
    for manifest, result in runs:
        for s in result.results:
            if tuple((k.dimension, k.value) for k in s.stratum) != stratum:
                continue
            for m in s.metrics:
                key = (result.run_id, m.key_variant, m.scope, m.baseline)
                row = out.setdefault(
                    key,
                    ComparisonRow(
                        experiment_id=result.experiment_id,
                        run_id=result.run_id,
                        source=result.counterfactual_source.value,
                        composition=manifest.prompt_composition_assumption,
                        data_hash=manifest.data_hash,
                        config_hash=manifest.versions.config_hash,
                        key_id=manifest.versions.fingerprint_key_id,
                        key_variant=m.key_variant,
                        scope=m.scope,
                        baseline=m.baseline,
                        n_cases=s.n_cases,
                    ),
                )
                row.cells[m.name.value] = cell(m)
    return list(out.values())


def markdown(
    table: Sequence[ComparisonRow], metrics: Sequence[str] | None = None
) -> str:
    names = list(metrics or dict.fromkeys(n for r in table for n in r.cells))
    head = [
        "experiment",
        "run",
        "source",
        "variant",
        "scope",
        "baseline",
        "cases",
        *names,
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in table:
        values = [
            r.experiment_id,
            r.run_id,
            r.source,
            r.key_variant or "—",
            r.scope or "—",
            r.baseline or "—",
            str(r.n_cases),
            *(r.cells.get(n, "") for n in names),
        ]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"
