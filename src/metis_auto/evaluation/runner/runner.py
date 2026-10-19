"""Experiment runner (CMP-24; evaluation.md §1–§2, docs/experiments/framework.md).

Responsibility: run one experiment config over a dataset slice against the
baselines, and write under ``runs/<EXP-ID>/<run-id>/``:
- ``manifest.json``: the ``RunManifest`` (built by wiring: code version,
  data hash, seed, versions and key ID, source, assumptions, hardware);
- ``events.jsonl``: every event of the run, the single measurement record
  (ADR-0012): ``run_started``, per-case ``evaluation_scored`` baseline costs,
  the runner kind's own events, ``run_finished``;
- ``results.json``: the ``EvaluationResult``, computed **from those events**;
- ``extras.json``: content-free counts that are not metrics (pairing and
  label-resolution counts; for cache-candidate runs the per-variant table,
  lexical repeat groups, and the lexical answer-match signal).

Two runner kinds (``experiment.kind``), one result format:
- ``pipeline_replay``: each admitted case through a candidate
  ``RequestPipeline`` built by wiring's factory (it never imports wiring);
- ``cache_candidates``: the ``CandidateHarness`` with the configured index.
The as-logged baseline is mandatory and computed from the cases; the premium
baseline is the brief §5 estimate (never a call).
Called by: scripts/run_experiment.py via ``wiring.experiments``.
Calls: evaluation.replay, .baselines, .metrics, .cache_candidates.
Status: minimal (Stage 8): no parallelism, no resume; a run is cheap to redo.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from metis_auto.application.accounting import AccountingService
from metis_auto.application.events import EventRecorder
from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.application.pipeline import RequestPipeline
from metis_auto.contracts import (
    Cost,
    CostStatus,
    EvaluationResult,
    Event,
    ExclusionCount,
    MetricName,
    MetricState,
    MetricValue,
    PairingFlag,
    PriceTable,
    ReplayCase,
    RunManifest,
    RunMode,
    Versions,
)
from metis_auto.contracts.events import EvaluationScored, RunFinished, RunStarted
from metis_auto.ports import Clock, EventSink, IdSource
from metis_auto.settings import ExperimentKind, ExperimentSettings, LabelMapping

from .. import metrics
from ..baselines import as_logged_cost, premium_cost
from ..cache_candidates import CandidateHarness, IndexFactory, order_cases
from ..replay import replay

PipelineFactory = Callable[[EventSink, IdSource], RequestPipeline]


class _Tee:
    """Events to the run's file sink and to memory, so metrics are computed
    from exactly the events that were written."""

    def __init__(self, sink: EventSink) -> None:
        self.events: list[Event] = []
        self._sink = sink

    def emit(self, event: Event) -> None:
        self._sink.emit(event)
        self.events.append(event)


@dataclass
class RunSetup:
    """Everything a run needs, built by ``wiring.experiments``."""

    experiment: ExperimentSettings
    manifest: RunManifest
    run_dir: Path
    sink: EventSink
    clock: Clock
    ids: IdSource
    versions: Versions
    run_mode: RunMode
    accounting: AccountingService
    prices: PriceTable
    label_mapping: LabelMapping
    premium_model_id: str | None
    fingerprinter: Fingerprinter
    measurement: MeasurementService
    pipeline_factory: PipelineFactory | None = None
    index_factory: IndexFactory | None = None
    strategy_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunOutputs:
    result: EvaluationResult
    run_dir: Path
    extras: dict[str, Any]


def _cost_metric(baseline: str, cost: Cost) -> MetricValue:
    if cost.status == CostStatus.COMPUTED:
        assert cost.amount is not None
        return MetricValue(
            name=MetricName.COST_PER_REQUEST,
            state=MetricState.MEASURED,
            value=float(cost.amount.amount),
            unit="usd",
            n=1,
            baseline=baseline,
            token_fidelity=cost.token_fidelity,
            price_table_version=cost.price_table_version,
        )
    return MetricValue(
        name=MetricName.COST_PER_REQUEST,
        state=MetricState.NOT_COMPUTED,
        n=1,
        baseline=baseline,
        reason=cost.reason.value if cost.reason else "not_computed",
    )


def admit(
    cases: Sequence[ReplayCase], flags: Sequence[str]
) -> tuple[list[ReplayCase], list[ExclusionCount]]:
    """Cases whose pairing flag the run admits; the rest are exclusions."""
    allowed = {PairingFlag(f) for f in flags}
    kept = [c for c in cases if c.pairing_flag in allowed]
    dropped = Counter(
        c.pairing_flag.value for c in cases if c.pairing_flag not in allowed
    )
    return kept, [
        ExclusionCount(reason=f"flag_{r}", count=n) for r, n in sorted(dropped.items())
    ]


class ExperimentRunner:
    def __init__(self, setup: RunSetup) -> None:
        self._s = setup

    def run(
        self, cases: Sequence[ReplayCase], exclusions: Sequence[ExclusionCount] = ()
    ) -> RunOutputs:
        s, exp = self._s, self._s.experiment
        assert exp.id is not None, "the runner needs experiment.id"
        s.run_dir.mkdir(parents=True, exist_ok=True)
        (s.run_dir / "manifest.json").write_text(
            s.manifest.model_dump_json(indent=2) + "\n"
        )
        tee = _Tee(s.sink)
        recorder = EventRecorder(
            tee, s.clock, s.ids, s.manifest.run_id, s.run_mode, s.versions
        )
        recorder.emit(RunStarted(experiment_id=exp.id, manifest_ref="manifest.json"))

        admitted, dropped = admit(cases, exp.data.pairing_flags)
        ordered = order_cases(admitted, exp.data.ordering)
        all_exclusions = [*exclusions, *dropped]
        labels = self._baselines(ordered, recorder)

        extras: dict[str, Any] = {
            "pairing_flags": dict(Counter(c.pairing_flag.value for c in cases)),
            "label_resolution": labels,
        }
        if exp.kind == ExperimentKind.CACHE_CANDIDATES:
            assert s.index_factory is not None
            harness = CandidateHarness(
                s.fingerprinter,
                s.measurement,
                recorder,
                s.index_factory,
                s.strategy_params,
            )
            run = harness.run(ordered)
            extras |= {
                "variants": list(run.variants),
                "lexical_repeats": run.repeats,
                "lexical_answer_match": run.lexical_answer_match,
            }
            covered = sum(1 for c in ordered if c.references)
        else:
            assert s.pipeline_factory is not None
            pipeline = s.pipeline_factory(tee, s.ids)
            outcomes = replay(ordered, pipeline)
            covered = sum(1 for o in outcomes if o.response.answer is not None)

        recorder.emit(
            RunFinished(
                cases_total=len(cases),
                cases_run=len(ordered),
                exclusions=tuple(all_exclusions),
                completed=True,
            )
        )
        result = self._aggregate(tee.events, ordered, covered, all_exclusions, extras)
        (s.run_dir / "results.json").write_text(result.model_dump_json(indent=2) + "\n")
        (s.run_dir / "extras.json").write_text(
            json.dumps(extras, indent=2, sort_keys=True) + "\n"
        )
        return RunOutputs(result=result, run_dir=s.run_dir, extras=extras)

    def _baselines(
        self, cases: Sequence[ReplayCase], recorder: EventRecorder
    ) -> dict[str, int]:
        """Per-case as-logged and premium costs as events; label counts."""
        s = self._s
        labels: Counter[str] = Counter()
        for case in cases:
            logged = as_logged_cost(case, s.label_mapping, s.accounting, s.prices)
            labels.update(r.outcome for r in logged.labels)
            scored = [_cost_metric("as_logged", logged.cost)]
            if "premium" in s.experiment.baselines:
                scored.append(
                    _cost_metric(
                        "premium",
                        premium_cost(case, s.premium_model_id, s.accounting, s.prices),
                    )
                )
            recorder.emit(
                EvaluationScored(metrics=tuple(scored)),
                request_id=f"req:{case.case_id}",
                session_ref=case.session_ref,
                case_id=case.case_id,
                logged_timestamp=case.logged_timestamp,
            )
        return dict(sorted(labels.items()))

    def _aggregate(
        self,
        events: Sequence[Event],
        cases: Sequence[ReplayCase],
        covered: int,
        exclusions: Sequence[ExclusionCount],
        extras: dict[str, Any],
    ) -> EvaluationResult:
        exp = self._s.experiment
        baselines = list(exp.baselines)
        costs = metrics.case_costs(events)
        if exp.kind == ExperimentKind.CACHE_CANDIDATES:
            found = metrics.lookups(events)
            extras["variant_table"] = metrics.variant_table(
                found, {c.case_id: c.session_ref for c in cases}
            )

            def per_stratum(ids: Sequence[str]) -> list[MetricValue]:
                return metrics.baseline_metrics(
                    ids, costs, baselines
                ) + metrics.cache_metrics(ids, found, costs.get("as_logged", {}))
        else:
            responses = {
                e.case_id: e
                for e in events
                if e.event_type == "response_returned" and e.case_id
            }

            def per_stratum(ids: Sequence[str]) -> list[MetricValue]:
                return metrics.baseline_metrics(
                    ids, costs, baselines
                ) + metrics.pipeline_metrics(
                    ids,
                    responses,
                    costs,
                    baselines,
                    self._s.manifest.counterfactual_source,
                )

        return metrics.result(
            run_id=self._s.manifest.run_id,
            experiment_id=exp.id or "",
            source=self._s.manifest.counterfactual_source,
            cases=cases,
            covered=covered,
            baselines=baselines,
            exclusions=exclusions,
            per_stratum=per_stratum,
            declared=exp.metrics,
        )
