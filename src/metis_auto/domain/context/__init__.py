"""Context construction (CMP-07): request components → ordered input parts for
one target, plus a content-free composition record. Traces: FR-CTX-01…05."""

from .pass_through import PassThroughStrategy
from .policy import (
    ContextConfig,
    ContextStrategy,
    OverflowRule,
    check_fit,
    reserved_output,
)

__all__ = [
    "ContextConfig",
    "ContextStrategy",
    "OverflowRule",
    "PassThroughStrategy",
    "check_fit",
    "reserved_output",
]
