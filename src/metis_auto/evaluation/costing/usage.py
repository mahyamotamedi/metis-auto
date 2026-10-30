"""Recorded usage and empirical quantiles (Stage E2; framework §2.2).

A ``UsageRecord`` is what a recorded or live call reported for one (request,
model, effort): provider-reported token counts (``output_tokens`` *includes*
hidden reasoning, as billed; ``reasoning_tokens`` is the reported part, or
None), plus the lengths needed to relate answers across models. No text is
held here (privacy: derived features only). ``empirical_quantile`` is plain
linear-interpolation quantile; ``min_n_for_quantile`` is the arithmetic floor
below which the q-quantile is not identifiable (n values cannot separate a
quantile from the sample extreme when n < 1 / min(q, 1 - q)); it is not a
chosen threshold. Pure, stdlib only.
Status: provisional (Stage E2).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class UsageRecord:
    request_id: str
    session_ref: str
    model_id: str
    effort: str | None
    input_tokens: int
    output_tokens: int
    """Billed output tokens, including reasoning."""
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None
    visible_output_chars: int | None = None
    logged_answer_chars: int | None = None
    strata: Mapping[str, str] = field(default_factory=dict)

    @property
    def visible_output_tokens(self) -> int | None:
        if self.reasoning_tokens is None:
            return None
        return self.output_tokens - self.reasoning_tokens


def min_n_for_quantile(q: float) -> int:
    """The least n at which the q-quantile is identifiable (see module doc)."""
    if not 0 < q < 1:
        raise ValueError("q must be between 0 and 1")
    # rounded first: 1 / (1 - 0.9) is 10.000000000000002 in floating point
    return math.ceil(round(1 / min(q, 1 - q), 9))


def empirical_quantile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation quantile; None for no values."""
    if not 0 <= q <= 1:
        raise ValueError("q must be between 0 and 1")
    if not values:
        return None
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction
