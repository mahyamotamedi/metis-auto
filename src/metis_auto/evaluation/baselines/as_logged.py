"""As-logged baseline (CMP-22; evaluation.md §5, ADR-0002, ADR-0014 point 4).

Responsibility: the cost of what the logged model actually did, computed from
the case without a pipeline run. Each reference answer's logged label is
mapped to a catalogue model through the label mapping (with its fidelity);
its cost is the case's request on the assumed prompt composition (the
``Request`` as the case builder made it: logged instructions, full logged
history, logged retrieved context, the message) counted with that model's
tokenizer plus chat framing, and the answer re-counted, priced from the
price table (``AccountingService.account``, basis ``baseline_estimate``).
A case with several answers costs the sum (each priced on the same request:
an assumption, as the log does not say what the later call was sent).

"Not computed" (never zero): no reference (``usage_unknown``); a label that
is unknown, not listed, or unmapped (``model_unmapped``); a missing price.
Also: ``premium_cost`` for the premium baseline (brief §5): the same answers
re-counted on the premium model, never called.

Caveats always apply: labels are not billing entities (A-07); prices are the
current table's, not those at log time; counts are local (strict fidelity,
ADR-0020); hidden reasoning of the logged model is not in the logged answer.
Called by: evaluation.cache_candidates, evaluation.runner.
Calls: application.accounting, domain.accounting. Status: implemented (Stage 8).
"""

from __future__ import annotations

from dataclasses import dataclass

from metis_auto.application.accounting import AccountingService
from metis_auto.contracts import (
    ComponentState,
    Cost,
    CostBasis,
    Name,
    NotComputedReason,
    PriceTable,
    ReplayCase,
)
from metis_auto.domain.accounting import AccountingConfig, not_computed, total_cost
from metis_auto.settings import LabelFidelity, LabelMapping


@dataclass(frozen=True)
class LabelResolution:
    """How one logged label resolved (counts by outcome go into reports)."""

    model_id: Name | None
    fidelity: LabelFidelity | None
    outcome: Name
    """``exact_id``, ``alias``, ``unknown_label``, ``not_listed``, or the
    mapping's unmapped reason."""


def resolve_label(
    state: ComponentState, label: str | None, mapping: LabelMapping
) -> LabelResolution:
    if state != ComponentState.PRESENT or label is None:
        return LabelResolution(None, None, "unknown_label")
    row = mapping.get(label)
    if row is None:
        return LabelResolution(None, None, "not_listed")
    if row.model_id is None:
        assert row.unmapped is not None
        return LabelResolution(None, None, row.unmapped.value)
    assert row.fidelity is not None
    return LabelResolution(row.model_id, row.fidelity, row.fidelity.value)


@dataclass(frozen=True)
class AsLoggedCost:
    case_id: str
    cost: Cost
    labels: tuple[LabelResolution, ...]


def as_logged_cost(
    case: ReplayCase,
    mapping: LabelMapping,
    accounting: AccountingService,
    prices: PriceTable,
) -> AsLoggedCost:
    basis = CostBasis.BASELINE_ESTIMATE
    labels = tuple(
        resolve_label(r.model_label.state, r.model_label.value, mapping)
        for r in case.references
    )
    if not case.references:
        return AsLoggedCost(
            case.case_id, not_computed(NotComputedReason.USAGE_UNKNOWN, basis), labels
        )
    if any(r.model_id is None for r in labels):
        return AsLoggedCost(
            case.case_id, not_computed(NotComputedReason.MODEL_UNMAPPED, basis), labels
        )
    # Counted as an actual call, then labelled a baseline estimate (the
    # AccountedUsage contract reserves baseline_estimate for named baselines).
    costs = [
        accounting.account(case.request, label.model_id, ref.text).cost.model_copy(
            update={"basis": basis}
        )
        for ref, label in zip(case.references, labels, strict=True)
        if label.model_id is not None
    ]
    total = (
        costs[0]
        if len(costs) == 1
        else total_cost(costs, basis, prices, AccountingConfig())
    )
    return AsLoggedCost(case.case_id, total, labels)


def premium_cost(
    case: ReplayCase,
    premium_model_id: str | None,
    accounting: AccountingService,
    prices: PriceTable,
) -> Cost:
    """Brief §5 estimate for the case's logged answers on the premium model."""
    basis = CostBasis.BASELINE_ESTIMATE
    if premium_model_id is None:
        return not_computed(NotComputedReason.BASELINE_UNSET, basis)
    if not case.references:
        return not_computed(NotComputedReason.USAGE_UNKNOWN, basis)
    costs = [
        accounting.premium_estimate(case.request, ref.text, premium_model_id).cost
        for ref in case.references
    ]
    return (
        costs[0]
        if len(costs) == 1
        else total_cost(costs, basis, prices, AccountingConfig())
    )
