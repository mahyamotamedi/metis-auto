"""The shared routing flow (routing.md §1–§2).

Responsibility: run eligibility → (explicit model mode) → configured policy →
model selection, and return a ``RoutingDecision`` with reason and version.
Policies are pluggable behind ``RoutingPolicy``; wiring maps a configured name
to a promoted implementation (QA-REPL). Pure.
Called by: application.pipeline (stage 3). Calls: domain.routing.eligibility
(and the injected policy).
Config: ``RoutingConfig`` plus the policy's own config. Traces: FR-ROUTE-01…07.
"""

from __future__ import annotations

from metis_auto.contracts import (
    CatalogueEntry,
    ContractModel,
    ModelCatalogue,
    Name,
    PriceTable,
    RequestFeatures,
    RoutingDecision,
    RoutingFlag,
)
from metis_auto.contracts.routing import NO_ELIGIBLE_MODEL

from .base import RequestedModelMode, RoutingPolicy
from .decision_policy import DecisionRouterConfig
from .eligibility import EligibilityConfig, filter_eligible
from .fixed_model import FixedModelConfig
from .rule_based import CostModel, RuleBasedConfig, rank_by_cost
from .sticky import StickyConfig


class RoutingConfig(ContractModel):
    policy: Name = "fixed_model"
    """Name wiring resolves to a promoted ``RoutingPolicy``."""
    eligibility: EligibilityConfig = EligibilityConfig()
    requested_model_mode: RequestedModelMode = RequestedModelMode.IGNORE
    candidates: tuple[Name, ...] = ()
    """Models routing may choose; empty = every enabled model (the serving
    default). The demo sets the sprint's primary set (config/demo, ADR-XXXX
    (demo-sprint-winners))."""
    chain: tuple[Name, ...] = ()
    """Escalation targets after the routed target (ADR-0013); configuration."""
    fixed_model: FixedModelConfig | None = None
    """Config of the ``fixed_model`` policy, when selected."""
    rule_based: RuleBasedConfig | None = None
    """Rules of ``rule_based``, also the initial routing of ``sticky``."""
    sticky: StickyConfig | None = None
    """Config of the ``sticky`` policy (mode sticky_v1 or per_request)."""
    decision_router: DecisionRouterConfig | None = None
    """Config of the ``decision_router`` policy (ADR-0047),
    also the sticky inner router when ``sticky.inner = "decision_router"``."""


def route(
    features: RequestFeatures,
    catalogue: ModelCatalogue,
    policy: RoutingPolicy,
    config: RoutingConfig,
    min_context_window: int | None = None,
    prices: PriceTable | None = None,
) -> RoutingDecision:
    """The routing decision for one request. Never routes to an ineligible model.

    ``prices`` lets a policy that answers with a tier get that tier's cheapest
    model by effective cost; without it, the first model with a known price
    in catalogue order."""
    eligible, exclusions = filter_eligible(
        features,
        catalogue,
        config.eligibility,
        min_context_window,
        candidates=config.candidates,
    )
    flags: list[RoutingFlag] = []
    if min_context_window is not None:
        flags.append(RoutingFlag.REROUTED)
    # TODO(FR-ROUTE-06, open): honour_if_eligible / honour modes.

    choice = policy.choose(features, eligible) if eligible else None
    target = None
    anchor = choice.anchor_model_id if choice is not None else None
    if choice is not None:
        if choice.model_id is not None:
            target = next((e for e in eligible if e.model_id == choice.model_id), None)
        elif choice.tier is not None:
            target = _cheapest_in_tier(eligible, choice.tier, features, prices)
    if target is None:
        return RoutingDecision(
            target_model_id=None,
            equivalence_group=None,
            tier=None,
            eligible=tuple(e.model_id for e in eligible),
            exclusions=exclusions,
            policy=policy.ref,
            reason_code=NO_ELIGIBLE_MODEL,
            min_context_window=min_context_window,
            flags=tuple(flags),
            anchor_model_id=anchor,
        )
    eligible_ids = {e.model_id for e in eligible}
    return RoutingDecision(
        target_model_id=target.model_id,
        equivalence_group=target.equivalence_group,
        tier=target.tier,
        eligible=tuple(e.model_id for e in eligible),
        exclusions=exclusions,
        # A chain model that is not eligible for this request is dropped here,
        # never invoked. A policy may choose its own chain (rule_based: the
        # cheapest model of each higher tier).
        chain=tuple(
            m
            for m in (choice.chain if choice.chain is not None else config.chain)
            if m in eligible_ids and m != target.model_id
        ),
        policy=policy.ref,
        reason_code=choice.reason_code,
        features_used=choice.features_used,
        min_context_window=min_context_window,
        flags=tuple(flags),
        anchor_model_id=choice.anchor_model_id,
        router_summary=choice.router_summary,
    )


def _cheapest_in_tier(
    eligible: tuple[CatalogueEntry, ...],
    tier: int,
    features: RequestFeatures,
    prices: PriceTable | None,
) -> CatalogueEntry | None:
    """The cheapest eligible model of ``tier`` (routing.md §1 step 5): by
    effective cost with the default cost model when prices are given (unknown
    prices last, ties by catalogue order); otherwise the first model with a
    known ``price_ref`` in catalogue order, then any. None if the tier is empty."""
    in_tier = [e for e in eligible if e.tier == tier]
    if not in_tier:
        return None
    if prices is not None:
        known = features.known_input_tokens
        tokens = known.tokens if known is not None else 0
        return rank_by_cost(in_tier, prices, tokens, CostModel())[0]
    return next((e for e in in_tier if e.price_ref is not None), in_tier[0])
