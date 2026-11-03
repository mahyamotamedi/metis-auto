"""R-A3 per-bot reassignment, exp-route-001/version.py. [SYNTHETIC] frames only:
``bot-a``-style labels stand in for bot IDs, ``s1`` for sessions, ``cheap`` /
``mid`` / ``dear`` for models.

Traces: plan R-A3 (and its four tests), "Routing without quality labels",
FR-ROUTE-03, FR-ROUTE-05, Review Focus 1 and 3, ADR-0036, ADR-0045, ADR-0046.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis import routing_base
from metis_auto.analysis.baselines_full import token_counts
from metis_auto.analysis.levers import ReplayContext, combine, with_blocks

VERSION = "routing/exp-route-001-per-bot-reassignment/version.py"
R_C3 = "routing/exp-route-012-small-classifier/version.py"
REASONING = "hidden_reasoning_billed_as_output"

# [SYNTHETIC] price file: cheap < mid < dear < prem; "sep" reports cached tokens
# outside its input count; "ghost" is in the catalogue without a price; "think"
# carries the hidden-reasoning capability.
CATALOGUE = {
    "version": "cat-synthetic",
    "models": [
        {
            "model_id": m,
            "price_ref": f"p-{m}",
            "enabled": True,
            "context_window": {"value": 10_000},
            "max_output_tokens": {"value": 1_000},
        }
        | (
            {"capabilities": [{"name": REASONING, "verified": True}]}
            if m == "think"
            else {}
        )
        for m in ("cheap", "mid", "dear", "sep", "ghost", "prem", "think")
    ],
}
PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1_000_000,
    "prices": [
        {"price_ref": "p-cheap", "input": "1", "output": "2", "cached_input": "0.5"},
        {"price_ref": "p-mid", "input": "2", "output": "4", "cached_input": "1"},
        {"price_ref": "p-dear", "input": "4", "output": "8", "cached_input": "2"},
        {"price_ref": "p-sep", "input": "3", "output": "6", "cached_input": "0.1"},
        {"price_ref": "p-prem", "input": "40", "output": "80", "cached_input": "4"},
        {"price_ref": "p-think", "input": "0.5", "output": "1", "cached_input": "0.1"},
    ],
}
# [SYNTHETIC] implied recorded-basis rates per 1M tokens (as_logged).
RATES = {
    "cheap": {"input": 0.5, "output": 1.0, "cached": 0.25},
    "mid": {"input": 1.0, "output": 2.0, "cached": np.nan},
}


def ctx(min_n=None) -> ReplayContext:
    return ReplayContext(
        period_bounds={
            "tune": (pd.Timestamp("2026-03-01"), pd.Timestamp("2026-07-31 23:59")),
            "report": (pd.Timestamp("2026-08-01"), pd.Timestamp("2026-10-31 23:59")),
        },
        price_table=PRICES,
        catalogue=CATALOGUE,
        seed=7,
        min_n=min_n,
    )


def frame(n: int, **cols) -> pd.DataFrame:
    """``n`` [SYNTHETIC] LLM rows of one bot on ``dear``; keywords override."""
    base = {
        "session_id": [f"s{i}" for i in range(n)],
        "bot_id": ["bot-a"] * n,
        "user_id": ["user-a"] * n,
        "u_lang": ["fa"] * n,
        "u_att_n": [0.0] * n,
        "bot_n_functions": [0.0] * n,
        "bot_provider_model": ["dear"] * n,
        "a_bill_inputTokens": [1000.0] * n,
        "a_bill_cachedInputTokens": [0.0] * n,
        "a_bill_outputTokens": [100.0] * n,
        "a_bill_totalCost": [0.01] * n,
        "a_n_per_call_only_items": [1.0] * n,
        "llm_request": [True] * n,
    }
    base.update(cols)
    return with_blocks(pd.DataFrame(base))


def allow_all(row, catalogue, prices, rules):
    return tuple(rules["candidates"])


def r0_rules(candidates) -> dict:
    return {
        "candidates": list(candidates),
        "retiring": [],
        "avoid_long_context_tier": True,
    }


@pytest.fixture(scope="module")
def v(load_experiment):
    return load_experiment(VERSION)


def fitted(v, tune, candidates=("cheap", "mid"), constraints=allow_all, **kw):
    fit_kw = {
        k: kw.pop(k) for k in ("premium_model", "cheap_model", "rates") if k in kw
    }
    r = v.PerBotReassignment(
        candidates,
        constraints=constraints,
        rules=kw.pop("rules", {"candidates": list(candidates), "retiring": []}),
        **kw,
    )
    return r.fit(tune, ctx(), **fit_kw)


def r0_fitted(v, tune, candidates=("cheap", "mid"), **kw):
    """Fitted with R-0 itself: ``eligible_models`` and ``candidate_costs``."""
    return fitted(
        v,
        tune,
        candidates,
        constraints=routing_base.eligible_models,
        rules=r0_rules(candidates),
        costs=routing_base.candidate_costs,
        **kw,
    )


def frames(v, r, req, baseline, **kw):
    out = r.apply(req, ctx())
    args = {
        "premium_model": "prem",
        "cheap_model": "cheap",
        "cached_separately": frozenset(),
        "rates": RATES,
    } | kw
    return out, *v.baseline_frames(req, out, ctx(), r, baseline=baseline, **args)


def saving(before, after) -> pd.Series:
    cols = ["block_fees", "block_token_cost"]
    return before[cols].sum(axis=1, min_count=1) - after[cols].sum(axis=1, min_count=1)


# --- the plan's four tests ---------------------------------------------------------


def test_repricing_adds_cached_tokens_back_for_the_five_models(v):
    # "sep" reports 400 cached tokens outside its 100 input tokens (Review Focus 3).
    tune = frame(
        3,
        bot_provider_model=["sep"] * 3,
        a_bill_inputTokens=[100.0] * 3,
        a_bill_cachedInputTokens=[400.0] * 3,
        a_bill_outputTokens=[10.0] * 3,
    )
    r = fitted(v, tune, cached_separately=frozenset({"sep"}))
    out = r.apply(tune, ctx())
    tok = token_counts(tune, frozenset({"sep"}))
    assert tok["input"].iloc[0] == 500.0  # the shared rule adds them back
    expected_cheap = (
        (tok["input"] - tok["cached"]) * 1 + tok["cached"] * 0.5 + tok["output"] * 2
    ) / 1e6
    expected_sep = (
        (tok["input"] - tok["cached"]) * 3 + tok["cached"] * 0.1 + tok["output"] * 6
    ) / 1e6
    assert out["routed_model"].eq("cheap").all()
    np.testing.assert_allclose(out["route_cost_routed"], expected_cheap)
    np.testing.assert_allclose(out["route_cost_incumbent"], expected_sep)
    # Without the add-back the routed cost would be priced on 100 input tokens.
    plain = fitted(v, tune).apply(tune, ctx())
    assert (plain["route_cost_routed"] < out["route_cost_routed"]).all()


def test_fee_block_unchanged_by_routing(v):
    tune = frame(4)
    r = fitted(v, tune, premium_model="prem", cheap_model="cheap", rates=RATES)
    out = r.apply(tune, ctx())
    assert out["routed_model"].eq("cheap").all()
    # Recorded blocks are never overwritten by repriced (price-file) cost.
    pd.testing.assert_series_equal(out["block_fees"], tune["block_fees"])
    pd.testing.assert_series_equal(out["block_token_cost"], tune["block_token_cost"])
    assert out.index.equals(tune.index)
    # as_logged: the fee is the same on both sides.
    _, before, after = frames(v, r, tune, "as_logged")
    pd.testing.assert_series_equal(before["block_fees"], after["block_fees"])


def test_never_routes_upward(v):
    # Bot on "mid" with candidates "cheap" and "dear": only "cheap" is lower.
    tune = frame(4, bot_provider_model=["mid"] * 4)
    r = fitted(v, tune, candidates=("dear", "cheap"))
    assert r.bots.loc["bot-a", "chosen"] == "cheap"
    # Bot on "cheap": every candidate costs more on its traffic, so it stays.
    tune = frame(4, bot_provider_model=["cheap"] * 4)
    r = fitted(v, tune, candidates=("mid", "dear"))
    out = r.apply(tune, ctx())
    assert out["routed_model"].eq("cheap").all()
    assert out["route_reason"].eq("no_cheaper_candidate").all()
    # A chosen candidate is cheaper than the incumbent on the bot's tune traffic.
    tune = pd.concat(
        [frame(3, bot_id=["bot-b"] * 3), frame(3, bot_provider_model=["cheap"] * 3)],
        ignore_index=True,
    )
    bots = fitted(v, tune, candidates=("mid",)).bots
    chosen = bots[bots["chosen"].notna()]
    assert (chosen["cost_chosen"] < chosen["cost_incumbent"]).all()
    assert list(chosen.index) == ["bot-b"]
    # A request where the choice is dearer than its logged model keeps its model.
    report = frame(1, bot_id=["bot-b"], bot_provider_model=["cheap"])
    out = fitted(v, tune, candidates=("mid",)).apply(report, ctx())
    assert out["route_reason"].iloc[0] == "row_not_cheaper"
    assert out["routed_model"].iloc[0] == "cheap"


def test_uses_routing_base_constraints(v):
    calls = []

    def only_mid(row, catalogue, prices, rules):  # [SYNTHETIC] stub of R-0
        calls.append((dict(row), catalogue["version"], prices["version"], rules))
        return ("mid",)

    tune = frame(3)
    r = fitted(v, tune, constraints=only_mid)
    out = r.apply(tune, ctx())
    assert out["routed_model"].eq("mid").all()  # "cheap" is cheaper but not allowed
    row, cat, price, rules = calls[0]
    assert (cat, price) == ("cat-synthetic", "prices-synthetic")
    assert rules["candidates"] == ["cheap", "mid"]
    assert {"input_tokens", "output_tokens", "u_att_n", "bot_n_functions"} <= set(row)


def test_routing_base_rules_run_on_synthetic_rows(v):
    tune = pd.concat(
        [
            frame(3, bot_id=["bot-plain"] * 3),
            frame(3, bot_id=["bot-att"] * 3, u_att_n=[0.0, 1.0, 0.0]),
            frame(3, bot_id=["bot-fn"] * 3, bot_n_functions=[2.0] * 3),
            frame(3, bot_id=["bot-long"] * 3, a_bill_inputTokens=[20_000.0] * 3),
        ],
        ignore_index=True,
    )
    r = r0_fitted(v, tune)
    reason = r.bots["reason"]
    assert reason["bot-plain"] == "chosen"
    assert r.bots.loc["bot-plain", "chosen"] == "cheap"
    for bot in ("bot-att", "bot-fn", "bot-long"):
        assert reason[bot] == "no_eligible_candidate"
    out = r.apply(tune, ctx())
    why = v.no_eligible_why(out, ctx(), routing_base.eligible_models, r.rules)
    att = out["bot_id"].eq("bot-att") & out["u_att_n"].gt(0)
    assert why[att].eq("attachment").all()
    assert why[out["bot_id"].eq("bot-fn")].eq("functions").all()
    assert why[out["bot_id"].eq("bot-long")].eq("context_or_output_limit").all()
    assert why[out["bot_id"].eq("bot-plain")].isna().all()


def test_candidate_costs_path_equals_the_eligible_models_path(v):
    tune = pd.concat(
        [
            frame(4, bot_id=["bot-plain"] * 4),
            frame(3, bot_id=["bot-long"] * 3, a_bill_inputTokens=[20_000.0] * 3),
            frame(3, bot_id=["bot-mid"] * 3, bot_provider_model=["mid"] * 3),
        ],
        ignore_index=True,
    )
    rules = r0_rules(("cheap", "mid"))
    rows = fitted(v, tune, constraints=routing_base.eligible_models, rules=rules).apply(
        tune, ctx()
    )
    vec = r0_fitted(v, tune).apply(tune, ctx())
    cols = ["routed_model", "route_reason", "route_target", "route_target_cost"]
    pd.testing.assert_frame_equal(rows[cols], vec[cols])


def test_one_model_cost_equals_the_shared_repricing_rule(v):
    from metis_auto.analysis.baselines_full import repriced_row_costs

    req = frame(
        4,
        bot_provider_model=["sep", "dear", "sep", "cheap"],
        a_bill_cachedInputTokens=[400.0, 0.0, 50.0, 0.0],
    )
    sep = frozenset({"sep"})
    tok = token_counts(req, sep)
    for model in ("cheap", "mid", "dear"):
        shared = repriced_row_costs(
            req, ctx(), premium_model=model, cheap_model=model, tokens=tok
        )["premium_gpt_5_5"]
        pd.testing.assert_series_equal(
            v.cost_at(req, tok, model, ctx()), shared, check_names=False
        )
    assert v.cost_at(req, tok, "ghost", ctx()).isna().all()  # unpriced: unknown
    assert v.cost_at(req, tok, "not-listed", ctx()).isna().all()


def test_apply_prices_only_the_targets_it_needs(v):
    calls = []

    def costs(req, c, candidates, *, rules, cached_separately):
        calls.append(tuple(candidates))
        return routing_base.candidate_costs(
            req, c, candidates, rules=rules, cached_separately=cached_separately
        )

    tune = frame(3)
    r = fitted(
        v,
        tune,
        candidates=("cheap", "mid"),
        constraints=routing_base.eligible_models,
        rules=r0_rules(("cheap", "mid")),
        costs=costs,
    )
    calls.clear()
    r.apply(tune, ctx())
    assert calls == [("cheap",)]


def test_r0_rules_drop_the_jev_list(v):
    r = v.PerBotReassignment(
        ("cheap",),
        constraints=routing_base.eligible_models,
        rules=r0_rules(("cheap",)) | {"candidates_jev": ["mid"]},
    )
    assert "candidates_jev" not in r.rules
    assert routing_base.candidate_list(r.rules) == ("cheap",)


# --- ADR-0046 points 4 to 6 --------------------------------------------------------


def test_reasoning_billed_candidates_come_from_the_catalogue(v):
    assert v.reasoning_billed(CATALOGUE) == frozenset({"think"})
    assert v.primary_candidates(("think", "cheap", "mid"), CATALOGUE) == (
        "cheap",
        "mid",
    )


def test_each_baseline_saving_is_the_routers_own_effect(v):
    # bot-a runs dear, bot-b runs cheap (already the target): under todays_models
    # only bot-a moves; under premium both move, priced against prem, not logged.
    tune = pd.concat(
        [frame(3), frame(3, bot_id=["bot-b"] * 3, bot_provider_model=["cheap"] * 3)],
        ignore_index=True,
    )
    r = fitted(v, tune, premium_model="prem", cheap_model="cheap", rates=RATES)
    one_dear = (1000 * 4 + 100 * 8) / 1e6
    one_cheap = (1000 * 1 + 100 * 2) / 1e6
    one_prem = (1000 * 40 + 100 * 80) / 1e6
    _, b, a = frames(v, r, tune, "todays_models")
    assert saving(b, a).sum() == pytest.approx(3 * (one_dear - one_cheap))
    _, b, a = frames(v, r, tune, "premium_gpt_5_5")
    # bot-b's target "cheap" equals its logged model, but the premium incumbent is
    # "prem", so in that baseline it moves too.
    assert saving(b, a).sum() == pytest.approx(6 * (one_prem - one_cheap))
    _, b, a = frames(v, r, tune, "best_single_cheap")
    assert saving(b, a).sum() == pytest.approx(0.0)  # target == the baseline model


def test_row_saving_is_never_negative_in_any_baseline(v):
    rng = np.random.default_rng(3)
    n = 40
    tune = frame(
        n,
        bot_id=[f"bot-{i % 4}" for i in range(n)],
        bot_provider_model=[("dear", "mid", "cheap", "sep")[i % 4] for i in range(n)],
        a_bill_inputTokens=rng.integers(10, 5000, n).astype(float),
        a_bill_outputTokens=rng.integers(1, 500, n).astype(float),
        a_bill_totalCost=rng.uniform(0.0001, 0.05, n),
    )
    r = fitted(
        v,
        tune,
        candidates=("cheap", "mid"),
        premium_model="prem",
        cheap_model="cheap",
        rates=RATES,
    )
    for key in ("todays_models", "premium_gpt_5_5", "best_single_cheap", "as_logged"):
        _, b, a = frames(v, r, tune, key)
        s = saving(b, a).dropna()
        assert (s >= -1e-12).all(), key


def test_as_logged_unknown_when_a_rate_is_missing_and_zero_when_not_moved(v):
    # bot-a moves to "mid", which has no cached rate: rows with cached tokens are
    # unknown; bot-c's recorded cost is below mid's implied cost, so it is not
    # reassigned in as_logged and saves exactly 0.
    tune = pd.concat(
        [
            frame(3, a_bill_cachedInputTokens=[0.0, 200.0, 0.0]),
            frame(
                3,
                bot_id=["bot-c"] * 3,
                bot_provider_model=["cheap"] * 3,
                a_bill_totalCost=[0.0021] * 3,
            ),
        ],
        ignore_index=True,
    )
    r = fitted(
        v,
        tune,
        candidates=("mid",),
        premium_model="prem",
        cheap_model="cheap",
        rates=RATES,
    )
    _, b, a = frames(v, r, tune, "as_logged")
    unknown = a["route_saving_unknown"]
    assert unknown.tolist() == [False, True, False, False, False, False]
    assert b.loc[unknown, "block_token_cost"].isna().all()
    s = saving(b, a)
    c = tune["bot_id"].eq("bot-c")
    assert s[c].eq(0.0).all()
    mid_row = (1000 * 1.0 + 100 * 2.0) / 1e6
    recorded = tune.loc[0, "block_token_cost"]
    assert s.iloc[0] == pytest.approx(recorded - mid_row)


def test_matches_r_c3_on_todays_models_and_as_logged(v, load_experiment):
    c3 = load_experiment(R_C3)
    tune = pd.concat(
        [
            frame(4, a_bill_cachedInputTokens=[0.0, 50.0, 0.0, 0.0]),
            frame(3, bot_id=["bot-b"] * 3, bot_provider_model=["mid"] * 3),
        ],
        ignore_index=True,
    )
    r = fitted(v, tune, premium_model="prem", cheap_model="cheap", rates=RATES)
    out = r.apply(tune, ctx())
    for key in ("todays_models", "as_logged"):
        _, b, a = frames(v, r, tune, key)
        # The same rows are candidates for R-C3: its "simple" flag = our moved-or-
        # unknown candidates in this baseline.
        c_out = out.copy()
        c_out[c3.SIMPLE] = a["route_candidate"]
        cb, ca = c3.baseline_frames(
            tune,
            c_out,
            ctx(),
            baseline=key,
            premium_model="prem",
            cached_separately=frozenset(),
            cheap_model="cheap",
            rates=RATES,
        )
        assert a["route_moved_in_baseline"].any()
        pd.testing.assert_series_equal(
            a["route_moved_in_baseline"], ca[c3.MOVED_B], check_names=False
        )
        assert saving(b, a).sum() == pytest.approx(saving(cb, ca).sum())


# --- further tests -------------------------------------------------------------------


def test_identity_when_no_candidate_is_cheaper(v):
    tune = frame(5, bot_provider_model=["cheap"] * 5)
    out = fitted(v, tune, candidates=("mid", "dear")).apply(tune, ctx())
    assert out["routed_model"].eq(tune["bot_provider_model"]).all()
    pd.testing.assert_series_equal(
        out["route_cost_routed"], out["route_cost_incumbent"], check_names=False
    )


def test_insufficient_bot_is_never_reassigned(v):
    tune = pd.concat([frame(5), frame(2, bot_id=["bot-small"] * 2)], ignore_index=True)
    r = v.PerBotReassignment(
        ("cheap",), constraints=allow_all, rules={"candidates": ["cheap"]}
    ).fit(tune, ctx(min_n=3))
    assert r.bots.loc["bot-small", "reason"] == "insufficient_bot"
    assert pd.isna(r.bots.loc["bot-small", "chosen"])
    out = r.apply(tune, ctx(min_n=3))
    small = out["bot_id"].eq("bot-small")
    assert out.loc[small, "routed_model"].eq("dear").all()
    assert out.loc[small, "route_reason"].eq("insufficient_bot").all()
    assert out.loc[~small, "routed_model"].eq("cheap").all()


def test_unpriced_model_is_unknown_not_zero(v):
    tune = pd.concat(
        [frame(3), frame(3, bot_id=["bot-g"] * 3, bot_provider_model=["ghost"] * 3)],
        ignore_index=True,
    )
    # "ghost" as a candidate is never chosen; as an incumbent its cost is unknown.
    r = fitted(v, tune, candidates=("ghost", "cheap"))
    assert r.bots.loc["bot-a", "chosen"] == "cheap"
    assert r.bots.loc["bot-g", "reason"] == "incumbent_unpriced"
    out = r.apply(tune, ctx())
    g = out["bot_id"].eq("bot-g")
    assert out.loc[g, "route_cost_incumbent"].isna().all()
    assert out.loc[g, "route_cost_routed"].isna().all()
    assert out.loc[g, "route_reason"].eq("incumbent_unpriced").all()
    unknown = frame(2, bot_id=["bot-u"] * 2, a_bill_outputTokens=[np.nan, 5.0])
    out = fitted(v, tune).apply(pd.concat([tune, unknown], ignore_index=True), ctx())
    assert out["route_reason"].iloc[-2] == "unknown_tokens"
    assert np.isnan(out["route_cost_routed"].iloc[-2])


def test_cache_hit_rows_are_not_rerouted(v):
    class HitFirstTwo:  # [SYNTHETIC] cache version
        name, step = "cache.synthetic", "cache"

        def apply(self, req, c):
            out = req.copy()
            out["served_from_cache"] = [i < 2 for i in range(len(out))]
            out.loc[out["served_from_cache"], ["block_fees", "block_token_cost"]] = 0.0
            return out

    tune = frame(5)
    r = fitted(v, tune)
    out = combine(tune, HitFirstTwo(), None, r, ctx())
    hit = out["served_from_cache"]
    assert out.loc[hit, "routed_model"].isna().all()
    assert out.loc[hit, "route_cost_routed"].isna().all()
    assert out.loc[~hit, "routed_model"].eq("cheap").all()


def test_unseen_bot_and_row_outside_the_choice_keep_their_model(v):
    tune = frame(3)
    r = r0_fitted(v, tune)
    report = pd.concat(
        [
            frame(1, a_bill_inputTokens=[50_000.0]),  # too long for the choice
            frame(1, bot_id=["bot-new"]),
        ],
        ignore_index=True,
    )
    out = r.apply(report, ctx())
    assert list(out["route_reason"]) == ["row_not_eligible", "unseen_bot"]
    assert out["routed_model"].eq("dear").all()


def test_apply_needs_a_fit_and_candidates_stay_a_constructor_argument(v):
    r = v.PerBotReassignment(
        ("cheap", "jev-x"), constraints=allow_all, rules={"candidates": ["cheap"]}
    )
    assert r.rules["candidates"] == ["cheap", "jev-x"]  # J-3 passes candidates_jev
    with pytest.raises(ValueError, match="fit"):
        r.apply(frame(1), ctx())
    assert r.step == "routing"
    assert "quality not proven; cost simulation only" in v.ASSUMPTIONS
