"""The benchmark pilot through the evaluation framework (E1, E4, E5, E6).

The pilot answered through E4's harness, but its ``RunResult`` was not kept, so
nothing could feed the framework's comparison. This module **rebuilds the
answering run from the recordings** (each recorded live answer becomes an E4
``CallRecord`` through E4's own record builder, with cost from the reported usage
and the price table) and gives it to the framework's ``comparison_table``: one
row per language (Persian first) and model with n, error share, cost, latency
and quality as separate columns, no combined score. Quality comes from each
judge's pairwise scores (E5), **one table per judge, never merged**, marked
``estimated`` and not validated unless that language's Persian gate says
``validated`` (``agreement`` module).

What is rebuilt is stated in the report (``reconstructed``): the run's caps,
retries and stop rules are not those of the original run. Judge calls and
records not made live are never answers. Content-free: model names, counts and
statistics only. Pure given its inputs.
Traces: FR-EVAL-04, FR-EVAL-05, ADR-0053. Status: provisional.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from pydantic import TypeAdapter

from metis_auto.contracts import (
    AnswerSource,
    CatalogueEntry,
    ModelInvocation,
    ModelResult,
    PriceTable,
)
from metis_auto.evaluation.reporting.render import to_plain
from metis_auto.evaluation.sampling.allocation import SamplingUnit
from metis_auto.evaluation.sampling.runner import (
    CallRecord,
    PlannedCall,
    RunEstimate,
    RunResult,
    call_record,
)
from metis_auto.evaluation.sampling.tables import (
    BootstrapSettings,
    Key,
    comparison_table,
)

FORMAT_VERSION = "benchmark-framework-report-v1"
_RESULT = TypeAdapter(ModelResult)
FRAMEWORK_LANGUAGE = {"persian": "fa", "english": "en"}
"""The golden set's language groups → the framework's language codes
(``Language``); other groups keep their own name."""
RECONSTRUCTED = "reconstructed_from_recordings"


def _made_live(record: Mapping[str, Any], result: Any) -> bool:
    """The replay client's rule: the recorder's ``client_source`` marker, else
    the result's own source."""
    marker = record.get("client_source")
    if marker is not None:
        return marker == AnswerSource.LIVE.value
    return getattr(result, "source", None) == AnswerSource.LIVE


def _rank(record: CallRecord) -> int:
    if record.outcome == "response":
        return 2 if record.finish_reason == "complete" else 1
    return 0


def recorded_run(
    records: Sequence[Mapping[str, Any]],
    *,
    case_ids: Sequence[str],
    arms: Sequence[str],
    catalogue: Mapping[str, CatalogueEntry],
    prices: PriceTable,
) -> RunResult:
    """The answers in ``records`` (a recording file's lines) as an E4 run. Per
    (case, arm) the best record wins (a complete answer over a partial one over
    an error; later over earlier). Judge calls and records not made live are
    skipped."""
    wanted = set(case_ids)
    best: dict[tuple[str, str], CallRecord] = {}
    for rec in records:
        invocation = ModelInvocation.model_validate(rec["invocation"])
        if ".judge." in invocation.request_id:
            continue
        if invocation.model_id not in arms or invocation.case_id not in wanted:
            continue
        result = _RESULT.validate_python(rec["result"])
        if not _made_live(rec, result):
            continue
        call = PlannedCall(
            invocation.case_id, invocation.case_id, invocation.model_id, None, 0
        )
        entry = catalogue[invocation.model_id]
        built = call_record(call, AnswerSource.LIVE, result, 0.0, entry, prices)
        key = (call.case_id, call.model_id)
        if key not in best or _rank(built) >= _rank(best[key]):
            best[key] = built
    ordered = tuple(best[k] for k in sorted(best))
    planned = len(wanted) * len(arms)
    realized = sum((r.cost_usd for r in ordered if r.cost_usd is not None), Decimal(0))
    return RunResult(
        records=ordered,
        halts=(),
        planned_calls=planned,
        executed_calls=len(ordered),
        skipped_calls=planned - len(ordered),
        realized_usd=realized,
        unreported_cost_calls=sum(
            1 for r in ordered if r.outcome == "response" and r.cost_usd is None
        ),
        charged_usd=realized,
        cap_usd=Decimal(0),
        estimate=RunEstimate(
            calls=planned,
            lower_bound_usd=None,
            assumed_usd=None,
            ceiling_usd=None,
            reasons={"all": RECONSTRUCTED},
        ),
        stop_rules={"source": RECONSTRUCTED},
        sources=("recorded",),
    )


def framework_report(
    run: RunResult,
    scores_by_judge: Mapping[str, Mapping[tuple[str, str], float]],
    languages: Mapping[str, str],
    *,
    min_n: int | None,
    bootstrap: BootstrapSettings | None,
    gate: Mapping[str, str] | None,
    run_id: str,
    families: Mapping[str, str] | None = None,
    current_judges: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The framework's comparison table per judge. ``scores_by_judge``: judge ID
    → ``(case, model)`` → pairwise score. ``languages``: case → language group.
    ``gate``: framework language code → ``validated`` / ``unvalidated`` /
    ``not_configured`` (default ``not_configured``); a language is marked
    validated only when its gate says so. ``families``: model ID → provider
    family (judges and arms); with it the report adds ``self_preference`` (see
    ``split_by_family``), over ``current_judges`` only."""
    units = {
        r.case_id: SamplingUnit(
            r.case_id,
            r.session_ref,
            {
                "language": FRAMEWORK_LANGUAGE.get(
                    languages.get(r.case_id, "unknown"),
                    languages.get(r.case_id, "unknown"),
                )
            },
        )
        for r in run.records
    }
    present = sorted({u.strata["language"] for u in units.values()})
    given = dict(gate or {})
    judge_gate = {lang: given.get(lang, "not_configured") for lang in present}
    tables: dict[str, Any] = {}
    for judge, scores in sorted(scores_by_judge.items()):
        quality: dict[Key, float] = {
            (case, model, None): score for (case, model), score in scores.items()
        }
        rows = []
        for validated in (False, True):
            if validated and "validated" not in judge_gate.values():
                continue
            table = comparison_table(
                run,
                units,
                min_n=min_n,
                boot=bootstrap,
                quality_by_call=quality,
                quality_validated=validated,
            )
            rows.append(
                {
                    (r.language, r.model_id, r.effort): r
                    for r in table
                    if (judge_gate.get(r.language) == "validated") == validated
                }
            )
        merged = {k: v for part in rows for k, v in part.items()}
        order = list(
            comparison_table(
                run, units, min_n=min_n, boot=bootstrap, quality_by_call=quality
            )
        )
        tables[judge] = {
            "rows": [
                to_plain(merged[(r.language, r.model_id, r.effort)]) for r in order
            ]
        }
    report = {
        "format": FORMAT_VERSION,
        "run_id": run_id,
        "reconstructed": True,
        "run": {
            "planned_calls": run.planned_calls,
            "executed_calls": run.executed_calls,
            "skipped_calls": run.skipped_calls,
            "realized_usd": str(run.realized_usd),
            "unreported_cost_calls": run.unreported_cost_calls,
        },
        "min_n": min_n,
        "judge_gate": judge_gate,
        "tables": tables,
    }
    if families is not None:
        report["self_preference"] = split_by_family(
            tables, families, current_judges or tuple(tables)
        )
    return report


def split_by_family(
    tables: Mapping[str, Any],
    families: Mapping[str, str],
    judges: Sequence[str],
) -> dict[str, Any]:
    """Self-preference handling (ADR-0053 amendment 5): a judge may favour an
    answer from its own provider family. Every (judge, language, arm) row of the
    per-judge tables goes to ``same_family`` when the judge's family equals the
    arm's, else to ``headline``. The headline of an arm is therefore its score
    **without its own family's judge**; the same-family rows are reported apart
    and are never averaged into it. Judges outside ``judges`` (an earlier judge
    version) are left out of both. An unknown family counts as not the same
    (stated in ``unknown_family``)."""
    headline, same, unknown = [], [], set()
    for judge in judges:
        if judge not in tables:
            continue
        for row in tables[judge]["rows"]:
            fam_j, fam_a = families.get(judge), families.get(row["model_id"])
            if fam_j is None or fam_a is None:
                unknown.add(judge if fam_j is None else row["model_id"])
            entry = {"judge": judge, "judge_family": fam_j, "arm_family": fam_a, **row}
            (same if fam_j is not None and fam_j == fam_a else headline).append(entry)
    return {
        "headline": headline,
        "same_family": same,
        "judges": list(judges),
        "unknown_family": sorted(unknown),
    }


def _est(e: Mapping[str, Any]) -> str:
    if e["state"] != "measured" or e["value"] is None:
        return f"— ({e['state']}: {e['reason']})"
    text = f"{e['value']:.4g}"
    if e["interval"] is not None:
        text += f" [{e['interval'][0]:.4g}, {e['interval'][1]:.4g}]"
    return f"{text} (n={e['n']})"


def to_markdown(report: Mapping[str, Any]) -> str:
    run = report["run"]
    lines = [
        f"# Framework report: {report['run_id']}",
        "",
        "The answering run was **reconstructed from the recordings** (not the "
        "original run's caps or stop rules): "
        f"{run['executed_calls']} of {run['planned_calls']} planned answers, "
        f"realised cost {run['realized_usd']} USD. One table per judge; quality "
        "is the judge's pairwise score against the reference (1 win, 0.5 tie, "
        "0 loss), **not validated** unless the language's gate says validated. "
        "There is no combined score.",
        "",
        "Judge gate by language: "
        + ", ".join(f"{k}: {v}" for k, v in report["judge_gate"].items()),
    ]
    for judge, table in report["tables"].items():
        lines += [
            "",
            f"## Judge {judge}",
            "",
            "| language | model | answered / calls | error share | cost mean USD "
            "| latency ms | quality | label |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in table["rows"]:
            share = "—" if r["error_share"] is None else f"{r['error_share']:.2f}"
            lines.append(
                f"| {r['language']} | {r['model_id']} | {r['n_answered']} / "
                f"{r['n_calls']} | {share} | {_est(r['cost_mean_usd'])} | "
                f"{_est(r['latency_total_ms'])} | {_est(r['quality'])} | "
                f"{r['label']} |"
            )
    sp = report.get("self_preference")
    if sp is not None:
        head = "| language | model | judge | quality |\n|---|---|---|---|"
        lines += [
            "",
            "## Self-preference: headline (judge from another family than the arm)",
            "",
            "A judge may favour answers of its own provider family. The headline "
            "of an arm leaves out its own family's judge; same-family rows follow "
            "apart and are not averaged into it. Current judges: "
            + ", ".join(sp["judges"])
            + ".",
            "",
            head,
        ]
        lines += [
            f"| {r['language']} | {r['model_id']} | {r['judge']} | "
            f"{_est(r['quality'])} |"
            for r in sp["headline"]
        ]
        lines += [
            "",
            "## Same-family pairs (judge family equals arm family; not the headline)",
            "",
            head,
        ]
        lines += [
            f"| {r['language']} | {r['model_id']} | {r['judge']} | "
            f"{_est(r['quality'])} |"
            for r in sp["same_family"]
        ]
    return "\n".join(lines) + "\n"
