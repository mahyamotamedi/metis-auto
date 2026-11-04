"""The content of ``reports/levers/final.json`` (sprint plan I-2; ADR-0050;
ADR-0061).

Pure: a dict from the combined run's summary, the lever results, F-2's cost
trace and the baseline totals. The caller reads and writes the files.

Rules, each tested on synthetic inputs:

- **The waterfall adds up** per pipeline and baseline: the baseline cost, minus each
  step's combined figure, equals the cost after. A step with no figure in a
  baseline's units has no row and says why ("not computed"), never 0.
- **No share hides the unexplained block.** F-2's ``other`` (cache writes and items
  logged without a cost breakdown, about 12% of all recorded cost, most of it in
  March) is shown with its share for the whole data, the tune period and the
  report period (derived: all minus tune), and stated beside the recorded
  baseline. In price-file units it is "not computed".
- **Units.** Recorded (``as_logged``) and price-file figures are never added; a
  repriced baseline has no fee block.
- **Provisional.** Winners are "provisional: cost only, pending quality".
- **Intervals.** Each result's own session-clustered interval is listed; the
  combined interval is not computed (needs row-level bootstrap of overlapping
  steps).
- Aggregates only: no text, ID or hash (``tests/architecture/
  test_reports_content_free.py``).

Imports ``analysis`` modules only (ADR-0009).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from .lever_result import LeverResult

FORMAT = "final-v1"
STEPS = ("cache", "context", "routing")
BASELINES = ("as_logged", "todays_models", "premium_gpt_5_5", "best_single_cheap")
REQUIRED_SLICES = ("llm_only", "traffic_weighted", "over_8k", "lang:", "tenant_rank:")
UNITS_CAVEAT = (
    "Recorded cost (as_logged, with a fee block) and price-file cost (the other three "
    "baselines, token cost only; fees are not on the price list) are never added. "
    "A step with no figure in a baseline's units is 'not computed', never 0. "
    "Savings of different steps can overlap; each pipeline's combined figure is the "
    "sum of the steps' marginal effects in the order cache, context, routing, with "
    "routing priced on the post-context tokens. Every figure is an offline replay "
    "on logged requests: quality is not measured."
)
OTHER_NOTE = (
    "F-2 'other': cache writes and items logged without a costBreakdown (mostly "
    "March 2026). It is part of token cost (ADR-0050 point 3, owner 2026-11-02), "
    "shown so that no share hides it. Report period = all AI messages minus the "
    "tune period (naive timestamps, Q-06)."
)
OTHER_REPRICED = (
    "not computed in price-file units: those baselines price tokens only, and F-2's "
    "other block is recorded cost"
)
COMBINED_INTERVAL = (
    "not computed: the steps overlap, so a combined interval needs a row-level "
    "bootstrap; each result's own interval is in 'versions'"
)


def _d(value: object) -> Decimal:
    return Decimal(str(value))


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def _scope_blocks(scope: Mapping[str, Any]) -> dict[str, Decimal]:
    return {k: _d(v) for k, v in scope["blocks"].items()}


def cost_blocks(f2: Mapping[str, Any]) -> dict[str, Any]:
    """F-2's blocks for the whole data, the tune period and, derived, the report
    period (all minus tune). Shares are of each scope's total."""
    scopes = f2["scopes"]
    all_s, tune = scopes["all_ai_messages"], scopes["tune"]
    other_keys = ("cache_write", "unbroken_usage", "unbroken_fixed", "unresolved")
    out: dict[str, Any] = {"note": OTHER_NOTE, "scopes": {}}
    pairs = {
        "all_ai_messages": (_d(all_s["total"]), _scope_blocks(all_s)),
        "tune": (_d(tune["total"]), _scope_blocks(tune)),
    }
    a_total, a_blocks = pairs["all_ai_messages"]
    t_total, t_blocks = pairs["tune"]
    pairs["report_derived"] = (
        a_total - t_total,
        {k: a_blocks[k] - t_blocks.get(k, Decimal(0)) for k in a_blocks},
    )
    for name, (total, blocks) in pairs.items():
        other = sum((blocks.get(k, Decimal(0)) for k in other_keys), Decimal(0))
        out["scopes"][name] = {
            "total": _fmt(total),
            "other_total": _fmt(other),
            "other_share": float(other / total) if total > 0 else None,
            "blocks": {k: _fmt(v) for k, v in sorted(blocks.items())},
            "shares": {
                k: (float(v / total) if total > 0 else None)
                for k, v in sorted(blocks.items())
            },
        }
    return out


def _blocks_label(step: str, cells: Mapping[str, Any], baseline: str) -> str:
    """Which recorded cost block a step's saving falls in."""
    if step == "cache":
        if baseline != "as_logged":
            return "token_cost"
        repriced = [
            c.get("steps", {}).get("cache", {})
            for b, c in cells.items()
            if b != baseline
        ]
        retrieval = any(s.get("not_computed") for s in repriced)
        return "fees" if retrieval else "fees+token_cost"
    return "token_cost"


def _waterfall(
    step_cells: Mapping[str, Mapping[str, Any]],
    combined_total: Decimal,
    total: Decimal,
    all_cells: Mapping[str, Any],
    baseline: str,
    versions: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {"kind": "baseline", "label": "baseline cost", "amount": _fmt(total)}
    ]
    for step in STEPS:
        cell = step_cells.get(step)
        if cell is None or cell.get("combined") is None:
            continue
        rows.append(
            {
                "kind": "step",
                "step": step,
                "version": versions.get(step),
                "blocks": _blocks_label(step, all_cells, baseline),
                "amount": cell["combined"],
            }
        )
    rows.append(
        {"kind": "after", "label": "cost after", "amount": _fmt(total - combined_total)}
    )
    return rows


def _role(result: LeverResult, config: Mapping[str, Any]) -> str:
    def named(group: str) -> set[str]:
        return {str(v) for v in config.get(group, {}).values()}

    keys = {result.version, result.lever_id}
    for group, label in (("winners", "winner"), ("runners_up", "runner_up")):
        for ident in named(group):
            if ident in keys or any(k.startswith(ident + ".") for k in keys):
                return label
    return "other"


def _version_row(result: LeverResult, config: Mapping[str, Any]) -> dict[str, Any]:
    llm = result.slices.get("llm_only", {})
    share = llm.get("saving_share")
    names = sorted(result.slices)
    present = {
        req: any(n == req or (req.endswith(":") and n.startswith(req)) for n in names)
        for req in REQUIRED_SLICES
    }
    return {
        "step": result.step,
        "version": result.version,
        "lever_id": result.lever_id,
        "baseline": result.baseline,
        "role": _role(result, config),
        "n_requests": result.n_requests,
        "share": None if share is None or not result.saving else float(share),
        "ci": (
            None
            if result.ci_low is None or result.ci_high is None
            else [result.ci_low, result.ci_high]
        ),
        "correctness_state": result.correctness_state,
        "evidence_class": result.evidence_class,
        "overhead_ms_p50": result.overhead_ms_p50,
        "overhead_ms_p95": result.overhead_ms_p95,
        "slices": names,
        "slices_missing": [k for k, ok in present.items() if not ok],
    }


def build_final(
    summary: Mapping[str, Any],
    results: Sequence[LeverResult],
    f2: Mapping[str, Any],
    baseline_totals: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """The ``final.json`` document (module docstring)."""
    pipelines = summary["pipelines"]
    blocks = cost_blocks(f2)
    other_report = blocks["scopes"]["report_derived"]
    baselines: dict[str, Any] = {}
    for b in BASELINES:
        cells = {
            name: p["baselines"][b]
            for name, p in pipelines.items()
            if b in p["baselines"]
        }
        if not cells:
            continue
        if b not in baseline_totals or "total" not in baseline_totals[b]:
            raise ValueError(f"baseline total missing for {b}")
        total = _d(baseline_totals[b]["total"])
        recorded = b == "as_logged"
        entry: dict[str, Any] = {
            "unit": "recorded" if recorded else "price-file",
            "total": _fmt(total),
            "pipelines": {},
        }
        if recorded:
            entry["fees"] = _fmt(_d(baseline_totals[b]["fees"]))
            entry["token_cost"] = _fmt(_d(baseline_totals[b]["token_cost"]))
            entry["other_block"] = {
                "amount": other_report["other_total"],
                "share": other_report["other_share"],
                "note": OTHER_NOTE,
            }
        else:
            entry["other_block"] = {
                "amount": None,
                "share": None,
                "note": OTHER_REPRICED,
            }
        for name, p in pipelines.items():
            cell = p["baselines"].get(b)
            if cell is None:
                continue
            combined = cell["combined_total"]
            share = None
            if combined is not None and total > 0:
                share = float(_d(combined) / total)
            entry["pipelines"][name] = {
                "versions": p["versions"],
                "steps": cell["steps"],
                "combined_total": combined,
                "standalone_sum": cell["standalone_sum"],
                "sum_rule": cell["sum_rule"],
                "share_of_total": share,
                "interval": None,
                "interval_note": COMBINED_INTERVAL,
                "waterfall": (
                    None
                    if combined is None
                    else _waterfall(
                        cell["steps"],
                        _d(combined),
                        total,
                        {k: v for k, v in p["baselines"].items()},
                        b,
                        p["versions"],
                    )
                ),
                "overlaps": p.get("overlaps"),
                "checks": p.get("checks"),
            }
        baselines[b] = entry
    return {
        "format": FORMAT,
        "status": config["status"],
        "note": config.get("note"),
        "units_caveat": UNITS_CAVEAT,
        "population": summary["population"],
        "cost_blocks": blocks,
        "baselines": baselines,
        "versions": [_version_row(r, config) for r in results],
        "winners": {
            "status": config["status"],
            "versions": dict(config.get("winners", {})),
            "runners_up": dict(config.get("runners_up", {})),
            "note": (
                "Keep every candidate's result: a winner that fails the quality "
                "run is swapped for its runner-up without re-running anything."
            ),
        },
        "skipped": dict(summary.get("skipped", {})),
        "not_run": dict(summary.get("not_run", {})),
    }
