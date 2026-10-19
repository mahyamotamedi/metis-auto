"""Routing (CMP-05): a shared eligibility filter, then a selectable policy.
Traces: FR-ROUTE-01…07, routing.md."""

from .base import PolicyChoice, RequestedModelMode, RoutingPolicy
from .eligibility import EligibilityConfig, filter_eligible
from .fixed_model import FixedModelConfig, FixedModelPolicy
from .policy import RoutingConfig, route
from .rule_based import (
    CostModel,
    Rule,
    RuleBasedConfig,
    RuleBasedPolicy,
    RuleCondition,
    effective_cost,
    rank_by_cost,
)
from .sticky import (
    Anchor,
    StickyConfig,
    StickyMode,
    StickyPolicy,
    difference,
    reconstruct_anchor,
)

__all__ = [
    "Anchor",
    "CostModel",
    "EligibilityConfig",
    "FixedModelConfig",
    "FixedModelPolicy",
    "PolicyChoice",
    "RequestedModelMode",
    "RoutingConfig",
    "RoutingPolicy",
    "Rule",
    "RuleBasedConfig",
    "RuleBasedPolicy",
    "RuleCondition",
    "StickyConfig",
    "StickyMode",
    "StickyPolicy",
    "difference",
    "effective_cost",
    "filter_eligible",
    "rank_by_cost",
    "reconstruct_anchor",
    "route",
]
