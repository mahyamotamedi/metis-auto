"""exp-route-013: the decision router's tiers on R-0's routing base
(ADR-0047; ADR-0045; J-3 remapped). Every frame,
model, limit, tier and price here is [SYNTHETIC]. The routing base is used
unchanged: its eligibility excludes, the decided tier chooses among the rest,
and a request never moves to a dearer model."""

from __future__ import annotations

import numpy as np
import pandas as pd

from metis_auto.analysis.levers import ReplayContext

NAN = np.nan
VERSION = "routing/exp-route-013-decision-router/version.py"


def _limits(window, out):
    return {"context_window": {"value": window}, "max_output_tokens": {"value": out}}


CATALOGUE = {
    "models": [
        {"model_id": "syn-cheap", "price_ref": "p-cheap", "enabled": True}
        | _limits(1000, 100),
        {"model_id": "syn-mid", "price_ref": "p-mid", "enabled": True}
        | _limits(10**6, 10**5),
        {"model_id": "syn-strong", "price_ref": "p-strong", "enabled": True}
        | _limits(10**6, 10**5),
        {"model_id": "syn-logged", "price_ref": "p-logged", "enabled": False}
        | _limits(10**6, 10**5),
    ]
}
PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1_000_000,
    "prices": [
        {"price_ref": "p-cheap", "input": "1", "output": "1", "cached_input": "1"},
        {"price_ref": "p-mid", "input": "2", "output": "2", "cached_input": "2"},
        {"price_ref": "p-strong", "input": "5", "output": "5", "cached_input": "5"},
        {"price_ref": "p-logged", "input": "4", "output": "4", "cached_input": "4"},
    ],
}
RULES = {
    "candidates": ["syn-cheap", "syn-mid", "syn-strong"],
    "candidates_jev": [],
    "retiring": [],
    "avoid_long_context_tier": True,
}
TIER_OF = {"syn-cheap": 0, "syn-mid": 0, "syn-strong": 1}


def ctx() -> ReplayContext:
    return ReplayContext(
        period_bounds={}, price_table=PRICES, catalogue=CATALOGUE, seed=1
    )


def frame() -> pd.DataFrame:
    """Row 0 tier 0 fits syn-cheap; row 1 tier 0 is over syn-cheap's window, so
    syn-mid; row 2 tier 1 (syn-strong dearer than the incumbent: stays); row 3
    no decision; row 4 tier 0 with an attachment (nothing eligible)."""
    return pd.DataFrame(
        {
            "llm_request": [True] * 5,
            "bot_provider_model": ["syn-logged"] * 5,
            "a_bill_inputTokens": [500, 2000, 500, 500, 500],
            "a_bill_cachedInputTokens": [0] * 5,
            "a_bill_outputTokens": [50, 50, 50, 50, 50],
            "u_att_n": [0, 0, 0, 0, 1],
            "bot_n_functions": [0] * 5,
        }
    )


def test_tiers_choose_among_the_routing_base_eligible_candidates(load_experiment):
    v = load_experiment(VERSION)
    tiers = pd.Series([0, 0, 1, NAN, 0])
    out = v.DecisionRouterRouting(tiers=tiers, tier_of=TIER_OF, rules=RULES).apply(
        frame(), ctx()
    )
    assert list(out["routed_model"]) == [
        "syn-cheap",
        "syn-mid",
        "syn-logged",
        "syn-logged",
        "syn-logged",
    ]
    assert list(out["route_reason"]) == [
        "moved",
        "moved",
        "no_cheaper_candidate",
        "no_decision",
        "no_eligible_in_tier",
    ]
    moved = out["route_reason"] == "moved"
    assert (
        out.loc[moved, "route_cost_routed"] < out.loc[moved, "route_cost_incumbent"]
    ).all()
    assert set(out["route_reason"]) <= set(v.REASONS)
    assert (
        v.DecisionRouterRouting(tiers=tiers, tier_of=TIER_OF, rules=RULES).step
        == "routing"
    )


def test_the_input_frame_is_not_changed(load_experiment):
    v = load_experiment(VERSION)
    before = frame()
    v.DecisionRouterRouting(
        tiers=pd.Series([0] * 5), tier_of=TIER_OF, rules=RULES
    ).apply(before, ctx())
    pd.testing.assert_frame_equal(before, frame())
