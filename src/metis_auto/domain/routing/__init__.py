"""Routing (CMP-05): a shared eligibility filter, then a selectable policy;
the System-One decision router's gate, state and policy
(ADR-0047).
Traces: FR-ROUTE-01…07, routing.md."""

from .base import PolicyChoice, RequestedModelMode, RoutingPolicy
from .decision import (
    Answers,
    GateConfig,
    GateDecision,
    QuestionIds,
    StateConfig,
    build_state,
    needs_decision,
)
from .decision_policy import (
    CriteriaConfig,
    DecisionRouterConfig,
    DecisionRouterPolicy,
    EffortConfig,
    HysteresisConfig,
    MappingConfig,
    TierDecision,
    map_answers,
)
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
    "Answers",
    "CostModel",
    "CriteriaConfig",
    "DecisionRouterConfig",
    "DecisionRouterPolicy",
    "EffortConfig",
    "EligibilityConfig",
    "FixedModelConfig",
    "FixedModelPolicy",
    "GateConfig",
    "GateDecision",
    "HysteresisConfig",
    "MappingConfig",
    "PolicyChoice",
    "QuestionIds",
    "RequestedModelMode",
    "RoutingConfig",
    "RoutingPolicy",
    "Rule",
    "RuleBasedConfig",
    "RuleBasedPolicy",
    "RuleCondition",
    "StateConfig",
    "StickyConfig",
    "StickyMode",
    "StickyPolicy",
    "TierDecision",
    "build_state",
    "difference",
    "effective_cost",
    "filter_eligible",
    "map_answers",
    "needs_decision",
    "rank_by_cost",
    "reconstruct_anchor",
    "route",
]
