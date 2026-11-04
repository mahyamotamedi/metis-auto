"""I-1, the combined run of the sprint's pipelines (final plan I-1, Review Focus
1; ADR-0031, ADR-0036, ADR-0037; ADR-0061).

One engine for A, B, C, Parham's routing-only run and the provisional winners.
A pipeline is up to three **members** (cache, context, routing); each member
brings its version (for ``levers.combine``) and a ``part`` function: its own
saving, in one baseline's units, on the scored rows. The engine runs

- every member **alone** (the standalone parts),
- all members **combined** (``combine``: cache, then context, then routing, rows
  served from an answer cache skip the later steps); a step's combined part is
  its **marginal** effect in that order, so the parts add up to the combined
  total,

and reports per baseline the standalone part, the combined part, the combined
total and the sum rule (combined <= the compatible standalone sum; equality is
allowed when steps touch different rows or cost blocks).

Rules kept here, each tested on synthetic frames:

- **Units.** Recorded (``as_logged``) and repriced (price-file) figures are never
  added. A step with no figure in a baseline's units is "not computed" there, never
  0 (``unit_cells``, ``sum_parts``): a retrieval cache saves recorded per-call
  fees, which the repriced baselines do not price (ADR-0037 item 7).
- **Routing after context** (the stated assumption, owner question of Stage 4):
  ``combine`` hands routing the frame context returned, whose logged input tokens
  are unchanged, so routing would price the pre-context tokens and overstate the
  combined saving by the rows both steps touch. ``PostContextRouting`` lowers the
  input by the context version's net saved tokens before routing sees it, and the
  routing part is priced on that frame. The shared ``combine`` is not changed.
- **Population.** The scored rows are the report split; ``check_population``
  refuses any other count.
- Output is aggregates only: no text, ID or hash.

Pure over injected frames and members; no I/O. Imports ``analysis`` only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pandas as pd

from metis_auto.analysis.levers import ReplayContext, StepVersion, combine

STEPS = ("cache", "context", "routing")
BASELINES = ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap")
REPRICED = ("premium_gpt_5_5", "todays_models", "best_single_cheap")
NOT_COMPUTED_CACHE = (
    "not computed in these units: a retrieval cache saves recorded per-call fees, "
    "and the repriced baselines have no fee block (ADR-0037 item 7)"
)
INPUT = "a_bill_inputTokens"


def unit_cells(cache_kind: str | None) -> dict[str, dict[str, Any]]:
    """Per baseline: the steps combined in its units and why the others are not
    computed. ``cache_kind``: ``answer_cache`` (token cost, all four baselines),
    ``retrieval_cache`` (recorded fees, ``as_logged`` only) or ``None`` (no cache
    step in the pipeline)."""
    out = {}
    for key in BASELINES:
        steps = [s for s in STEPS if s != "cache" or cache_kind is not None]
        not_computed: dict[str, str] = {}
        if cache_kind == "retrieval_cache" and key != "as_logged":
            steps.remove("cache")
            not_computed["cache"] = NOT_COMPUTED_CACHE
        out[key] = {"combined_steps": tuple(steps), "not_computed": not_computed}
    return out


def sum_parts(
    parts: Mapping[str, Mapping[str, Decimal]], baseline: str
) -> Decimal | None:
    """Sum of the steps' figures in ``baseline``'s units; a step without one is
    left out (not 0). ``None`` when no step has a figure."""
    found = [p[baseline] for p in parts.values() if baseline in p]
    return sum(found, Decimal(0)) if found else None


def sum_rule(combined: Decimal, parts: Sequence[Decimal]) -> dict[str, Any]:
    """Combined must not exceed the compatible standalone sum; equality is
    allowed (steps on different rows or cost blocks). Never forced strict."""
    total = sum(parts, Decimal(0))
    return {
        "combined": str(combined),
        "standalone_sum": str(total),
        "holds": combined <= total,
        "equal": combined == total,
    }


def require_sum_rule(rules: Mapping[str, Mapping[str, Any]]) -> None:
    broken = [k for k, r in rules.items() if not r["holds"]]
    if broken:
        shown = "; ".join(
            f"{k}: combined {rules[k]['combined']} > sum {rules[k]['standalone_sum']}"
            for k in sorted(broken)
        )
        raise ValueError(f"sum rule violated for {', '.join(sorted(broken))} ({shown})")


def post_context_frame(
    req: pd.DataFrame,
    saved_column: str,
    *,
    rates: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """A copy whose logged input tokens are lowered by the context version's net
    saved tokens (unknown saves 0, never below 0).

    With ``rates`` (implied input rate per 1M tokens by logged model) the recorded
    token cost is lowered by the same tokens at that rate, capped at the cost:
    a context version that prices its recorded saving outside ``apply`` leaves
    routing an incumbent at full recorded cost otherwise, and routing would gain
    the context saving. A row whose model has no rate keeps its cost (never 0)."""
    out = req.copy()
    if saved_column in out:
        saved = out[saved_column].fillna(0.0).clip(lower=0.0)
        out[INPUT] = (out[INPUT] - saved).clip(lower=0.0)
        if rates is not None:
            rate = out["bot_provider_model"].map(rates).astype(float)
            cut = (saved * rate / 1e6).clip(upper=out["block_token_cost"])
            out["block_token_cost"] = out["block_token_cost"] - cut.fillna(0.0)
    return out


class PostContextRouting:
    """Wrap a routing version so it prices the post-context input tokens."""

    step = "routing"

    def __init__(self, router: StepVersion, *, saved_column: str) -> None:
        self.router = router
        self.saved_column = saved_column
        self.name = f"{router.name}.post-context"

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        out = self.router.apply(post_context_frame(req, self.saved_column), ctx)
        out[INPUT] = req[INPUT]  # the logged input stays as logged in the output
        return out


def served_rows_untouched(out: pd.DataFrame, columns: Sequence[str]) -> bool:
    """Rows served from an answer cache hold no context or routing result."""
    if "served_from_cache" not in out:
        return True
    served = out["served_from_cache"].fillna(False).astype(bool)
    cols = [c for c in columns if c in out]
    return bool(out.loc[served, cols].isna().all().all()) if cols else True


def check_population(scored: pd.Series, *, expected: int) -> int:
    n = int(scored.sum())
    if n != expected:
        raise ValueError(f"population: {n} scored rows, expected {expected}")
    return n


@dataclass
class Member:
    """One step of a pipeline: its version and its own-effect function."""

    step: str
    name: str
    version: StepVersion
    part: Callable[[pd.DataFrame, pd.DataFrame, str, pd.Series], Decimal | None]
    """``part(frame, out, baseline, rows)``: the saving of this step, in
    ``baseline``'s units, on ``rows``; ``frame`` is what the step saw, ``out`` the
    frame after ``combine``."""
    units: tuple[str, ...] = BASELINES
    kind: str | None = None
    """Cache only: ``answer_cache`` or ``retrieval_cache``."""
    saved_column: str | None = None
    """Context only: net saved input tokens per row (routing then prices less)."""
    recorded_rates: Mapping[str, float] | None = None
    """Context only: implied input rate by model, set when ``apply`` does not lower
    the recorded token cost itself (the engine then lowers it for routing)."""
    touched: Callable[[pd.DataFrame], pd.Series] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _touched(m: Member, out: pd.DataFrame) -> pd.Series:
    if m.touched is not None:
        return m.touched(out).fillna(False).astype(bool)
    if m.step == "cache":
        return out["served_from_cache"].fillna(False).astype(bool)
    if m.step == "context" and m.saved_column:
        return out[m.saved_column].fillna(0) > 0
    return out["route_reason"].eq("moved").fillna(False).astype(bool)


def _overlaps(out: pd.DataFrame, rows: pd.Series, members: Sequence[Member]) -> dict:
    flags = {m.step: _touched(m, out) & rows for m in members}
    result = {s: int(f.sum()) for s, f in flags.items()}
    steps = list(flags)
    for i, a in enumerate(steps):
        for b in steps[i + 1 :]:
            result[f"{a}&{b}"] = int((flags[a] & flags[b]).sum())
    if len(steps) == 3:
        result["all_three"] = int(
            (flags[steps[0]] & flags[steps[1]] & flags[steps[2]]).sum()
        )
    return result


def run_pipeline(
    name: str,
    frame: pd.DataFrame,
    scored: pd.Series,
    members: Sequence[Member],
    ctx: ReplayContext,
    baselines: Sequence[str] = BASELINES,
) -> dict[str, Any]:
    """Run ``members`` alone and combined on ``frame`` (history and scored rows)
    and report on the ``scored`` rows. Aggregates only."""
    by_step = {m.step: m for m in members}
    cache, context, routing = (by_step.get(s) for s in STEPS)
    v = {s: (by_step[s].version if s in by_step else None) for s in STEPS}

    # The pipeline step by step, so each step's part is its marginal effect in the
    # order cache, context, routing (the parts then add up to the combined total):
    # f0 is the frame, f1 after the cache, f2 after context, f3 after routing.
    routing_v = v["routing"]
    if context is not None and routing is not None and context.saved_column:
        routing_v = PostContextRouting(
            routing.version, saved_column=context.saved_column
        )
    f0 = frame
    f1 = combine(f0, v["cache"], None, None, ctx) if cache is not None else f0
    f2 = combine(f0, v["cache"], v["context"], None, ctx) if context is not None else f1
    f3 = combine(f0, v["cache"], v["context"], routing_v, ctx)
    combined = f3
    # what routing saw: the frame after context, with the input tokens lowered
    routing_in = f2
    if context is not None and context.saved_column:
        routing_in = post_context_frame(
            f2, context.saved_column, rates=context.recorded_rates
        )
    seen_by = {"cache": (f0, f1), "context": (f1, f2), "routing": (routing_in, f3)}

    def alone(m: Member) -> pd.DataFrame:
        only = {s: (m.version if s == m.step else None) for s in STEPS}
        return combine(f0, only["cache"], only["context"], only["routing"], ctx)

    rows = scored.reindex(frame.index, fill_value=False)
    parts_alone: dict[str, dict[str, Decimal]] = {}
    parts_comb: dict[str, dict[str, Decimal]] = {}
    for m in members:
        out_alone = alone(m)
        before, after = seen_by[m.step]
        parts_alone[m.step], parts_comb[m.step] = {}, {}
        for b in baselines:
            if b not in m.units:
                continue
            a = m.part(f0, out_alone, b, rows)
            c = m.part(before, after, b, rows)
            if a is not None:
                parts_alone[m.step][b] = a
            if c is not None:
                parts_comb[m.step][b] = c

    kind = cache.kind if cache is not None else None
    cells = unit_cells(kind)
    out_baselines: dict[str, Any] = {}
    for b in baselines:
        steps = {}
        for m in members:
            steps[m.step] = {
                "alone": _s(parts_alone[m.step].get(b)),
                "combined": _s(parts_comb[m.step].get(b)),
            }
            if m.step in cells[b]["not_computed"]:
                steps[m.step]["not_computed"] = cells[b]["not_computed"][m.step]
        total = sum_parts(parts_comb, b)
        alone_sum = sum_parts(parts_alone, b)
        rule = None
        if total is not None and alone_sum is not None:
            compat = [p[b] for p in parts_alone.values() if b in p]
            rule = sum_rule(total, compat)
        out_baselines[b] = {
            "steps": steps,
            "combined_total": _s(total),
            "standalone_sum": _s(alone_sum),
            "sum_rule": rule,
        }
    saved_cols = [m.saved_column for m in members if m.saved_column]
    checks = {
        "served_rows_untouched": served_rows_untouched(
            combined, [*saved_cols, "route_reason"]
        ),
    }
    if (
        cache is not None
        and cache.kind == "retrieval_cache"
        and "retrieval_reused" in combined
    ):
        reused = (
            combined["retrieval_reused"].astype("boolean").fillna(False).astype(bool)
        )
        checks["retrieval_rows_not_served"] = not bool(
            combined["served_from_cache"].fillna(False).astype(bool)[reused].any()
        )
    return {
        "pipeline": name,
        "versions": {m.step: m.name for m in members},
        "units": unit_cells(kind),
        "n_scored": int(rows.sum()),
        "baselines": out_baselines,
        "overlaps": _overlaps(combined, rows, members),
        "checks": checks,
    }


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")
