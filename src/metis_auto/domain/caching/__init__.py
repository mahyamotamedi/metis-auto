"""Cache policy (CMP-06): eligibility, scope, key composition, validity, and
store rules. Stores hold data only (ADR-0011 point 5). Traces: FR-XCACHE-*,
FR-SCACHE-*, ADR-0007, ADR-0011."""

from .normalise import TREATMENTS, normalise
from .policy import (
    CachePolicyConfig,
    KeyVariant,
    compose_key,
    eligibility,
    ineligible_result,
    select_scope,
    store_decision,
    validate_entry,
)

__all__ = [
    "TREATMENTS",
    "CachePolicyConfig",
    "KeyVariant",
    "compose_key",
    "eligibility",
    "ineligible_result",
    "normalise",
    "select_scope",
    "store_decision",
    "validate_entry",
]
