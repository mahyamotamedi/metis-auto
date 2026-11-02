"""The four baselines on the full requests frame (final plan S-3; FR-EVAL-02).

Every frame, model name and price here is [SYNTHETIC]: invented numbers, no
dataset content, no real price.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.baselines_full import (
    BASELINE_KEYS,
    baseline_costs,
    best_single_cheap_model,
    cached_reported_separately,
)
from metis_auto.analysis.levers import ReplayContext

NAN = np.nan
PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1_000_000,
    "prices": [
        # syn-free is the cheapest, but it is disabled (not callable).
        {
            "price_ref": "p-free",
            "input": "0.001",
            "output": "0.001",
            "cached_input": "0",
        },
        {"price_ref": "p-small", "input": "1", "output": "2", "cached_input": "0.5"},
        {"price_ref": "p-mid", "input": "2", "output": "4", "cached_input": "1"},
        {"price_ref": "p-premium", "input": "10", "output": "20", "cached_input": "5"},
    ],
}
CATALOGUE = {
    "models": [
        {"model_id": "syn-free", "price_ref": "p-free", "enabled": False},
        {"model_id": "syn-small", "price_ref": "p-small", "enabled": True},
        {"model_id": "syn-mid", "price_ref": "p-mid", "enabled": True},
        {"model_id": "syn-premium", "price_ref": "p-premium", "enabled": False},
        {"model_id": "syn-unpriced", "price_ref": "p-missing", "enabled": True},
    ]
}


def ctx() -> ReplayContext:
    return ReplayContext(
        period_bounds={},
        price_table=PRICES,
        catalogue=CATALOGUE,
        seed=7,
    )


def frame() -> pd.DataFrame:
    """[SYNTHETIC] Row 3 is a workflow row; row 4 is an LLM row with unknown
    tokens and cost; row 2 runs a model with no price."""
    return pd.DataFrame(
        {
            "llm_request": [True, True, True, False, True],
            "bot_provider_model": [
                "syn-mid",
                "syn-small",
                "syn-other",
                "default",
                "syn-mid",
            ],
            "a_bill_inputTokens": [1_000_000, 2_000_000, 1_000_000, NAN, NAN],
            "a_bill_cachedInputTokens": [0, 1_000_000, 0, NAN, NAN],
            "a_bill_outputTokens": [1_000_000, 0, 1_000_000, NAN, NAN],
            "a_bill_totalCost": [0.5, 0.25, 0.75, NAN, NAN],
            "a_n_per_call_only_items": [1, 0, 2, NAN, NAN],
        }
    )


def test_best_single_cheap_model_baseline_uses_only_callable_models():
    req = frame()
    # syn-free is cheaper but disabled; syn-unpriced has no price; syn-premium
    # is disabled. The cheapest callable model is syn-small.
    assert best_single_cheap_model(req, ctx()) == "syn-small"
    out = baseline_costs(req, ctx(), premium_model="syn-premium")
    # syn-small on the three known-token LLM rows:
    # row 0: 1M in + 1M out = 1 + 2 = 3; row 1: 1M uncached + 1M cached = 1 + 0.5;
    # row 2: 1 + 2 = 3. Total 7.5.
    assert out["best_single_cheap"]["token_cost"] == Decimal("7.5")
    assert out["best_single_cheap"]["n_unknown"] == Decimal(1)


def test_four_baselines_with_two_cost_blocks():
    out = baseline_costs(frame(), ctx(), premium_model="syn-premium")
    assert tuple(out) == BASELINE_KEYS
    logged = out["as_logged"]
    # Recorded units: fees are 0.002 per per-call item (levers.with_blocks).
    assert logged["fees"] == Decimal("0.006")
    assert logged["token_cost"] == Decimal("1.494")
    assert logged["total"] == Decimal("1.5")
    assert logged["n_requests"] == Decimal(4)  # workflow row never counted
    assert logged["n_unknown"] == Decimal(1)  # unknown is never zero
    # Repriced baselines carry no fee block: per-call fees are not on the
    # token price list, and recorded units are never mixed with repriced ones.
    for key in ("premium_gpt_5_5", "todays_models", "best_single_cheap"):
        assert "fees" not in out[key]
        assert out[key]["total"] == out[key]["token_cost"]
    # Premium: 10 + 20; 10 + 5; 10 + 20 = 75.
    assert out["premium_gpt_5_5"]["token_cost"] == Decimal("75")
    # Today's models: row 0 at syn-mid (2 + 4 = 6), row 1 at syn-small (1.5);
    # row 2's model has no price, so it is unknown, not zero.
    assert out["todays_models"]["token_cost"] == Decimal("7.5")
    assert out["todays_models"]["n_unknown"] == Decimal(2)


def test_cached_tokens_added_back_for_models_that_report_them_separately():
    req = frame()
    out = baseline_costs(
        req,
        ctx(),
        premium_model="syn-premium",
        cached_separately=frozenset({"syn-small"}),
    )
    # Row 1 (syn-small) now has 2M uncached + 1M cached input at premium prices:
    # 20 + 5 instead of 10 + 5.
    assert out["premium_gpt_5_5"]["token_cost"] == Decimal("85")


def test_cached_convention_detected_from_billed_rows():
    req = pd.DataFrame(
        {
            "bot_provider_model": ["m-sep"] * 3 + ["m-incl"] * 3,
            "a_billing_state": ["items"] * 6,
            "a_bill_inputTokens": [10, 10, 10, 100, 100, 100],
            "a_bill_cachedInputTokens": [50, 50, 0, 50, 0, 0],
        }
    )
    assert cached_reported_separately(req) == frozenset({"m-sep"})


def test_repriced_row_costs_sum_to_baseline_costs():
    from metis_auto.analysis.baselines_full import repriced_row_costs

    req = frame()
    sep = frozenset({"syn-small"})
    totals = baseline_costs(
        req, ctx(), premium_model="syn-premium", cached_separately=sep
    )
    rows = repriced_row_costs(
        req, ctx(), premium_model="syn-premium", cached_separately=sep
    )
    for key in ("premium_gpt_5_5", "todays_models", "best_single_cheap"):
        assert Decimal(str(rows[key].sum())) == totals[key]["token_cost"]
        assert int(rows[key].notna().sum()) == int(totals[key]["n_known"])


def test_unpriced_premium_model_is_refused():
    with pytest.raises(ValueError, match="price"):
        baseline_costs(frame(), ctx(), premium_model="syn-unpriced")


def test_model_row_costs_equals_the_repriced_column_of_that_model():
    """R-0 helper: one model's per-row cost is the same rule as the repriced
    baselines (``best_single_cheap`` fixed to that model)."""
    from metis_auto.analysis.baselines_full import model_row_costs, repriced_row_costs

    req = frame()
    sep = frozenset({"syn-small"})
    for model in ("syn-small", "syn-mid"):
        got = model_row_costs(req, ctx(), model, cached_separately=sep)
        ref = repriced_row_costs(
            req,
            ctx(),
            premium_model="syn-premium",
            cached_separately=sep,
            cheap_model=model,
        )["best_single_cheap"]
        pd.testing.assert_series_equal(got, ref, check_names=False)
    assert (
        model_row_costs(req, ctx(), "syn-unpriced", cached_separately=sep).isna().all()
    )
