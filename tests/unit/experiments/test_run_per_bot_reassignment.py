"""Offline logic of ``scripts/run_per_bot_reassignment.py`` (R-A3).

Every frame here is [SYNTHETIC]: ``bot-a``-style labels stand in for bot IDs and
``m-cheap``-style names for models. The script is loaded with ``importlib``
(scripts are not a package), as in ``test_run_reranker_cut.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def rp():
    name = "run_per_bot_reassignment_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "run_per_bot_reassignment.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# [SYNTHETIC] implied recorded-basis rates (per 1M tokens).
RATES = pd.DataFrame(
    {
        "model": ["m-cheap", "m-dear", "m-rare"],
        "items": [20_000, 50_000, 10],
        "implied_input_per_M": [1.0, 10.0, 0.01],
        "implied_output_per_M": [2.0, 20.0, 0.01],
        "implied_cached_per_M": [np.nan, 5.0, 0.01],
    }
)


def billed(**cols) -> pd.DataFrame:
    """Four [SYNTHETIC] billed rows; keywords override."""
    base = {
        "a_billing_state": ["items"] * 4,
        "a_n_token_items": [1, 1, 1, 0],
        "bot_provider_model": ["m-dear", "m-dear", "m-cheap", "m-dear"],
        "a_bill_inputTokens": [1_000_000.0, 1_000_000.0, 1_000_000.0, 5.0],
        "a_bill_cachedInputTokens": [0.0, 500_000.0, 0.0, 0.0],
        "a_bill_outputTokens": [0.0, 0.0, 0.0, 0.0],
        "a_bill_totalCost": [10.002, 7.5, 0.5, 9.0],
        "a_n_per_call_only_items": [1.0, 0.0, 0.0, 0.0],
        "u_n_chars": [50.0, 500.0, 50.0, 50.0],
        "a_rag_n_chunks": [0.0, 0.0, 0.0, 0.0],
        "u_att_n": [0.0, 0.0, 0.0, 0.0],
        "a_tool_n_calls": [0.0, 0.0, 0.0, 0.0],
        "a_input_n_items": [0.0, 0.0, 0.0, 0.0],
        "a_is_json": [False, False, False, False],
    }
    base.update(cols)
    return pd.DataFrame(base)


def test_eda_target_is_the_cheapest_high_volume_model_by_blend(rp):
    # m-rare is cheaper but has under 10,000 items, so it is not a target.
    assert rp.eda_target(RATES)["model"] == "m-cheap"


def test_eda_simulation_reproduces_the_eda_rule(rp):
    sim = rp.eda_simulation(billed(), RATES)
    # Row 4 has no token item: out of the EDA population.
    assert sim["n_billed"] == 3
    assert sim["recorded_cost"] == pytest.approx(10.002 + 7.5 + 0.5)
    # At m-cheap's rates (no cached rate: cached tokens at the input rate, and
    # cached tokens are NOT added back, as in the EDA): 1.0 per row.
    # Savings: row 1 token cost 10.0 - 1.0 = 9.0; row 2 7.5 - 1.0 = 6.5; row 3
    # 0.5 - 1.0 < 0, clipped to 0 (never upward).
    assert sim["save_all_billed"] == pytest.approx(15.5)
    assert sim["share_all_billed"] == pytest.approx(15.5 / 18.002)
    # Only rows 1 and 3 match the simple rule (row 2 is long).
    assert sim["n_simple_rule"] == 2
    assert sim["share_simple_rule"] == pytest.approx(9.0 / 18.002)
    assert sim["simple_rule_already_on_target"] == pytest.approx(0.5)


def test_eda_simulation_adds_cached_tokens_back_as_the_eda_frame_does(rp):
    # The EDA's frame adds cached tokens to input for the models that report them
    # outside the input count (full_eda_analyze._cached_convention).
    rows = billed(
        bot_provider_model=["m-sep"] * 4,
        a_bill_inputTokens=[100_000.0] * 4,
        a_bill_cachedInputTokens=[900_000.0] * 4,
        a_bill_totalCost=[10.0] * 4,
        a_n_per_call_only_items=[0.0] * 4,
    )
    sim = rp.eda_simulation(rows, RATES, cached_separately=frozenset({"m-sep"}))
    # Effective input 1M at m-cheap's input rate (no cached rate): 1.0 per row.
    assert sim["save_all_billed"] == pytest.approx(3 * 9.0)
    plain = rp.eda_simulation(rows, RATES)
    # Without the add-back, cached tokens are capped at the 0.1M raw input.
    assert plain["save_all_billed"] == pytest.approx(3 * 9.9)


def test_eda_simulation_at_another_target(rp):
    target = RATES.set_index("model").loc["m-dear"].rename("m-dear")
    sim = rp.eda_simulation(billed(), RATES, target=target)
    assert sim["target"] == "m-dear"
    # m-dear: 10.0 per row on rows 1 and 3; row 2: 0.5M x 10 + 0.5M x 5 = 7.5.
    assert sim["save_all_billed"] == pytest.approx(0.0)


# --- R-A3 results --------------------------------------------------------------------

POINT_6 = "follows ADR-0046 point 6, provisional; owner to confirm (Q-B21)"
INTERIM = "interim eligibility, not the shared routing base"
# [SYNTHETIC] implied recorded-basis rates per 1M tokens.
RATES_T = {"cheap": {"input": 0.5, "output": 1.0, "cached": 0.25}}
CATALOGUE = {
    "version": "cat-synthetic",
    "models": [
        {"model_id": m, "price_ref": f"p-{m}", "enabled": True}
        for m in ("cheap", "mid", "dear", "prem", "ghost")
    ],
}
PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1_000_000,
    "prices": [
        {"price_ref": "p-cheap", "input": "1", "output": "2", "cached_input": "0.5"},
        {"price_ref": "p-mid", "input": "2", "output": "4", "cached_input": "1"},
        {"price_ref": "p-dear", "input": "4", "output": "8", "cached_input": "2"},
        {"price_ref": "p-prem", "input": "40", "output": "80", "cached_input": "4"},
    ],
}


def ctx():
    from metis_auto.analysis.levers import ReplayContext

    return ReplayContext(
        period_bounds={
            "tune": (pd.Timestamp("2026-03-01"), pd.Timestamp("2026-07-31 23:59")),
            "report": (pd.Timestamp("2026-08-01"), pd.Timestamp("2026-10-31 23:59")),
        },
        price_table=PRICES,
        catalogue=CATALOGUE,
        seed=7,
        min_n=None,
    )


def requests() -> pd.DataFrame:
    """[SYNTHETIC] report rows: bot-a (dear, 4 rows) is switched to cheap, bot-b
    (cheap) stays, bot-g runs an unpriced model, and one workflow row."""
    from metis_auto.analysis.levers import with_blocks

    bots = ["bot-a"] * 4 + ["bot-b"] * 3 + ["bot-g"] * 2 + ["bot-w"]
    models = ["dear"] * 4 + ["cheap"] * 3 + ["ghost"] * 2 + ["workflow"]
    n = len(bots)
    frame = pd.DataFrame(
        {
            "session_id": [f"s{i}" for i in range(n)],
            "bot_id": bots,
            "user_id": ["user-a"] * 6 + ["user-b"] * 4,
            "u_lang": ["fa"] * 5 + ["en"] * 5,
            "u_att_n": [0.0] * n,
            "bot_n_functions": [0.0] * n,
            "bot_provider_model": models,
            "a_bill_inputTokens": [1000.0] * 3 + [9000.0] + [1000.0] * 5 + [np.nan],
            "a_bill_cachedInputTokens": [0.0] * (n - 1) + [np.nan],
            "a_bill_outputTokens": [100.0] * (n - 1) + [np.nan],
            "a_bill_totalCost": [0.01] * (n - 1) + [np.nan],
            "a_n_per_call_only_items": [1.0] * n,
            "llm_request": [True] * (n - 1) + [False],
            "a_order": list(range(n)),
            "u_n_chars": [50.0] * n,
            "a_rag_n_chunks": [0.0] * n,
            "a_tool_n_calls": [0.0] * n,
            "a_input_n_items": [0.0] * n,
            "a_is_json": [False] * n,
        }
    )
    return with_blocks(frame)


@pytest.fixture(scope="module")
def run(rp, load_experiment):
    from metis_auto.analysis.lever_result import build_manifest
    from metis_auto.analysis.levers import combine

    v = load_experiment("routing/exp-route-001-per-bot-reassignment/version.py")

    def allow_all(row, catalogue, prices, rules):
        return tuple(rules["candidates"])

    req = requests()
    fitted = v.PerBotReassignment(
        ("cheap", "mid"), constraints=allow_all, rules={"candidates": []}
    ).fit(req, ctx(), premium_model="prem", cheap_model="cheap", rates=RATES_T)
    after = combine(req, None, None, fitted, ctx())
    manifests = {
        b: build_manifest(
            {"baseline": b},
            ctx(),
            code_commit="abc1234",
            python_version="3.13.9",
            created_at=pd.Timestamp("2026-11-03", tz="UTC").to_pydatetime(),
        )
        for b in rp.BASELINES
    }
    results = rp.lever_results(
        req,
        after,
        ctx(),
        fitted=fitted,
        premium_model="prem",
        cheap_model="cheap",
        cached_separately=frozenset(),
        rates=RATES_T,
        manifests=manifests,
        extra=("[SYNTHETIC] run note",),
    )
    return {"req": req, "after": after, "results": results, "fitted": fitted}


ONE = {
    "dear": (1000 * 4 + 100 * 8) / 1e6,
    "cheap": (1000 * 1 + 100 * 2) / 1e6,
    "prem": (1000 * 40 + 100 * 80) / 1e6,
}
LONG = {
    "dear": (9000 * 4 + 100 * 8) / 1e6,
    "cheap": (9000 * 1 + 100 * 2) / 1e6,
    "prem": (9000 * 40 + 100 * 80) / 1e6,
}


def test_results_for_all_four_baselines_in_their_own_units(run):
    results = run["results"]
    assert set(results) == {
        "premium_gpt_5_5",
        "as_logged",
        "todays_models",
        "best_single_cheap",
    }
    for key, r in results.items():
        assert r.step == "routing" and r.lever_id == "route.per_bot"
        if key == "as_logged":
            assert set(r.baseline_cost) == {"fees", "token_cost", "total"}
            assert r.saving["fees"] == 0
        else:
            assert "fees" not in r.baseline_cost and "fees" not in r.saving


def test_each_saving_is_the_routers_own_effect(run):
    r = run["results"]
    # todays_models: bot-a (dear) moves to cheap; bot-b already runs cheap.
    bot_a_dear = 3 * ONE["dear"] + LONG["dear"]
    bot_a_cheap = 3 * ONE["cheap"] + LONG["cheap"]
    today = r["todays_models"]
    assert float(today.baseline_cost["token_cost"]) == pytest.approx(
        bot_a_dear + 3 * ONE["cheap"]
    )
    assert float(today.saving["token_cost"]) == pytest.approx(bot_a_dear - bot_a_cheap)
    # premium: both priced bots move from prem to cheap (the router's effect in
    # that baseline, not the gap between baselines).
    prem = r["premium_gpt_5_5"]
    assert float(prem.saving["token_cost"]) == pytest.approx(
        (6 * ONE["prem"] + LONG["prem"]) - (6 * ONE["cheap"] + LONG["cheap"])
    )
    # best_single_cheap: the target is the baseline model, so nothing moves.
    assert float(r["best_single_cheap"].saving["token_cost"]) == 0
    # as_logged: recorded token cost 0.008 per row; cheap at implied rates.
    logged = r["as_logged"]
    implied = (3 * (1000 * 0.5 + 100 * 1.0) + (9000 * 0.5 + 100 * 1.0)) / 1e6
    assert float(logged.saving["token_cost"]) == pytest.approx(4 * 0.008 - implied)
    assert float(logged.baseline_cost["total"]) == pytest.approx(9 * 0.01)
    assert logged.slices["routing"]["n_saving_unknown"] == 0
    for res in r.values():
        assert res.slices["routing"]["n_switched_in_baseline"] >= 0
    assert prem.slices["routing"]["n_switched_in_baseline"] == 7
    assert today.slices["routing"]["n_switched_in_baseline"] == 4
    assert float(today.slices["over_8k"]["n_requests"]) == 1
    assert "eda_simple_rule" in logged.slices


def test_saving_by_target_model_is_reported(run):
    routing = run["results"]["todays_models"].slices["routing"]
    total = run["results"]["todays_models"].saving["token_cost"]
    assert routing["saving_by_target:cheap"] == total


def test_assumptions_name_point_6_and_r0_not_the_interim_rules(run):
    for r in run["results"].values():
        assert any(POINT_6 in a for a in r.assumptions)
        assert not any(INTERIM in a for a in r.assumptions)
        assert "quality not proven; cost simulation only" in r.assumptions
        assert r.evidence_class == "simulation"
        assert r.correctness_state == "unmeasured"
        assert not any("moved" in k for k in r.slices["routing"])


def test_per_bot_rows_use_rank_labels_not_ids(rp, run):
    table = rp.bot_table(run["after"], run["fitted"])
    assert list(table["bot_rank"]) == ["bot-01", "bot-02", "bot-03"]
    text = table.to_csv(index=False)
    for raw in ("bot-a", "bot-b", "bot-g", "s1", "user-a"):
        assert raw not in text
    first = table.iloc[0]
    assert (first["incumbent"], first["candidate"]) == ("dear", "cheap")
    assert first["cost_per_request_after"] < first["cost_per_request_before"]
    assert table["quality"].eq("not proven").all()
    for r in run["results"].values():
        assert not any(k.startswith("bot_rank:bot-a") for k in r.slices)
        assert "bot_rank:1" in r.slices


def test_constraints_and_costs_come_from_routing_base(rp):
    from metis_auto.analysis import routing_base

    constraints, costs = rp.load_constraints()
    assert constraints is routing_base.eligible_models
    assert costs is routing_base.candidate_costs
    routing = {
        "candidates": ["a", "b"],
        "candidates_jev": [],
        "retiring": [{"model_id": "old", "replacement": "a"}],
        "avoid_long_context_tier": True,
    }
    assert rp.routing_rules({"routing": routing}) == routing


def test_manifest_rules_are_plain_values(rp):
    import datetime

    rules = {
        "candidates": ["a"],
        "retiring": [
            {"model_id": "old", "replacement": "a", "date": datetime.date(2026, 1, 1)}
        ],
        "avoid_long_context_tier": True,
    }
    assert rp.plain_rules(rules) == {
        "candidates": ["a"],
        "retiring": [{"model_id": "old", "replacement": "a"}],
        "avoid_long_context_tier": True,
    }


def test_implied_rates_load_per_model(rp, tmp_path):
    path = tmp_path / "rates.csv"
    RATES.to_csv(path, index=False)
    rates = rp.load_implied_rates(path)
    assert rates["m-cheap"] == {"input": 1.0, "output": 2.0, "cached": None}
    assert rates["m-dear"]["cached"] == 5.0
