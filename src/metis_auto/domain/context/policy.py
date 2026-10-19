"""Context strategy interface and the shared budget/overflow rule
(context_construction.md §2 steps 4–5).

Responsibility: declare the pluggable ``ContextStrategy`` and decide the
overflow outcome for a plan. Pure. Called by: the strategies in this package;
the pipeline reads the outcome from ``ContextPlan.record.overflow``.
Config: ``ContextConfig``. Traces: FR-CTX-01…05.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import Field

from metis_auto.contracts import (
    CatalogueEntry,
    ContextPlan,
    ContractModel,
    Name,
    OverflowOutcome,
    PolicyRef,
    Request,
    RequestMeasurements,
    TargetTokenCounts,
)

from .compression import CompressionConfig


class OverflowRule(StrEnum):
    TRIM = "trim"
    REROUTE = "reroute"
    REJECT = "reject"
    TRIM_THEN_REROUTE = "trim_then_reroute"


class ContextConfig(ContractModel):
    compression: CompressionConfig = CompressionConfig()
    """EXPERIMENTAL compression of history and retrieved context (Demo
    milestone); off by default."""
    strategy: Name = "pass_through"
    """Name wiring resolves to a promoted ``ContextStrategy``."""
    overflow_rule: OverflowRule = OverflowRule.TRIM_THEN_REROUTE  # provisional
    safety_margin: float = 0.1
    """Fraction of input tokens added before the window check (provisional)."""
    default_reserved_output_tokens: int = 1024
    """Used when the catalogue's output limit is unknown (provisional)."""
    max_output_tokens_cap: int | None = Field(default=None, gt=0)
    """Generation limit actually requested: at most this many output tokens
    (reasoning included), even when the model allows more. It is also the
    output reserved in the fit check and in the spend guard's pre-call
    estimate, so a model's full output limit (e.g. 128,000) does not inflate
    every estimate. None = the model's limit (Stage 7.5; provisional)."""


class ContextStrategy(Protocol):
    """A pure context strategy. Reducers in experiments/context/ implement this
    until promoted (FR-CTX-02)."""

    @property
    def ref(self) -> PolicyRef: ...

    def build(
        self,
        request: Request,
        measurements: RequestMeasurements,
        counts: TargetTokenCounts,
        target: CatalogueEntry,
        config: ContextConfig,
        rerouted: bool,
    ) -> ContextPlan: ...


def reserved_output(target: CatalogueEntry, config: ContextConfig) -> int:
    """Output tokens to request and reserve: the model's limit (or the
    default when unknown), lowered to ``max_output_tokens_cap`` if set."""
    known = target.max_output_tokens.value
    limit = known if known is not None else config.default_reserved_output_tokens
    cap = config.max_output_tokens_cap
    return min(limit, cap) if cap is not None else limit


def check_fit(
    input_tokens: int,
    target: CatalogueEntry,
    config: ContextConfig,
    rerouted: bool,
) -> OverflowOutcome:
    """Fits, or what the overflow rule says to do. Trimming is TODO(Stage 8,
    context experiments): until then it frees nothing, so ``trim`` behaves
    like ``reject`` and ``trim_then_reroute`` like ``reroute``."""
    window = target.context_window.value
    if window is None:  # eligibility excludes these; nothing to check against
        return OverflowOutcome.FITS
    needed = input_tokens * (1 + config.safety_margin) + reserved_output(target, config)
    if needed <= window:
        return OverflowOutcome.FITS
    may_reroute = config.overflow_rule in (
        OverflowRule.REROUTE,
        OverflowRule.TRIM_THEN_REROUTE,
    )
    if may_reroute and not rerouted:
        return OverflowOutcome.REROUTE_REQUESTED
    return OverflowOutcome.REJECTED
