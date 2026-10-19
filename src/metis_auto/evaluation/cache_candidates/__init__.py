"""Cache-candidate experiments (CMP-23 support): every key variant and scope
in one pass over replay cases, outside the serving path (caching.md §4)."""

from .harness import (
    BASES,
    CandidateHarness,
    CandidateRun,
    KeyVariantSpec,
    order_cases,
    variants,
)
from .index import (
    BUILTIN_INDEXES,
    CandidateIndex,
    CandidateItem,
    ExactKeyIndex,
    IndexFactory,
    WildcardIndex,
    exact_index,
)

__all__ = [
    "BASES",
    "BUILTIN_INDEXES",
    "CandidateHarness",
    "CandidateIndex",
    "CandidateItem",
    "CandidateRun",
    "ExactKeyIndex",
    "IndexFactory",
    "KeyVariantSpec",
    "WildcardIndex",
    "exact_index",
    "order_cases",
    "variants",
]
