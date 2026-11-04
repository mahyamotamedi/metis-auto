"""The framework's rules applied to the pipelines' lever results (E6; FR-EVAL-04,
FR-EVAL-05, the final plan's "Decision rules").

The three pipelines write one ``LeverResult`` per step version and baseline
(``analysis``): a saving with a session-clustered interval, slices and an
evidence class. They carry no quality measure, so this module gives each result
the framework's reading of it, using **only what the file holds**:

- the saving share (total saving over the baseline's total) with its interval,
  its provenance (the evidence class mapped to the framework's measured /
  estimated / simulated) and its units (recorded, repriced, estimate only);
  a point value without an interval makes no claim;
- the Persian slice (``lang:fa``) as its own line, never folded into the total;
- the quality side: ``not_measured``, ``sampled`` (n reviewed) or ``measured``;
- the plan's decision rule for the step: **context** needs the paid quality
  ablation, **routing** needs judge-corrected acceptable rates, an **answer
  cache** needs about 300 reviewed hits with no error, a **retrieval cache**
  needs agreement of 0.9 or more. When the evidence for a rule is not in the
  file the outcome is ``not_evaluated`` with the reason; a rule that cannot be
  passed on the data says ``cannot_pass`` and why. Nothing passes by default.

Results in different scopes (rows, price version, evidence class, baseline) are
listed in separate comparable groups and never ranked across them. Pure: plain
mappings in, content-free data out (the evaluation layer does not import
``analysis``; ``wiring`` reads the files). Status: provisional.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from metis_auto.evaluation.comparison.types import Estimate, not_measured

from .render import to_plain

FORMAT_VERSION = "lever-evaluation-v1"
STEPS = ("cache", "context", "routing")
PROVENANCE_OF_EVIDENCE = {
    "observed": "measured",
    "metadata-derived": "estimated",
    "heuristic": "estimated",
    "hypothetical reconstruction": "simulated",
    "simulation": "simulated",
}
UNITS_OF_BASELINE = {
    "as_logged": "recorded",
    "premium_gpt_5_5": "estimate_only",
}
DEFAULT_CACHE_KINDS = {
    "cache.popular_question": "answer",
    "retrieval_result_cache": "retrieval",
    "cache.session_memo_gate": "retrieval",
}
"""Version-name prefix → cache kind. The kind decides the rule; an unknown
version is not guessed."""
DEFAULT_MIN_REVIEWED = 300
"""The plan: "about 300 reviewed hits with no errors" for an answer cache."""
DECISION_RULES = {
    "cache": "Retrieval versions: agreement with the later real lookup >= 0.9. "
    "Answer versions: answer error <= 1%, which needs about 300 reviewed hits "
    "with no errors; with fewer the result stays a candidate.",
    "context": "Pass only with the paid quality ablation (loss minus win within "
    "the noise + 3 points, no language group more than 10 points worse, JSON "
    "validity, reply language and refusal rate not worse); without it the "
    "result is tokens only, quality not measured.",
    "routing": "Move a bot only if its acceptable rate is within 10 points of "
    "the incumbent (lower 95% bound, judge-corrected) and its cost is lower; "
    "keep a more complex router only if it beats per-bot reassignment outside "
    "the interval. Without quality labels no version can pass.",
}
SOURCE = "docs/superpowers/plans/2026-11-01-final-plan.md, Decision rules"
PIPELINES = ("A", "B", "C", "unassigned")
DEFAULT_PIPELINE_PREFIXES = {
    "cache.popular_question": "A",
    "context.reranker_cut": "A",
    "route.per_bot": "A",
    "retrieval_result_cache": "B",
    "cross_turn_chunks": "B",
    "route.knn": "B",
    "cache.session_memo_gate": "C",
    "ctx.within_message_dedup": "C",
    "ctx.history_budget": "C",
    "route.small_classifier": "C",
}
"""Version-name prefix → pipeline (sprint_decisions.md: A popular-question cache,
reranker cut, per-bot reassignment; B retrieval cache, cross-turn chunks, kNN
router; C session memo, within-message dedup and history budget, small
classifier). A version that matches none is ``unassigned``, never guessed."""
BLOCKERS = {
    "tokens_only_quality_not_measured": (
        "needs the paid quality ablation (cut-first d); until then tokens only"
    ),
    "cost_only_quality_not_proven": (
        "needs judge-corrected acceptable rates per bot (benchmark labels); "
        "until then cost only"
    ),
    "quality_comparison_not_in_result": "the win and loss rates are not in the result",
    "acceptable_rate_not_in_result": "the acceptable rates are not in the result",
    "retrieval_agreement_not_in_result": (
        "needs the retrieval agreement (0.9 or more) in the result file"
    ),
    "answer_error_rate_not_in_result": (
        "needs the reviewed answer-error count in the result file"
    ),
    "cache_kind_unknown": "the cache kind is unknown, so its rule cannot be applied",
    "no_hits_reviewed": "needs about {min} reviewed hits with no errors; none reviewed",
}


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _total(block: Mapping[str, Any]) -> Decimal | None:
    """The block's ``total``, else the sum of its parts (the comparison's rule)."""
    if "total" in block:
        return _decimal(block["total"])
    parts = [_decimal(v) for v in block.values()]
    return None if not parts or None in parts else sum(parts, Decimal(0))  # type: ignore[arg-type]


def _saving_share(res: Mapping[str, Any], provenance: str) -> dict[str, Any]:
    n = int(res["n_requests"])
    base, saved = _total(res["baseline_cost"]), _total(res["saving"])
    if base is None or saved is None:
        est = not_measured("not_evaluated", "cost_not_in_result", n, provenance)
    elif base == 0:
        est = not_measured("not_evaluated", "baseline_cost_zero", n, provenance)
    else:
        low, high = res.get("ci_low"), res.get("ci_high")
        est = Estimate(
            "measured",
            n,
            provenance,
            value=float(saved / base),
            interval=(low, high) if low is not None and high is not None else None,
            method="session_clustered_interval",
        )
    plain = to_plain(est)
    plain["claims_allowed"] = est.claims_allowed
    return plain


def _persian(res: Mapping[str, Any]) -> dict[str, Any]:
    fa = res["slices"].get("lang:fa")
    if fa is None:
        return {"state": "not_reported", "saving_share": None, "n_requests": None}
    share = fa.get("saving_share")
    if share is None:
        base, saved = (
            _decimal(fa.get("baseline:total")),
            _decimal(fa.get("saving:total")),
        )
        share = float(saved / base) if base and saved is not None else None
    n = fa.get("n_requests")
    return {
        "state": "reported",
        "saving_share": None if share is None else float(share),
        "n_requests": None if n is None else int(float(n)),
    }


def _quality(state: str) -> dict[str, Any]:
    if state == "unmeasured":
        return {
            "state": "not_measured",
            "reviewed": None,
            "reason": "correctness_unmeasured",
        }
    if state.startswith("sampled:"):
        return {
            "state": "sampled",
            "reviewed": int(state.split(":", 1)[1]),
            "reason": None,
        }
    return {"state": "measured", "reviewed": None, "reason": None}


def _rule(
    step: str,
    version: str,
    quality: Mapping[str, Any],
    cache_kinds: Mapping[str, str],
    min_reviewed: int,
) -> dict[str, str]:
    measured = quality["state"] == "measured"
    if step == "context":
        if not measured:
            return _out("cannot_pass", "tokens_only_quality_not_measured")
        return _out("not_evaluated", "quality_comparison_not_in_result")
    if step == "routing":
        if not measured:
            return _out("cannot_pass", "cost_only_quality_not_proven")
        return _out("not_evaluated", "acceptable_rate_not_in_result")
    kind = next((k for p, k in cache_kinds.items() if version.startswith(p)), None)
    if kind == "retrieval":
        return _out("not_evaluated", "retrieval_agreement_not_in_result")
    if kind != "answer":
        return _out("not_evaluated", "cache_kind_unknown")
    reviewed = quality["reviewed"]
    if measured or (reviewed is not None and reviewed >= min_reviewed):
        return _out("not_evaluated", "answer_error_rate_not_in_result")
    if reviewed is None:
        return _out("candidate", "no_hits_reviewed")
    return _out("candidate", f"reviewed_{reviewed}_below_{min_reviewed}")


def _out(outcome: str, reason: str) -> dict[str, str]:
    return {"outcome": outcome, "reason": reason}


def _row(
    res: Mapping[str, Any], cache_kinds: Mapping[str, str], min_reviewed: int
) -> dict[str, Any]:
    provenance = PROVENANCE_OF_EVIDENCE.get(res["evidence_class"], "simulated")
    quality = _quality(res["correctness_state"])
    return {
        "lever_id": res["lever_id"],
        "version": res["version"],
        "baseline": res["baseline"],
        "units": UNITS_OF_BASELINE.get(res["baseline"], "repriced"),
        "n_requests": res["n_requests"],
        "n_eligible": res["n_eligible"],
        "evidence_class": res["evidence_class"],
        "price_version": res.get("manifest", {}).get("price_version"),
        "saving_share": _saving_share(res, provenance),
        "persian": _persian(res),
        "quality": quality,
        "rule": _rule(res["step"], res["version"], quality, cache_kinds, min_reviewed),
        "overhead_ms_p95": res.get("overhead_ms_p95"),
    }


def _groups(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        key = (r["baseline"], r["n_requests"], r["price_version"], r["evidence_class"])
        group = out.setdefault(
            key,
            {
                "baseline": r["baseline"],
                "n_requests": r["n_requests"],
                "price_version": r["price_version"],
                "evidence_class": r["evidence_class"],
                "versions": [],
            },
        )
        group["versions"].append(r["version"])
    return list(out.values())


def _blocker(reason: str, min_reviewed: int) -> str:
    if reason.startswith("reviewed_"):
        n = reason.split("_")[1]
        return f"needs about {min_reviewed} reviewed hits with no errors; {n} reviewed"
    return BLOCKERS.get(reason, reason).replace("{min}", str(min_reviewed))


def _pipeline_of(version: str, prefixes: Mapping[str, str]) -> str:
    return next(
        (p for pre, p in prefixes.items() if version.startswith(pre)), "unassigned"
    )


def _summarise(rows: Sequence[Mapping[str, Any]], min_reviewed: int) -> dict[str, Any]:
    logged = [
        r
        for r in rows
        if r["baseline"] == "as_logged" and r["saving_share"]["state"] == "measured"
    ]
    best = max(logged, key=lambda r: r["saving_share"]["value"], default=None)
    values = [r["saving_share"]["value"] for r in logged]
    blockers: list[str] = []
    for r in rows:
        text = _blocker(r["rule"]["reason"], min_reviewed)
        if text not in blockers:
            blockers.append(text)
    return {
        "variants": len({r["version"] for r in rows}),
        "results": len(rows),
        "headline": None
        if best is None
        else {
            "version": best["version"],
            "saving_share": best["saving_share"],
            "persian": best["persian"],
            "is_pick": False,
        },
        "saving_range": [min(values), max(values)] if values else None,
        "without_interval": sum(
            1 for r in rows if not r["saving_share"]["claims_allowed"]
        ),
        "persian_reported": sum(1 for r in rows if r["persian"]["state"] == "reported"),
        "outcomes": dict(sorted(Counter(r["rule"]["outcome"] for r in rows).items())),
        "can_pass": any(r["rule"]["outcome"] == "pass" for r in rows),
        "blocked_by": blockers,
    }


def evaluate_levers(
    results: Sequence[Mapping[str, Any]],
    *,
    min_reviewed: int = DEFAULT_MIN_REVIEWED,
    cache_kinds: Mapping[str, str] | None = None,
    pipeline_prefixes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """``results``: ``LeverResult`` data as plain mappings (``model_dump`` in
    JSON mode). One block per step with its rows, the versions that could be
    picked (none unless a rule is passed on the file's own evidence) and the
    comparable groups."""
    kinds = DEFAULT_CACHE_KINDS if cache_kinds is None else cache_kinds
    steps: dict[str, Any] = {}
    for step in STEPS:
        rows = [_row(r, kinds, min_reviewed) for r in results if r["step"] == step]
        rows.sort(
            key=lambda r: (
                r["baseline"],
                -(r["saving_share"]["value"] or 0.0),
                r["version"],
            )
        )
        pickable = [r for r in rows if r["rule"]["outcome"] == "pass"]
        picked = max(
            pickable, key=lambda r: r["saving_share"]["value"] or 0.0, default=None
        )
        steps[step] = {
            "rule": DECISION_RULES[step],
            "results": rows,
            "pickable": [r["lever_id"] for r in pickable],
            "picked": None if picked is None else picked["lever_id"],
            "comparable_groups": _groups(rows),
        }
    prefixes = (
        DEFAULT_PIPELINE_PREFIXES if pipeline_prefixes is None else pipeline_prefixes
    )
    pipelines: dict[str, Any] = {
        name: {
            step: _summarise(
                [
                    r
                    for r in steps[step]["results"]
                    if _pipeline_of(r["version"], prefixes) == name
                ],
                min_reviewed,
            )
            for step in STEPS
        }
        for name in PIPELINES
    }
    return {
        "format": FORMAT_VERSION,
        "n_results": len(results),
        "pipelines": pipelines,
        "decision_rules": {"source": SOURCE, **DECISION_RULES},
        "steps": steps,
    }


def _pct(est: Mapping[str, Any]) -> str:
    if est["state"] != "measured" or est["value"] is None:
        return f"— ({est['reason']})"
    text = f"{est['value'] * 100:.2f}%"
    if est["interval"] is not None:
        text += f" [{est['interval'][0] * 100:.2f}, {est['interval'][1] * 100:.2f}]"
    return text


def _pipeline_summary(pipelines: Mapping[str, Any]) -> list[str]:
    lines = [
        "",
        "# Summary by pipeline",
        "",
        "For each pipeline and step: how many variants were tried, the largest "
        "saving against the recorded cost (a headline, **not a pick**), whether "
        "the framework's rule can be passed on these files, and what is blocking "
        "it. Detail per step and baseline follows.",
    ]
    for name, steps in pipelines.items():
        if not any(s["variants"] for s in steps.values()):
            continue
        title = (
            "Unassigned (version not matched to a pipeline)"
            if name == "unassigned"
            else f"Pipeline {name}"
        )
        lines += [
            "",
            f"## {title}",
            "",
            "| step | variants | largest saving (recorded) | Persian slice "
            "| with an interval | can pass | blocked by |",
            "|---|---|---|---|---|---|---|",
        ]
        for step, s in steps.items():
            if not s["variants"]:
                lines.append(f"| {step} | 0 | — | — | — | — | not tried |")
                continue
            h = s["headline"]
            saving = (
                "— (no recorded-cost result)"
                if h is None
                else f"{_pct(h['saving_share'])} ({h['version']})"
            )
            fa = (
                "—"
                if h is None or h["persian"]["saving_share"] is None
                else f"{h['persian']['saving_share'] * 100:.2f}%"
            )
            with_ci = s["results"] - s["without_interval"]
            intervals = f"{with_ci} of {s['results']} results"
            lines.append(
                f"| {step} | {s['variants']} | {saving} | {fa} | {intervals} | "
                f"{'yes' if s['can_pass'] else 'no'} | "
                + "; ".join(s["blocked_by"])
                + " |"
            )
    return lines


def to_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Lever evaluation by the framework's rules",
        "",
        f"{report['n_results']} results. Every saving is a simulation on logged "
        "requests: **quality is not measured** for any result (no ablation, no "
        "judge-corrected labels), so no context or routing version can pass its "
        "rule. Rules: " + report["decision_rules"]["source"] + ". A saving "
        "without an interval makes no claim; results are not ranked across "
        "different scopes, price versions or evidence classes (see the groups).",
    ]
    lines += _pipeline_summary(report["pipelines"])
    lines += ["", "# Detail by step"]
    for step, block in report["steps"].items():
        lines += [
            "",
            f"## {step}",
            "",
            f"Rule: {block['rule']}",
            "",
            f"Pickable: {', '.join(block['pickable']) or 'none'}. "
            f"Comparable groups: {len(block['comparable_groups'])}.",
        ]
        if not block["results"]:
            lines += ["", "_no results_"]
            continue
        lines += [
            "",
            "| version | baseline | units | requests | saving (interval) "
            "| Persian slice | quality | rule outcome | evidence |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in block["results"]:
            fa = r["persian"]
            fa_text = (
                "not reported"
                if fa["saving_share"] is None
                else f"{fa['saving_share'] * 100:.2f}% (n={fa['n_requests']})"
            )
            q = r["quality"]
            q_text = (
                "not measured"
                if q["state"] == "not_measured"
                else f"{q['state']}" + (f" ({q['reviewed']})" if q["reviewed"] else "")
            )
            lines.append(
                f"| {r['version']} | {r['baseline']} | {r['units']} | "
                f"{r['n_requests']} | {_pct(r['saving_share'])} | {fa_text} | "
                f"{q_text} | {r['rule']['outcome']}: {r['rule']['reason']} | "
                f"{r['evidence_class']} |"
            )
    return "\n".join(lines) + "\n"
