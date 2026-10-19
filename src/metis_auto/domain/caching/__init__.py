"""Cache policy (CMP-06): eligibility, scope, key composition, validity, and
store rules. Stores hold data only (ADR-0011 point 5). Demo-only settings
(bot-level scope rule, demo seed) are labelled (ADR-0023). Traces:
FR-XCACHE-*, FR-SCACHE-*, ADR-0007, ADR-0011."""

from .normalise import TREATMENTS, normalise
from .policy import (
    CachePolicyConfig,
    DemoSeedConfig,
    KeyVariant,
    ScopeRule,
    compose_key,
    compose_seed_key,
    eligibility,
    ineligible_result,
    seed_eligibility,
    seed_ineligible_result,
    select_scope,
    store_decision,
    validate_entry,
)

__all__ = [
    "TREATMENTS",
    "CachePolicyConfig",
    "DemoSeedConfig",
    "KeyVariant",
    "ScopeRule",
    "compose_key",
    "compose_seed_key",
    "eligibility",
    "ineligible_result",
    "normalise",
    "seed_eligibility",
    "seed_ineligible_result",
    "select_scope",
    "store_decision",
    "validate_entry",
]
