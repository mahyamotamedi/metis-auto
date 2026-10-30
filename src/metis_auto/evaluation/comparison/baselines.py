"""Baselines as assignments over an outcome table (Stage E1; framework §1;
ADR-0002).

A *system* is an assignment: request_id → model it used. Baselines are
assignments too, so every comparison goes through the same metrics:
``fixed_assignment`` (premium, cheapest acceptable, any single model),
``as_logged_assignment`` (the logged choice, from a label mapping; unmapped
requests are left out and counted by the caller), ``oracle_assignment``
(hindsight, RouterBench-style: the best-quality model, the cheapest of those
within a noise margin; or the cheapest within δ of a reference model), and
``random_mix_expected`` (the expected cost and quality of a router that picks
models at random with a given mix, isolating routing skill from simply using
cheaper models).

The oracle needs complete outcomes for the candidates on each request (only
true of the shared sampling run) and **validated** quality (§0.4); the noise
margin and δ are arguments with no default, and an unset one means "not
evaluated". The oracle is a bound, not a target: the maximum of noisy scores
is biased upward, which the margin is meant to limit. Pure.
Status: provisional (Stage E1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .types import EvalRequest, OutcomeTable

KINDS = ("fixed_model", "as_logged", "oracle", "random_mix")


@dataclass(frozen=True)
class BaselineSpec:
    """A baseline named by configuration (values come from config, not code)."""

    name: str
    kind: str
    model_id: str | None = None
    params: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if self.kind == "fixed_model" and not self.model_id:
            raise ValueError("a fixed_model baseline needs a model_id")


@dataclass(frozen=True)
class SystemPoint:
    """Mean cost and quality of a system over the requests where it has both."""

    label: str
    n: int
    total: int
    mean_cost: float | None
    mean_quality: float | None
    provenance: str

    @property
    def coverage(self) -> float:
        return self.n / self.total if self.total else 0.0


@dataclass(frozen=True)
class OracleResult:
    state: str
    """``measured`` or ``not_evaluated``."""
    assignment: Mapping[str, str]
    skipped: int
    reason: str | None = None


def fixed_assignment(table: OutcomeTable, model_id: str) -> dict[str, str]:
    return {r.request_id: model_id for r in table.requests}


def as_logged_assignment(
    table: OutcomeTable, logged_model: Mapping[str, str | None]
) -> dict[str, str]:
    """The logged model per request; requests with no mapped model are absent."""
    return {
        r.request_id: m
        for r in table.requests
        if (m := logged_model.get(r.request_id)) is not None
    }


def system_point(
    table: OutcomeTable, assignment: Mapping[str, str], label: str
) -> SystemPoint:
    costs: list[float] = []
    qualities: list[float] = []
    for request in table.requests:
        model = assignment.get(request.request_id)
        outcome = request.outcomes.get(model) if model is not None else None
        if (
            outcome is not None
            and outcome.cost is not None
            and (outcome.quality is not None)
        ):
            costs.append(outcome.cost)
            qualities.append(outcome.quality)
    n = len(costs)
    return SystemPoint(
        label=label,
        n=n,
        total=len(table.requests),
        mean_cost=sum(costs) / n if n else None,
        mean_quality=sum(qualities) / n if n else None,
        provenance=table.provenance,
    )


def _complete(request: EvalRequest) -> dict[str, tuple[float, float]]:
    return {
        m: (o.cost, o.quality)
        for m, o in request.outcomes.items()
        if o.cost is not None and o.quality is not None
    }


def oracle_assignment(
    table: OutcomeTable,
    *,
    mode: str,
    noise_margin: float | None = None,
    reference_model: str | None = None,
    delta: float | None = None,
) -> OracleResult:
    """Hindsight choice per request.

    ``best_quality``: models within ``noise_margin`` of the best quality count
    as tied; the cheapest wins (ties by model id). ``cheapest_within_delta``:
    the cheapest model whose quality is at least the reference model's minus
    ``delta``. Requests without a complete outcome (and, for the second mode,
    without a complete reference) are skipped and counted."""
    if not table.quality_validated:
        return OracleResult("not_evaluated", {}, 0, "unvalidated_quality")
    if mode == "best_quality":
        if noise_margin is None:
            return OracleResult("not_evaluated", {}, 0, "noise_margin_unset")
        if noise_margin < 0:
            raise ValueError("noise_margin must not be negative")
    elif mode == "cheapest_within_delta":
        if reference_model is None:
            raise ValueError("cheapest_within_delta needs a reference_model")
        if delta is None:
            return OracleResult("not_evaluated", {}, 0, "delta_unset")
        if delta < 0:
            raise ValueError("delta must not be negative")
    else:
        raise ValueError("mode must be best_quality or cheapest_within_delta")
    assignment: dict[str, str] = {}
    skipped = 0
    for request in table.requests:
        complete = _complete(request)
        if not complete:
            skipped += 1
            continue
        if mode == "best_quality":
            assert noise_margin is not None
            best = max(q for _, q in complete.values())
            floor = best - noise_margin
        else:
            if reference_model not in complete:
                skipped += 1
                continue
            assert delta is not None
            floor = complete[reference_model][1] - delta
        eligible = {m: v for m, v in complete.items() if v[1] >= floor}
        assignment[request.request_id] = min(
            eligible, key=lambda m: (eligible[m][0], m)
        )
    return OracleResult("measured", assignment, skipped)


def random_mix_expected(
    table: OutcomeTable, mix: Mapping[str, float], label: str = "random_mix"
) -> SystemPoint:
    """Expected cost and quality of choosing each model with probability
    ``mix[model]`` per request, over requests where every model in the mix has a
    complete outcome."""
    if not mix or any(s <= 0 for s in mix.values()):
        raise ValueError("mix shares must be positive")
    if abs(sum(mix.values()) - 1.0) > 1e-9:
        raise ValueError("mix shares must sum to 1")
    costs: list[float] = []
    qualities: list[float] = []
    for request in table.requests:
        complete = _complete(request)
        if all(m in complete for m in mix):
            costs.append(sum(s * complete[m][0] for m, s in mix.items()))
            qualities.append(sum(s * complete[m][1] for m, s in mix.items()))
    n = len(costs)
    return SystemPoint(
        label=label,
        n=n,
        total=len(table.requests),
        mean_cost=sum(costs) / n if n else None,
        mean_quality=sum(qualities) / n if n else None,
        provenance=table.provenance,
    )
