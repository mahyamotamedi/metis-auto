"""Routing base: eligibility, failover and candidate cost replay (final plan
R-0; FR-ROUTE-01, FR-ROUTE-05, FR-FAIL-01..04; Review Focus 3).

Every frame, model name, limit and price here is [SYNTHETIC]: invented numbers,
no dataset content, no real price or model limit. The one exception is
``test_sprint_config_and_replay_catalogue_load``, which reads the committed
config files (no data).
"""

from __future__ import annotations

import math
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.baselines_full import repriced_row_costs, token_counts
from metis_auto.analysis.levers import ReplayContext
from metis_auto.analysis.routing_base import (
    REASON_COLUMN,
    candidate_costs,
    candidate_list,
    eligibility_frame,
    eligible_models,
    failover,
)

NAN = np.nan
ROOT = Path(__file__).resolve().parents[3]


def _limits(window, out):
    return {"context_window": {"value": window}, "max_output_tokens": {"value": out}}


# [SYNTHETIC] catalogue: every limit and tier invented.
CATALOGUE = {
    "models": [
        {"model_id": "syn-a", "price_ref": "p-a", "enabled": True} | _limits(1000, 100),
        {"model_id": "syn-b", "price_ref": "p-b", "enabled": True}
        | _limits(10**6, 10**5),
        # Long-context tier: cheap up to 1,000 input tokens, dear above.
        {"model_id": "syn-tiered", "price_ref": "p-tiered", "enabled": True}
        | _limits(10**6, 10**5),
        {"model_id": "syn-off", "price_ref": "p-a", "enabled": False}
        | _limits(10**6, 10**5),
        {"model_id": "syn-nolimit", "price_ref": "p-a", "enabled": True},
        {"model_id": "syn-unpriced", "price_ref": "p-none", "enabled": True}
        | _limits(10**6, 10**5),
        {"model_id": "syn-premium", "price_ref": "p-premium", "enabled": False}
        | _limits(10**6, 10**5),
    ]
}
PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1_000_000,
    "prices": [
        {"price_ref": "p-a", "input": "1", "output": "2", "cached_input": "0.5"},
        {"price_ref": "p-b", "input": "2", "output": "4", "cached_input": "0.1"},
        {
            "price_ref": "p-tiered",
            "max_input_tokens": 1000,
            "input": "1",
            "output": "1",
            "cached_input": "1",
        },
        {
            "price_ref": "p-tiered",
            "min_input_tokens": 1001,
            "input": "10",
            "output": "10",
            "cached_input": "10",
        },
        {"price_ref": "p-premium", "input": "20", "output": "40", "cached_input": "2"},
    ],
}


def rules(**over):
    base = {
        "candidates": ["syn-a", "syn-b", "syn-tiered"],
        "candidates_jev": [],
        "retiring": [],
        "avoid_long_context_tier": True,
    }
    return base | over


def row(**over):
    """[SYNTHETIC] one request, effective tokens already computed."""
    return {
        "input_tokens": 500.0,
        "output_tokens": 50.0,
        "u_att_n": 0,
        "bot_n_functions": 0,
    } | over


def ctx() -> ReplayContext:
    return ReplayContext(
        period_bounds={}, price_table=PRICES, catalogue=CATALOGUE, seed=7
    )


def frame() -> pd.DataFrame:
    """[SYNTHETIC] requests frame. Row 0 runs ``syn-sep``, a model that reports
    cached tokens outside the input count; row 3 is a workflow row; row 4 has
    unknown tokens; row 5 an unknown attachment count; row 7 bot functions;
    row 8 sits in the long-context tier; row 9 is over syn-a's window."""
    return pd.DataFrame(
        {
            "llm_request": [True] * 3 + [False] + [True] * 6,
            "bot_provider_model": ["syn-sep"] + ["syn-b"] * 9,
            "a_bill_inputTokens": [300, 400, 100, NAN, NAN, 200, 50, 300, 1500, 990],
            "a_bill_cachedInputTokens": [400, 100, 0, NAN, NAN, 0, 0, 0, 0, 0],
            "a_bill_outputTokens": [20, 30, 10, NAN, NAN, 10, 5, 10, 10, 20],
            "u_att_n": [0, 0, 0, 0, 0, NAN, 2, 0, 0, 0],
            "bot_n_functions": [0, 0, 0, 0, 0, 0, 0, 3, 0, 0],
        }
    )


SEP = frozenset({"syn-sep"})


# --- the plan's six tests ---------------------------------------------------


def test_vision_requests_only_get_vision_models():
    """No catalogue model has a VERIFIED vision capability, so a request with
    an image attachment gets no candidate; an unverified declaration does not
    count (FR-ROUTE-05: unverified = unsupported)."""
    cat = {
        "models": [
            m
            | {
                "capabilities": [
                    {"name": "image_input", "verified": False},
                ]
            }
            for m in CATALOGUE["models"]
        ]
    }
    assert eligible_models(row(u_att_n=1), cat, PRICES, rules()) == ()
    assert eligible_models(row(u_att_n=1), CATALOGUE, PRICES, rules()) == ()
    # Without the attachment the same models are eligible.
    assert eligible_models(row(), cat, PRICES, rules()) == (
        "syn-a",
        "syn-b",
        "syn-tiered",
    )


def test_context_over_limit_excluded():
    # syn-a: window 1,000, output limit 100.
    assert "syn-a" in eligible_models(
        row(input_tokens=950.0, output_tokens=50.0), CATALOGUE, PRICES, rules()
    )  # exactly at the window
    assert "syn-a" not in eligible_models(
        row(input_tokens=951.0, output_tokens=50.0), CATALOGUE, PRICES, rules()
    )
    assert "syn-a" not in eligible_models(
        row(input_tokens=10.0, output_tokens=101.0), CATALOGUE, PRICES, rules()
    )
    reasons = eligibility_frame(
        frame(), ctx(), rules=rules(), cached_separately=SEP, reasons=True
    )
    assert reasons.loc[9, "reason:syn-a"] == "over_context_window"


def test_unknown_limit_excludes_model():
    r = rules(candidates=["syn-nolimit", "syn-unpriced", "syn-b"])
    assert eligible_models(row(), CATALOGUE, PRICES, r) == ("syn-b",)
    out = eligibility_frame(
        frame(), ctx(), rules=r, cached_separately=SEP, reasons=True
    )
    # Rows that pass the request-level rules: the limit is the first failure.
    assert out.loc[[0, 1, 2, 8, 9], "reason:syn-nolimit"].eq("unknown_limit").all()
    assert out.loc[1, "reason:syn-unpriced"] == "unpriced"
    # Unknown input tokens exclude every candidate, with the reason recorded.
    assert eligible_models(row(input_tokens=NAN), CATALOGUE, PRICES, r) == ()
    assert eligible_models(row(output_tokens=None), CATALOGUE, PRICES, r) == ()
    assert out.loc[4, REASON_COLUMN] == "unknown_tokens"
    # A limit given as a bare null value is unknown too.
    cat = {
        "models": [
            {"model_id": "syn-b", "price_ref": "p-b", "enabled": True}
            | _limits(None, 10**5)
        ]
    }
    assert eligible_models(row(), cat, PRICES, rules(candidates=["syn-b"])) == ()


def test_long_context_price_cliff_avoided():
    small, large = row(input_tokens=900.0), row(input_tokens=1500.0)
    assert "syn-tiered" in eligible_models(small, CATALOGUE, PRICES, rules())
    assert "syn-tiered" not in eligible_models(large, CATALOGUE, PRICES, rules())
    off = rules(avoid_long_context_tier=False)
    assert "syn-tiered" in eligible_models(large, CATALOGUE, PRICES, off)
    out = eligibility_frame(
        frame(), ctx(), rules=rules(), cached_separately=SEP, reasons=True
    )
    assert out.loc[8, "reason:syn-tiered"] == "long_context_tier"


def test_long_context_rule_has_no_default():
    r = rules()
    del r["avoid_long_context_tier"]
    with pytest.raises(ValueError, match="avoid_long_context_tier"):
        eligible_models(row(), CATALOGUE, PRICES, r)


def test_retiring_model_replaced_from_config_list():
    retiring = [{"model_id": "syn-a", "replacement": "syn-b"}]
    r = rules(candidates=["syn-a", "syn-tiered"], retiring=retiring)
    assert candidate_list(r) == ("syn-b", "syn-tiered")
    got = eligible_models(row(), CATALOGUE, PRICES, r)
    assert "syn-a" not in got
    assert got == ("syn-b", "syn-tiered")
    # The replacement is returned only if it is eligible itself.
    r_off = rules(
        candidates=["syn-a"], retiring=[{"model_id": "syn-a", "replacement": "syn-off"}]
    )
    assert eligible_models(row(), CATALOGUE, PRICES, r_off) == ()
    # A retiring entry without a replacement just drops out; plain IDs work too.
    assert candidate_list(rules(retiring=["syn-a"])) == ("syn-b", "syn-tiered")
    # A retiring model is never returned, even as someone else's replacement.
    r_chain = rules(
        candidates=["syn-a"],
        retiring=[{"model_id": "syn-a", "replacement": "syn-b"}, "syn-b"],
    )
    assert eligible_models(row(), CATALOGUE, PRICES, r_chain) == ()


def test_failover_chain_order():
    """Same model elsewhere, then the equivalence group, then one tier up;
    catalogue order inside each step; never itself, disabled or retiring."""
    cat = {
        "models": [
            {"model_id": "x", "provider": "p1", "provider_model_name": "x",
             "tier": 0, "equivalence_group": "g0", "enabled": True},
            {"model_id": "y", "provider": "p2", "provider_model_name": "y",
             "tier": 0, "equivalence_group": "g0", "enabled": True},
            {"model_id": "z-off", "provider": "p2", "provider_model_name": "z",
             "tier": 0, "equivalence_group": "g0", "enabled": False},
            {"model_id": "r", "provider": "p3", "provider_model_name": "r",
             "tier": 0, "equivalence_group": "g0", "enabled": True},
            {"model_id": "x-alt", "provider": "p9", "provider_model_name": "x",
             "tier": 0, "equivalence_group": "g0", "enabled": True},
            {"model_id": "w", "provider": "p1", "provider_model_name": "w",
             "tier": 1, "equivalence_group": "g1", "enabled": True},
            {"model_id": "v-off", "provider": "p1", "provider_model_name": "v",
             "tier": 1, "equivalence_group": "g1", "enabled": False},
            {"model_id": "u", "provider": "p1", "provider_model_name": "u",
             "tier": 2, "equivalence_group": "g2", "enabled": True},
            {"model_id": "x-off", "provider": "p8", "provider_model_name": "x",
             "tier": 0, "equivalence_group": "g0", "enabled": False},
        ]
    }  # fmt: skip
    assert failover("x", cat, retiring=[{"model_id": "r"}]) == ("x-alt", "y", "w")
    assert failover("x", cat, retiring=()) == ("x-alt", "y", "r", "w")
    # The top tier has nothing above it; its group is just itself.
    assert failover("u", cat, retiring=()) == ()
    with pytest.raises(ValueError, match="not in the catalogue"):
        failover("nope", cat, retiring=())


# --- further tests ----------------------------------------------------------


def test_disabled_model_never_eligible():
    r = rules(candidates=["syn-off", "syn-premium", "syn-b"])
    assert eligible_models(row(), CATALOGUE, PRICES, r) == ("syn-b",)
    out = eligibility_frame(frame(), ctx(), rules=r, cached_separately=SEP)
    assert not out["syn-off"].any() and not out["syn-premium"].any()
    assert "syn-off" not in failover("syn-a", CATALOGUE, retiring=())


def test_attachments_or_functions_get_no_candidate():
    for over in (
        {"u_att_n": 1},
        {"u_att_n": NAN},  # unknown count counts as attachments
        {"u_att_n": None},
        {"bot_n_functions": 2},
        {"bot_n_functions": NAN},
    ):
        assert eligible_models(row(**over), CATALOGUE, PRICES, rules()) == ()
    missing = row()
    del missing["u_att_n"]
    assert eligible_models(missing, CATALOGUE, PRICES, rules()) == ()
    out = eligibility_frame(frame(), ctx(), rules=rules(), cached_separately=SEP)
    assert out.loc[5, REASON_COLUMN] == "attachments_unknown"
    assert out.loc[6, REASON_COLUMN] == "attachments"
    assert out.loc[7, REASON_COLUMN] == "functions"
    assert out.loc[3, REASON_COLUMN] == "workflow"


def test_eligibility_frame_matches_eligible_models_row_by_row():
    req = frame()
    out = eligibility_frame(req, ctx(), rules=rules(), cached_separately=SEP)
    assert list(out.columns) == ["syn-a", "syn-b", "syn-tiered", REASON_COLUMN]
    assert out.index.equals(req.index)
    tok = token_counts(req, SEP)
    for i in req.index[req["llm_request"]]:
        r = {
            "input_tokens": tok.loc[i, "input"],
            "output_tokens": tok.loc[i, "output"],
            "u_att_n": req.loc[i, "u_att_n"],
            "bot_n_functions": req.loc[i, "bot_n_functions"],
        }
        got = eligible_models(r, CATALOGUE, PRICES, rules())
        assert got == tuple(m for m in candidate_list(rules()) if out.loc[i, m]), i
        # The reason is empty exactly when some candidate is eligible.
        assert (out.loc[i, REASON_COLUMN] is None) == bool(got), i
    # Row 0 adds its cached tokens back (300 + 400 = 700 effective input).
    assert out.loc[0, "syn-a"]
    # Row 9: 990 + 20 > 1,000, so syn-a is out; syn-b fits.
    assert not out.loc[9, "syn-a"] and out.loc[9, "syn-b"]
    assert not out.loc[3].drop(REASON_COLUMN).any()  # workflow


def test_candidate_costs_sum_equals_baselines_repricing():
    req, c = frame(), ctx()
    elig = eligibility_frame(req, c, rules=rules(), cached_separately=SEP)
    costs = candidate_costs(
        req, c, ["syn-a", "syn-b", "syn-tiered"], rules=rules(), cached_separately=SEP
    )
    assert list(costs.columns) == ["syn-a", "syn-b", "syn-tiered"]
    for model in costs.columns:
        assert costs[model].isna().equals(~elig[model])
        ref = repriced_row_costs(
            req,
            c,
            premium_model="syn-premium",
            cached_separately=SEP,
            cheap_model=model,
        )["best_single_cheap"]
        assert math.fsum(costs[model].dropna()) == pytest.approx(
            math.fsum(ref[elig[model]]), rel=1e-12, abs=0
        )
        assert np.allclose(costs[model].dropna(), ref[elig[model]], rtol=0, atol=0)
    # Row 0 adds cached tokens back: (700 - 400) x 2 + 400 x 0.1 + 20 x 4.
    assert costs.loc[0, "syn-b"] == pytest.approx((600 + 40 + 80) / 1e6)
    with pytest.raises(ValueError, match="not a routing candidate"):
        candidate_costs(req, c, ["syn-off"], rules=rules(), cached_separately=SEP)


def test_matches_b_interim_rules():
    """Pipeline B's interim cases (``test_interim_eligibility`` of R-B3), ported
    as fixtures: same catalogue, prices, rules and rows; same answers. The
    shared base adds ``avoid_long_context_tier`` (no tier here, so inert)."""
    b_prices = {
        "version": "prices-synthetic",
        "per_tokens": 1_000_000,
        "prices": [
            {
                "price_ref": "p-cheap",
                "input": "1",
                "output": "2",
                "cached_input": "0.5",
            },
            {"price_ref": "p-mid", "input": "2", "output": "4", "cached_input": "1"},
            {"price_ref": "p-dear", "input": "4", "output": "8", "cached_input": "2"},
        ],
    }
    cat = {
        "models": [
            {"model_id": "a", "price_ref": "p-cheap", "enabled": True}
            | _limits(1000, 100),
            {"model_id": "b", "price_ref": "p-mid", "enabled": True},  # no limits
            {"model_id": "c", "price_ref": "p-none", "enabled": True}
            | _limits(10**6, 10**5),
            {"model_id": "r", "price_ref": "p-dear", "enabled": True}
            | _limits(10**6, 10**5),
        ]
    }
    r = {
        "candidates": ["a", "b", "c", "r", "z"],
        "retiring": ["r"],
        "avoid_long_context_tier": True,
    }
    base = {
        "input_tokens": 800.0,
        "output_tokens": 50.0,
        "u_att_n": 0,
        "bot_n_functions": 0,
    }
    assert eligible_models(base, cat, b_prices, r) == ("a",)
    assert eligible_models({**base, "input_tokens": 990.0}, cat, b_prices, r) == ()
    assert eligible_models({**base, "u_att_n": 1}, cat, b_prices, r) == ()
    assert eligible_models({**base, "bot_n_functions": 2}, cat, b_prices, r) == ()
    assert eligible_models({**base, "input_tokens": NAN}, cat, b_prices, r) == ()


def test_sprint_config_and_replay_catalogue_load():
    """The committed config works as ``rules`` and ``catalogue`` unchanged."""
    sprint = tomllib.loads(
        (ROOT / "config/evaluation/sprint.toml").read_text(encoding="utf-8")
    )
    routing = sprint["routing"]
    assert routing["avoid_long_context_tier"] is True
    assert candidate_list(routing) == tuple(routing["candidates"])
    cat = tomllib.loads(
        (ROOT / sprint["baselines"]["catalogue"]).read_text(encoding="utf-8")
    )
    # tier and equivalence_group are placeholders (A-48); disabled models and
    # the retiring one never appear; no tier above 1 is enabled.
    assert failover("gpt-5-nano", cat, retiring=routing["retiring"]) == (
        "gpt-4.1-nano",
        "mimo-v2.5",
        "gpt-4o-mini",
        "deepseek-v4-flash",
    )
    assert failover("gpt-4o-mini", cat, retiring=routing["retiring"]) == (
        "deepseek-v4-flash",
    )
