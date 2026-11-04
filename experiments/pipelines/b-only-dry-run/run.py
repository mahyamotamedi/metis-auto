"""I-1, Pipeline B only: dry-run helpers for ``levers.combine`` with R-B1 +
R-B2 + R-B3 (final plan I-1; Review Focus 1; ADR-0031, ADR-0036). A handoff
for the team, not the final integration, and no winner is picked here.

Units decide what may be added (ADR-0036 decisions 5 to 7):

- R-B1 (cache) saves recorded fees: ``as_logged`` only. The repriced baselines
  have no fee block, so it is **not computed in these units** there.
- R-B2 (context) saves tokens: ``as_logged`` (recorded) and the three repriced
  baselines (before minus after, price-file units).
- R-B3 (routing): all four baselines, each with its own model as the incumbent
  (ADR-0046 points 5 and 6); ``as_logged`` at implied recorded rates.

So a combined saving exists per baseline only for the steps computed in that
baseline's units (``unit_cells``); the rest is "not computed in these units".

Routing after context: ``combine`` hands R-B3 the frame R-B2 returned, and
R-B2 lowers ``block_token_cost`` but leaves ``a_bill_inputTokens`` as logged.
``PostContextRouting`` is this dry run's stated assumption (a design question
for the ``combine`` owner, Pipeline A): routing sees the input lowered by
R-B2's net tokens saved, with R-B2's cached-token floor (``after_tokens``).
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
STEP_UNITS = {
    "cache": ("as_logged",),
    "context": ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap"),
    "routing": ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap"),
}
BASELINES = ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap")
REASONS = {
    "cache": "not computed in these units: R-B1 saves recorded per-call fees, "
    "and the repriced baselines have no fee block",
}


def _load(relative: str, key: str) -> Any:
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, HERE.parent / relative)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


def _rb2_run() -> Any:
    return _load(
        "../context/exp-ctx-002-cross-turn-chunk-policy/run.py",
        "metis_exp_ctx_002_run_for_i1",
    )


class PostContextRouting:
    """Wrap a routing version so it sees the post-context input tokens."""

    step = "routing"

    def __init__(self, router: Any, *, cached_separately: frozenset[str]) -> None:
        self.router = router
        self.cached_separately = cached_separately
        self.name = f"{router.name}.post-context"

    def apply(self, req: pd.DataFrame, ctx: Any) -> pd.DataFrame:
        if "ctx_tokens_saved" in req:
            req = _rb2_run().after_tokens(req, self.cached_separately)
        return self.router.apply(req, ctx)


def unit_cells() -> dict[str, dict[str, Any]]:
    """Per baseline: the steps combined in its units, and why the others are
    not computed."""
    out = {}
    for key in BASELINES:
        steps = tuple(
            s for s in ("cache", "context", "routing") if key in STEP_UNITS[s]
        )
        out[key] = {
            "combined_steps": steps,
            "not_computed": {s: REASONS[s] for s in STEP_UNITS if s not in steps},
        }
    return out


def sum_rule(combined: Decimal, parts: Sequence[Decimal]) -> dict[str, Any]:
    """Combined saving must not exceed the compatible standalone sum; equality
    is allowed (steps on different rows or cost blocks)."""
    total = sum(parts, Decimal(0))
    return {
        "combined": combined,
        "standalone_sum": total,
        "holds": combined <= total,
        "equal": combined == total,
    }


def _flag(series: pd.Series) -> pd.Series:
    return series.astype("boolean").fillna(False).astype(bool)


def overlaps(after: pd.DataFrame) -> dict[str, int]:
    """Requests touched by each step and by more than one."""
    cache = _flag(after["retrieval_reused"])
    context = after["ctx_tokens_saved"].fillna(0) > 0
    routing = after["route_reason"].eq("moved").fillna(False).astype(bool)
    return {
        "cache": int(cache.sum()),
        "context": int(context.sum()),
        "routing": int(routing.sum()),
        "cache&context": int((cache & context).sum()),
        "cache&routing": int((cache & routing).sum()),
        "context&routing": int((context & routing).sum()),
        "all_three": int((cache & context & routing).sum()),
    }


def retrieval_rows_not_served(after: pd.DataFrame) -> bool:
    """R-B1 rows keep ``served_from_cache`` False (a retrieval reuse is not an
    answer-cache hit: the Day 2 accounting decision, slug
    ``retrieval-result-cache-accounting``)."""
    reused = _flag(after["retrieval_reused"])
    return not bool(_flag(after["served_from_cache"])[reused].any())
