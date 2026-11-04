"""What a computed sampling estimate needs: the owner values still unset, and
the call count it gives once they are set (Gap 1, sprint close).

Nothing is chosen here: ``unset_values`` lists, ``call_estimate`` multiplies.
Pure. Traces: QA-COST, FR-EVAL-04, ADR-0053. Status: provisional.
"""

from __future__ import annotations

from .config import AllocationConfig, RunConfig

ALLOCATION_REQUIRED = ("dimensions", "total", "seed")
RUN_REQUIRED = ("models", "hard_cap_usd", "max_output_tokens", "order_seed")


def unset_values(allocation: AllocationConfig, run: RunConfig) -> list[str]:
    """Every value the estimate needs that is unset, as ``section.key``."""
    out = [
        f"allocation.{k}" for k in ALLOCATION_REQUIRED if getattr(allocation, k) is None
    ]
    out += [f"run.{k}" for k in RUN_REQUIRED if not getattr(run, k)]
    return out


def call_estimate(*, achieved_total: int, run: RunConfig) -> dict[str, int]:
    """Calls (units × models) and the output-token ceiling of the whole run."""
    if not run.models or run.max_output_tokens is None:
        raise ValueError("run.models and run.max_output_tokens are required")
    calls = achieved_total * len(run.models)
    return {
        "calls": calls,
        "max_output_tokens_total": calls * run.max_output_tokens,
    }
