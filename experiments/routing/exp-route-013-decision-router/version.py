"""exp-route-013: the decision router as a routing step version on R-0's
routing base (ADR-0047; final plan R-0, J-3
remapped; FR-ROUTE-01, FR-ROUTE-03, FR-ROUTE-05, H-1; ADR-0045).

The decision router answers typed questions about a request and its pure
policy maps the answers to a **tier** (0 cheap, 1 strong). It never names a
model. This version turns a tier per request into a routed model with the
shared routing base, unchanged:

- ``analysis.routing_base.candidate_costs`` gives each candidate's price-file
  cost per row, NaN where the candidate is not eligible (R-0's rules: window,
  output limit, attachments, functions, unknowns, the long-context cliff);
- among the eligible candidates **of the decided tier** (catalogue ``tier``,
  a placeholder, A-48) the cheapest is chosen;
- the request moves only if that is strictly cheaper than its incumbent
  (``baselines_full.model_row_costs``): never upward in cost.

Rows with no decided tier (gate skip, failure, fallback to the rules) keep
their incumbent with a reason. The tiers come from the router's shadow run
(``wiring.router_eval``), keyed by the caller onto the frame's index; this
module never runs a model. A **cost simulation; quality not proven**.

Layer: candidate code in ``experiments/``, loaded by file path; pure over
injected frames. Output columns follow R-B3: ``routed_model``,
``route_reason``, ``route_cost_incumbent``, ``route_cost_routed``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from metis_auto.analysis.baselines_full import model_row_costs
from metis_auto.analysis.routing_base import candidate_costs, candidate_list

ASSUMPTIONS = (
    "cost simulation; quality not proven",
    "tiers come from the decision router's shadow run; catalogue tiers are "
    "placeholders (A-48)",
    "token counts assumed model-independent; logged output length unchanged",
    "fees and recorded cost blocks unchanged",
)
REASONS = (
    "no_decision",
    "incumbent_unpriced",
    "no_eligible_in_tier",
    "no_cheaper_candidate",
    "moved",
)


@dataclass
class DecisionRouterRouting:
    """``StepVersion`` (step ``routing``) over R-0's routing base."""

    tiers: pd.Series
    """Decided tier per row (index-aligned with the frame; NaN = no decision)."""
    tier_of: Mapping[str, int]
    """Catalogue tier per candidate model (placeholders, A-48)."""
    rules: Mapping[str, Any]
    """``sprint.toml [routing]`` as loaded (R-0's rules)."""
    cached_separately: frozenset[str] = frozenset()
    name: str = "route.decision_router"
    step: str = field(default="routing", init=False)

    def apply(self, req: pd.DataFrame, ctx: Any) -> pd.DataFrame:
        candidates: Sequence[str] = candidate_list(self.rules)
        costs = candidate_costs(
            req,
            ctx,
            candidates,
            rules=self.rules,
            cached_separately=self.cached_separately,
        )
        incumbent = req["bot_provider_model"].astype(str)
        inc_cost = pd.Series(np.nan, index=req.index)
        for model in sorted(set(incumbent)):
            rows = incumbent == model
            try:
                inc_cost[rows] = model_row_costs(
                    req[rows], ctx, model, cached_separately=self.cached_separately
                )
            except (KeyError, ValueError):  # not in the catalogue: unpriced
                continue
        tiers = self.tiers.reindex(req.index)
        routed = incumbent.to_numpy(dtype=object).copy()
        routed_cost = inc_cost.to_numpy(dtype=float).copy()
        reason = np.full(len(req), "", dtype=object)
        for i, (_, tier) in enumerate(tiers.items()):
            if pd.isna(tier):
                reason[i] = "no_decision"
                continue
            if np.isnan(routed_cost[i]):
                reason[i] = "incumbent_unpriced"
                continue
            options = [
                (costs.iloc[i][m], m)
                for m in candidates
                if self.tier_of.get(m) == int(tier) and not np.isnan(costs.iloc[i][m])
            ]
            if not options:
                reason[i] = "no_eligible_in_tier"
                continue
            best_cost, best = min(options)
            if best_cost < routed_cost[i]:
                routed[i], routed_cost[i], reason[i] = best, best_cost, "moved"
            else:
                reason[i] = "no_cheaper_candidate"
        out = req.copy()
        out["routed_model"] = routed
        out["route_reason"] = reason
        out["route_cost_incumbent"] = inc_cost.to_numpy(dtype=float)
        out["route_cost_routed"] = routed_cost
        return out
