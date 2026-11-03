"""The P-1..P-3 plan: what a run would do and cost, with **no call**.

``build_plan`` counts the generation calls (callable arms × records) and the
judge calls (records × callable arms × 2 judges × 2 orders, plan P-2), prices
the generation with E4's ``estimate_run`` (input-only lower bound; ceiling at
the generation limit when the owner set it), bounds the judge cost when the
judge models and limits are set, and lists the three paid-branch gates and
every owner value still unset. It never invents a missing value: an unset
input gives ``None`` with the reason. Pure. Traces: QA-COST, ADR-0018,
ADR-0053. Status: provisional.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from metis_auto.contracts import CatalogueEntry, PriceTable
from metis_auto.evaluation.sampling.config import RunConfig
from metis_auto.evaluation.sampling.runner import PlannedCall, estimate_run

from .arms import ArmStatus
from .config import BenchmarkConfig

JUDGE_ORDERS = 2
"""Both answer orders (plan P-2; ``evaluation.judging.pairwise``)."""


@dataclass(frozen=True)
class Gate:
    name: str
    state: str
    """``met``, ``missing`` or ``per_run``."""
    note: str


def generation_estimate(
    records: Sequence[str],
    arms: Sequence[str],
    *,
    input_tokens: Mapping[tuple[str, str], int],
    catalogue: Mapping[str, CatalogueEntry],
    prices: PriceTable,
    max_output_tokens: int | None,
) -> dict[str, object]:
    calls = [
        PlannedCall(case_id=r, session_ref=r, model_id=m, effort=None, repeat_index=0)
        for r in records
        for m in arms
    ]
    est = estimate_run(
        calls,
        input_tokens=input_tokens,
        catalogue=catalogue,
        prices=prices,
        config=RunConfig(models=tuple(arms), max_output_tokens=max_output_tokens),
    )
    return {
        "calls": est.calls,
        "lower_bound_usd": _s(est.lower_bound_usd),
        "ceiling_usd": _s(est.ceiling_usd),
        "reasons": dict(est.reasons),
    }


def judge_estimate(
    records: Sequence[str],
    arms: Sequence[str],
    *,
    judges: Sequence[str] | None,
    judge_input_tokens: Mapping[tuple[str, str], int] | None,
    candidate_max_tokens: int | None,
    judge_max_output: int | None,
    catalogue: Mapping[str, CatalogueEntry],
    prices: PriceTable,
) -> dict[str, object]:
    """``judge_input_tokens[(record, judge)]``: prompt + request view +
    reference answer, counted with the judge's tokenizer. The candidate answer
    is bounded by ``candidate_max_tokens`` (the generation limit)."""
    n = len(records) * len(arms) * 2 * JUDGE_ORDERS
    out: dict[str, object] = {"calls": n, "lower_bound_usd": None, "ceiling_usd": None}
    reasons: dict[str, str] = {}
    if judges is None:
        reasons["all"] = "set by owner: judges.models"
        out["reasons"] = reasons
        return out
    if judge_input_tokens is None:
        reasons["all"] = "judge input sizes unknown (needs the database)"
        out["reasons"] = reasons
        return out
    lower = Decimal(0)
    ceiling: Decimal | None = Decimal(0)
    for judge in judges:
        per_judge_calls = [
            PlannedCall(
                case_id=r, session_ref=r, model_id=judge, effort=None, repeat_index=0
            )
            for r in records
        ]
        base = estimate_run(
            per_judge_calls,
            input_tokens={(r, judge): judge_input_tokens[(r, judge)] for r in records}
            if all((r, judge) in judge_input_tokens for r in records)
            else {},
            catalogue=catalogue,
            prices=prices,
            config=RunConfig(models=(judge,), max_output_tokens=judge_max_output),
        )
        factor = len(arms) * JUDGE_ORDERS
        if base.lower_bound_usd is None:
            reasons["lower_bound_usd"] = base.reasons.get("lower_bound_usd", "unknown")
            lower = None  # type: ignore[assignment]
            ceiling = None
            break
        lower += base.lower_bound_usd * factor
        if candidate_max_tokens is None or judge_max_output is None:
            ceiling = None
            reasons["ceiling_usd"] = (
                "set by owner: run.max_output_tokens"
                if candidate_max_tokens is None
                else "set by owner: judges.max_output_tokens"
            )
            continue
        if ceiling is not None:
            grown = {
                (r, judge): judge_input_tokens[(r, judge)] + candidate_max_tokens
                for r in records
            }
            top = estimate_run(
                per_judge_calls,
                input_tokens=grown,
                catalogue=catalogue,
                prices=prices,
                config=RunConfig(models=(judge,), max_output_tokens=judge_max_output),
            )
            if top.ceiling_usd is None:
                ceiling = None
                reasons["ceiling_usd"] = top.reasons.get("ceiling_usd", "unknown")
            else:
                ceiling += top.ceiling_usd * factor
    out["lower_bound_usd"] = _s(lower)
    out["ceiling_usd"] = _s(ceiling)
    out["reasons"] = reasons
    return out


def gates(
    *, amendment_committed: bool, samples_allowed: bool | None
) -> tuple[Gate, ...]:
    """The three paid-branch gates of the final plan."""
    return (
        Gate(
            "ADR-0018 amendment 2 committed",
            "met" if amendment_committed else "missing",
            "committed 2026-11-01 (ceiling and lifetime cap 20 USD), approved for "
            "the golden answers; whether the benchmark may spend from the "
            "remaining credit is an owner decision",
        ),
        Gate(
            "Metis allows sending samples to model APIs (O-1, licence)",
            "met" if samples_allowed else "missing",
            "no written answer recorded; until then no dataset text goes to any "
            "provider",
        ),
        Gate(
            "owner approval in chat per run, after the printed estimate",
            "per_run",
            "given per run; never assumed",
        ),
    )


def build_plan(
    config: BenchmarkConfig,
    *,
    arms: Sequence[ArmStatus],
    records: Sequence[str],
    generation: Mapping[str, object],
    judging: Mapping[str, object],
    budget: Mapping[str, object],
    gate_list: Sequence[Gate],
    tenant: Mapping[str, object] | None,
) -> dict[str, object]:
    callable_ = [a.model_id for a in arms if a.callable]
    return {
        "set": config.set.dataset_id,
        "reference": f"{config.set.reference_model} ({config.set.reference_run_id})",
        "records": len(records),
        "arms": [
            {
                "model": a.model_id,
                "callable": a.callable,
                "reason": a.reason,
                "tier": a.tier,
                "provider": a.provider,
            }
            for a in arms
        ],
        "callable_arms": callable_,
        "generation": dict(generation),
        "judging": dict(judging),
        "budget": dict(budget),
        "tenant_check": dict(tenant) if tenant is not None else None,
        "gates": [g.__dict__ for g in gate_list],
        "owner_values_unset": config.unset_owner_values(),
        "makes_calls": False,
    }


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")
