"""I-1, the sprint-final combined run: the engine (``experiments/pipelines/
sprint-final/run.py``). Every frame, version and number here is [SYNTHETIC].

Rules under test: recorded and repriced units are never added; a step is
"not computed" in units where it has no figure, never 0; routing is priced on
the post-context tokens (a stated assumption, ``PostContextRouting``); combined
never exceeds the sum of the compatible standalone parts; rows served from an
answer cache get no context or routing saving (Review Focus 1); the run needs
exactly the expected population.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.levers import ReplayContext, with_blocks

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "experiments/pipelines/sprint-final/run.py"
NAN = np.nan
BASELINES = ("as_logged", "premium_gpt_5_5", "todays_models", "best_single_cheap")


@pytest.fixture(scope="module")
def sf():
    name = "sprint_final_run_under_test"
    spec = importlib.util.spec_from_file_location(name, PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(name, None)


def ctx() -> ReplayContext:
    return ReplayContext(
        period_bounds={}, price_table={"version": "p-syn"}, catalogue={}, seed=1
    )


def frame(n: int = 6) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "llm_request": [True] * n,
            "session_id": [f"s{i}" for i in range(n)],
            "a_bill_inputTokens": [1000.0] * n,
            "a_bill_cachedInputTokens": [0.0] * n,
            "a_bill_outputTokens": [100.0] * n,
            "a_bill_totalCost": [1.0] * n,
            "a_n_per_call_only_items": [0] * n,
            "a_billing_state": ["items"] * n,
        },
        index=range(10, 10 + n),
    )
    return with_blocks(out)


# --- units ------------------------------------------------------------------------


def test_unit_cells_follow_the_cache_kind(sf):
    cells = sf.unit_cells("retrieval_cache")
    assert cells["as_logged"]["combined_steps"] == ("cache", "context", "routing")
    for key in ("premium_gpt_5_5", "todays_models", "best_single_cheap"):
        assert cells[key]["combined_steps"] == ("context", "routing")
        assert "cache" in cells[key]["not_computed"]
    answer = sf.unit_cells("answer_cache")
    for key in BASELINES:
        assert answer[key]["combined_steps"] == ("cache", "context", "routing")
        assert answer[key]["not_computed"] == {}


def test_no_cache_means_no_cache_cell(sf):
    cells = sf.unit_cells(None)
    assert cells["as_logged"]["combined_steps"] == ("context", "routing")
    assert "cache" not in cells["as_logged"]["not_computed"]


def test_parts_are_not_added_across_units(sf):
    parts = {
        "cache": {"as_logged": Decimal("2")},  # recorded fees only
        "context": {"as_logged": Decimal("3"), "todays_models": Decimal("5")},
        "routing": {"as_logged": Decimal("4"), "todays_models": Decimal("7")},
    }
    assert sf.sum_parts(parts, "as_logged") == Decimal("9")
    # the cache part has no price-file figure: it is left out, never read as 0
    assert sf.sum_parts(parts, "todays_models") == Decimal("12")
    assert sf.sum_parts({"cache": {}}, "todays_models") is None


# --- the sum rule -----------------------------------------------------------------


def test_sum_rule_equal_strict_and_violation(sf):
    ok = sf.sum_rule(Decimal("9"), [Decimal("4"), Decimal("5")])
    assert ok["holds"] and ok["equal"]
    strict = sf.sum_rule(Decimal("8"), [Decimal("4"), Decimal("5")])
    assert strict["holds"] and not strict["equal"]
    bad = sf.sum_rule(Decimal("10"), [Decimal("4"), Decimal("5")])
    assert not bad["holds"]
    with pytest.raises(ValueError, match="sum rule"):
        sf.require_sum_rule({"as_logged": bad})


# --- routing after context --------------------------------------------------------


class Router:
    name = "spy-router"
    step = "routing"

    def __init__(self):
        self.seen_input = None

    def apply(self, req, ctx):
        self.seen_input = req["a_bill_inputTokens"].copy()
        out = req.copy()
        out["route_reason"] = "moved"
        return out


def test_post_context_routing_sees_the_lowered_input(sf):
    req = frame(3)
    req["ctx_saved"] = [100.0, 0.0, NAN]
    router = Router()
    wrapped = sf.PostContextRouting(router, saved_column="ctx_saved")
    out = wrapped.apply(req, ctx())
    assert list(router.seen_input) == [900.0, 1000.0, 1000.0]  # unknown saves 0
    assert list(req["a_bill_inputTokens"]) == [1000.0] * 3  # the input is untouched
    assert list(out["a_bill_inputTokens"]) == [1000.0] * 3
    assert wrapped.step == "routing" and wrapped.name.endswith(".post-context")


def test_post_context_routing_never_goes_below_zero(sf):
    req = frame(1)
    req["ctx_saved"] = [5000.0]
    router = Router()
    sf.PostContextRouting(router, saved_column="ctx_saved").apply(req, ctx())
    assert router.seen_input.iloc[0] == 0.0


def test_post_context_frame_matches_what_routing_saw(sf):
    req = frame(2)
    req["ctx_saved"] = [250.0, NAN]
    assert list(sf.post_context_frame(req, "ctx_saved")["a_bill_inputTokens"]) == [
        750.0,
        1000.0,
    ]


# --- answer cache hits ------------------------------------------------------------


class HitCache:
    name = "syn-cache"
    step = "cache"

    def apply(self, req, ctx):
        out = req.copy()
        hit = pd.Series([True, False, False, False, False, False], index=req.index)
        out["served_from_cache"] = hit
        out.loc[hit, ["block_fees", "block_token_cost"]] = 0.0
        return out


class Cut:
    name = "syn-cut"
    step = "context"

    def apply(self, req, ctx):
        out = req.copy()
        out["ctx_saved"] = 100.0
        return out


def test_rows_served_from_an_answer_cache_get_no_context_or_routing(sf):
    from metis_auto.analysis.levers import combine

    out = combine(frame(), HitCache(), Cut(), Router(), ctx())
    served = out["served_from_cache"].astype(bool)
    assert served.sum() == 1
    assert out.loc[served, "ctx_saved"].isna().all()
    assert out.loc[served, "route_reason"].isna().all()
    assert sf.served_rows_untouched(out, ["ctx_saved", "route_reason"])
    out2 = out.copy()
    out2.loc[served, "ctx_saved"] = 5.0
    assert not sf.served_rows_untouched(out2, ["ctx_saved", "route_reason"])


# --- population -------------------------------------------------------------------


def test_the_run_needs_exactly_the_expected_population(sf):
    scored = pd.Series([True, True, False, True], index=[1, 2, 3, 4])
    assert sf.check_population(scored, expected=3) == 3
    with pytest.raises(ValueError, match="population"):
        sf.check_population(scored, expected=4)


# --- the whole loop, with synthetic members ---------------------------------------


def members(sf):
    def frames_part(step):
        def part(frame, out, baseline, rows):
            cols = ["block_fees", "block_token_cost"]
            diff = frame.loc[rows, cols].sum(axis=1) - out.loc[rows, cols].sum(axis=1)
            return Decimal(f"{float(diff.fillna(0).sum()):.9f}")

        return part

    cache = sf.Member(
        "cache",
        "syn-cache",
        HitCache(),
        frames_part("cache"),
        units=BASELINES,
        kind="answer_cache",
    )

    class Lower:
        name = "syn-lower"
        step = "context"

        def apply(self, req, ctx):
            out = req.copy()
            out["ctx_saved"] = 100.0
            out["block_token_cost"] = out["block_token_cost"] - 0.01
            return out

    context = sf.Member(
        "context",
        "syn-lower",
        Lower(),
        frames_part("context"),
        units=BASELINES,
        saved_column="ctx_saved",
    )

    class Move:
        name = "syn-move"
        step = "routing"

        def apply(self, req, ctx):
            out = req.copy()
            out["route_reason"] = "moved"
            out["block_token_cost"] = out["block_token_cost"] - 0.1
            return out

    routing = sf.Member(
        "routing", "syn-move", Move(), frames_part("routing"), units=BASELINES
    )
    return cache, context, routing


def test_run_pipeline_reports_alone_combined_and_the_sum_rule(sf):
    req = frame()
    scored = pd.Series(True, index=req.index)
    cache, context, routing = members(sf)
    out = sf.run_pipeline(
        "syn",
        req,
        scored,
        [cache, context, routing],
        ctx(),
        BASELINES,
    )
    assert out["versions"] == {
        "cache": "syn-cache",
        "context": "syn-lower",
        "routing": "syn-move",
    }
    cell = out["baselines"]["as_logged"]
    assert set(cell["steps"]) == {"cache", "context", "routing"}
    assert Decimal(cell["combined_total"]) <= Decimal(cell["standalone_sum"])
    assert cell["sum_rule"]["holds"]
    # the served row keeps nothing for context and routing: strictly below the sum
    assert out["checks"]["served_rows_untouched"] is True
    assert out["overlaps"]["cache"] == 1


def test_summary_is_content_free(sf):
    req = frame()
    scored = pd.Series(True, index=req.index)
    out = sf.run_pipeline("syn", req, scored, list(members(sf)), ctx(), BASELINES)
    text = json.dumps(out, default=str)
    for leaked in ("s0", "s1", "session"):
        assert leaked not in text.replace("sum_rule", "").replace("standalone", "")


def test_post_context_frame_lowers_the_recorded_cost_too_when_asked(sf):
    """A context version that leaves its recorded saving to be priced outside
    ``apply`` must not leave routing an incumbent whose recorded cost is still
    the full cost: routing would then gain the context saving."""
    req = frame(3)
    req["bot_provider_model"] = ["m-a", "m-b", "m-none"]
    req["ctx_saved"] = [200.0, 100.0, 50.0]
    rates = {"m-a": 1000.0, "m-b": 500.0}  # per 1M tokens
    out = sf.post_context_frame(req, "ctx_saved", rates=rates)
    cut = [200 * 1000 / 1e6, 100 * 500 / 1e6, 0.0]  # no rate: no cut (not 0 saved)
    want = req["block_token_cost"].to_numpy() - np.array(cut)
    assert np.allclose(out["block_token_cost"].to_numpy(), want)
    # tokens are lowered either way
    assert list(out["a_bill_inputTokens"]) == [800.0, 900.0, 950.0]
    # never below zero
    req["ctx_saved"] = [10**9] * 3
    low = sf.post_context_frame(req, "ctx_saved", rates=rates)
    assert (low["block_token_cost"] >= 0).all()


def test_a_context_that_already_lowers_the_blocks_is_not_cut_twice(sf):
    req = frame(2)
    req["bot_provider_model"] = ["m-a", "m-a"]
    req["ctx_saved"] = [100.0, 100.0]
    out = sf.post_context_frame(req, "ctx_saved", rates=None)
    assert np.allclose(out["block_token_cost"], req["block_token_cost"])
