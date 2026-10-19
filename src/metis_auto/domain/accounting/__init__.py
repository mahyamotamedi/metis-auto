"""Accounting (CMP-09): token totals, chat-template overhead, cost from usage
and tiered prices, request totals, pre-call estimates, the premium-baseline
estimate, and the savings decomposition. "Not computed" when a price or usage
is unknown, never zero (FR-ACCT-02). Traces: FR-ACCT-01…07, ADR-0002,
ADR-0006, ADR-0020."""

from .baseline import baseline_estimate
from .cost import (
    HIDDEN_REASONING,
    AccountingConfig,
    bills_hidden_reasoning,
    cost_of,
    not_computed,
    pre_call_estimate,
    provider_cache_discount,
    total_cost,
)
from .overhead import template_overhead, with_overhead
from .savings import decompose_message, sum_decompositions
from .tokens import sum_counts, worst_fidelity

__all__ = [
    "HIDDEN_REASONING",
    "AccountingConfig",
    "baseline_estimate",
    "bills_hidden_reasoning",
    "cost_of",
    "decompose_message",
    "not_computed",
    "pre_call_estimate",
    "provider_cache_discount",
    "sum_counts",
    "sum_decompositions",
    "template_overhead",
    "total_cost",
    "with_overhead",
    "worst_fidelity",
]
