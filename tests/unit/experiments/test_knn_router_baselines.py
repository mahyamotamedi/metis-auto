"""R-B3 per-baseline accounting (ADR-0046 points 4 to 6, as R-A3 and R-C3;
owner decision for Pipeline B, 2026-11-03). Every frame, catalogue and rate
here is SYNTHETIC.

Traces: plan R-B3 and "Routing without quality labels", FR-ROUTE-01,
FR-ROUTE-05, ADR-0036, ADR-0045, ADR-0046, ADR-0048, ADR-0051.
"""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_knn_router import CATALOGUE, allow_all, ctx, frame

from metis_auto.analysis import routing_base
from metis_auto.analysis.baselines_full import baseline_costs, repriced_row_costs
from metis_auto.analysis.lever_result import LeverResult

ROOT = Path(__file__).resolve().parents[3]
VERSION = "routing/exp-route-011-knn-router/version.py"
RUN = "routing/exp-route-011-knn-router/run.py"
CREATED = datetime(2026, 11, 3, tzinfo=UTC)
REPRICED = ("premium_gpt_5_5", "todays_models", "best_single_cheap")
BASELINES = ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap")
# [SYNTHETIC] implied recorded rates per 1M tokens; "mid" has no output rate.
RATES = {
    "cheap": {"input": 1.0, "cached": 0.5, "output": 2.0},
    "mid": {"input": 2.0, "cached": 1.0, "output": None},
    "dear": {"input": 4.0, "cached": 2.0, "output": 8.0},
}


@pytest.fixture(scope="module")
def v(load_experiment):
    return load_experiment(VERSION)


@pytest.fixture(scope="module")
def run(load_experiment):
    return load_experiment(RUN)


def decided(n, targets, target_costs, **cols):
    """[SYNTHETIC] router output: ``n`` LLM rows with blocks and a target."""
    req = frame(n, **cols)
    req["block_fees"] = 0.002
    req["block_token_cost"] = req.pop("recorded") if "recorded" in req else 0.0050
    out = req.copy()
    out["route_target"] = pd.Series(targets, index=req.index, dtype=object)
    out["route_target_cost"] = pd.Series(target_costs, index=req.index, dtype=float)
    inc = repriced_row_costs(req, ctx(), premium_model="premium")["todays_models"]
    out["route_cost_incumbent"] = inc
    moved = out["route_target_cost"].lt(inc) & out["route_target"].notna()
    out["routed_model"] = req["bot_provider_model"].where(~moved, out["route_target"])
    out["route_reason"] = np.where(moved, "moved", "no_cheaper_candidate")
    out["route_cost_routed"] = inc.where(~moved, out["route_target_cost"])
    return req, out


def mixed(n=20):
    """[SYNTHETIC] two bots with the same request profiles, one logged on
    "cheap" and one on "dear": "dear" requests have "cheap" neighbours."""
    return frame(
        n,
        bot_id=["bot-a" if i % 2 else "bot-b" for i in range(n)],
        user_id=[f"user-{i % 3}" for i in range(n)],
        bot_provider_model=["cheap" if i % 2 else "dear" for i in range(n)],
        u_n_chars=[100.0 + (i // 2) for i in range(n)],
    )


def frames(v, req, out, key, cheap="cheap", rates=RATES):
    return v.baseline_frames(
        req,
        out,
        ctx(),
        baseline=key,
        premium_model="premium",
        cheap_model=cheap,
        cached_separately=frozenset(),
        rates=rates,
    )


def saving(before, after):
    cols = ["block_fees", "block_token_cost"]
    return before[cols].sum(axis=1, min_count=2) - after[cols].sum(axis=1, min_count=2)


def mid_cost(req):
    tok = (req["a_bill_inputTokens"] * 2 + req["a_bill_outputTokens"] * 4) / 1e6
    return tok.tolist()


def test_incumbent_is_the_baseline_model_per_baseline(v):
    req, out = decided(1, ["mid"], mid_cost(frame(1)))
    repriced = repriced_row_costs(
        req, ctx(), premium_model="premium", cheap_model="cheap"
    )
    for key in REPRICED:  # the "before" side is the baseline's own model
        before, after = frames(v, req, out, key)
        assert before["block_token_cost"].iloc[0] == pytest.approx(
            repriced[key].iloc[0]
        )
    moved = {k: bool(frames(v, req, out, k)[1][v.MOVED_B].iloc[0]) for k in REPRICED}
    # logged "dear" and premium are dearer than "mid"; "cheap" is cheaper.
    assert moved == {
        "todays_models": True,
        "premium_gpt_5_5": True,
        "best_single_cheap": False,
    }
    # as_logged: the incumbent is the recorded token cost (logged model).
    full = {"mid": {"input": 2.0, "cached": 1.0, "output": 4.0}}
    before, _ = frames(v, req, out, "as_logged", rates=full)
    assert before["block_token_cost"].iloc[0] == req["block_token_cost"].iloc[0]
    # The target equal to the baseline's model is never a move.
    _, after = frames(v, req, out, "best_single_cheap", cheap="mid")
    assert not after[v.MOVED_B].any()


def test_request_not_moved_saves_exactly_zero(v):
    req, out = decided(
        3,
        [None, "dear", "mid"],
        [np.nan, 0.0012, mid_cost(frame(1))[0]],
        bot_provider_model=["mid", "mid", "dear"],
    )
    for key in BASELINES:
        before, after = frames(v, req, out, key)
        s = saving(before, after)
        still = ~after[v.MOVED_B] & ~after[v.SAVING_UNKNOWN]
        assert (s[still] == 0.0).all(), key
        if key == "as_logged":  # fees never change
            pd.testing.assert_series_equal(before["block_fees"], after["block_fees"])


def test_saving_never_negative_row_by_row(v):
    req, out = decided(
        4,
        ["cheap", "dear", "mid", "cheap"],
        [0.0012, 0.0048, 0.0024, 0.0012],
        bot_provider_model=["dear", "mid", "cheap", "mid"],
        recorded=[0.001, 0.009, 0.0001, 0.003],
    )
    for key in BASELINES:
        before, after = frames(v, req, out, key, rates={"cheap": RATES["cheap"]})
        s = saving(before, after).dropna()
        assert (s >= 0).all(), key


def test_cheaper_is_tested_in_the_baselines_own_units(v):
    # Logged "dear"; target "cheap" is cheaper at list prices in both rows.
    # Row 0: recorded cost tiny, so at implied rates "cheap" is dearer.
    req, out = decided(
        2,
        ["cheap", "cheap"],
        [0.0012, 0.0012],
        recorded=[0.0001, 0.0100],
    )
    _, today = frames(v, req, out, "todays_models")
    _, logged = frames(v, req, out, "as_logged")
    assert today[v.MOVED_B].tolist() == [True, True]
    assert logged[v.MOVED_B].tolist() == [False, True]


def test_todays_models_saving_unchanged_by_the_new_definition(v, run):
    req = mixed()
    router = v.KnnRouter(
        k=3,
        train=req,
        candidates=("cheap", "mid"),
        eligible_models=allow_all,
        rules={"candidates": ["cheap", "mid"]},
    )
    after = router.apply(req, ctx())
    after["block_fees"], after["block_token_cost"] = 0.002, 0.005
    before_b, after_b = frames(v, after, after, "todays_models")
    new = saving(before_b, after_b)
    # Old definition: baseline cost minus routed cost on the rows it can price.
    priced = after["route_cost_incumbent"].notna()
    copy = after[priced].copy()
    copy["bot_provider_model"] = copy["routed_model"]
    old_base = baseline_costs(after[priced], ctx(), premium_model="premium")
    old_routed = baseline_costs(copy, ctx(), premium_model="premium")
    old = (
        old_base["todays_models"]["token_cost"]
        - old_routed["todays_models"]["token_cost"]
    )
    assert Decimal(f"{new.sum():.9f}") == old
    assert after_b[v.MOVED_B].equals(after["route_reason"].eq("moved"))
    assert after["route_reason"].eq("moved").any()


def test_reasoning_billed_candidates_excluded_from_primary(v):
    cat = {
        "models": [
            {**m, "capabilities": [{"name": v.REASONING_CAPABILITY}]}
            if m["model_id"] == "cheap"
            else m
            for m in CATALOGUE["models"]
        ]
    }
    assert v.reasoning_billed(cat) == frozenset({"cheap"})
    assert v.primary_candidates(["cheap", "mid", "dear"], cat) == ("mid", "dear")
    # The real catalogue decides which candidates are excluded (not hard-coded).
    sprint = tomllib.loads(
        (ROOT / "config" / "evaluation" / "sprint.toml").read_text(encoding="utf-8")
    )
    real = tomllib.loads(
        (ROOT / sprint["baselines"]["catalogue"]).read_text(encoding="utf-8")
    )
    candidates = sprint["routing"]["candidates"]
    hidden = v.reasoning_billed(real) & set(candidates)
    # gpt-4.1-nano and mimo-v2.5 left the candidates on 2026-11-03 (not callable).
    assert hidden == {"deepseek-v4-flash", "gpt-5-nano"}
    assert not {"gpt-4.1-nano", "mimo-v2.5"} & set(candidates)
    assert set(v.primary_candidates(candidates, real)) == set(candidates) - hidden


def results(v, run, *, with_reasoning=False, split="tune"):
    req = mixed()
    router = v.KnnRouter(
        k=3,
        train=req,
        candidates=("cheap", "mid"),
        eligible_models=allow_all,
        rules={"candidates": ["cheap", "mid"]},
    )
    after = router.apply(req, ctx())
    after["block_fees"], after["block_token_cost"] = 0.002, 0.004
    texts = run.lever_results_json(
        after,
        req,
        k=3,
        split=split,
        with_reasoning=with_reasoning,
        ctx=ctx(),
        premium_model="premium",
        cheap_model="cheap",
        cached_separately=frozenset(),
        rates=RATES,
        code_commit="abcdef1",
        python_version="3.13.5",
        created_at=CREATED,
    )
    return {k: LeverResult.from_json(t) for k, t in texts.items()}


def test_secondary_with_reasoning_models_result_is_labelled(v, run):
    primary = results(v, run)
    secondary = results(v, run, with_reasoning=True, split="report")
    assert {r.lever_id for r in primary.values()} == {
        f"rb3.knn-router.k-3.tune.{b}" for b in BASELINES
    }
    assert {r.lever_id for r in secondary.values()} == {
        f"rb3.knn-router.with_reasoning_models.k-3.report.{b}" for b in BASELINES
    }
    assert {r.version for r in primary.values()} == {"route.knn.k3"}
    assert {r.version for r in secondary.values()} == {
        "route.knn.with_reasoning_models.k3"
    }
    for r in secondary.values():
        assert any(v.WITH_REASONING_LABEL in a for a in r.assumptions)
    for r in primary.values():
        assert not any(v.WITH_REASONING_LABEL in a for a in r.assumptions)
        assert any("ADR-0046 point 6" in a for a in r.assumptions)


def test_as_logged_priced_at_implied_rates(v, run):
    # Row 0: target "cheap" at implied rates; row 1: target "mid" has no output
    # rate -> unknown; row 2: no target -> saves exactly 0.
    req, out = decided(
        3,
        ["cheap", "mid", None],
        [0.0012, 0.0024, np.nan],
        recorded=[0.009, 0.009, 0.009],
    )
    before, after = frames(v, req, out, "as_logged")
    implied = (1000 * 1.0 + 100 * 2.0) / 1e6
    assert after["block_token_cost"].iloc[0] == pytest.approx(implied)
    assert after[v.SAVING_UNKNOWN].tolist() == [False, True, False]
    assert before.iloc[1][["block_fees", "block_token_cost"]].isna().all()
    assert after.iloc[1][["block_fees", "block_token_cost"]].isna().all()
    assert saving(before, after).iloc[2] == 0.0
    known = ~after[v.SAVING_UNKNOWN]
    assert before.loc[known, "block_fees"].equals(after.loc[known, "block_fees"])
    # In the result: as_logged has a saving, in recorded units, and counts the unknown.
    res = results(v, run)["as_logged"]
    assert set(res.saving) == {"fees", "token_cost", "total"}
    assert res.saving["fees"] == Decimal(0)
    assert "n_saving_unknown" in res.slices["routing"]
    assert any("implied" in a for a in res.assumptions)


def test_jev_candidates_follow_routing_base(v):
    rules = {
        "candidates": ["cheap", "mid", "dear"],
        "candidates_jev": ["jev-synthetic"],
        "avoid_long_context_tier": True,
    }
    router = v.KnnRouter(
        k=1,
        train=frame(2),
        candidates=("cheap",),
        eligible_models=allow_all,
        rules=rules,
    )
    assert "candidates_jev" not in router.rules
    assert router.rules["candidates"] == ["cheap"]
    assert routing_base.candidate_list(router.rules) == ("cheap",)
    assert rules["candidates_jev"] == ["jev-synthetic"]  # the caller's rules unchanged


def test_repriced_result_has_no_recorded_unit_slice(v, run):
    for res in (results(v, run), results(v, run, with_reasoning=True)):
        for key, r in res.items():
            if key == "as_logged":
                continue
            assert "fees" not in r.baseline_cost and "fees" not in r.saving
            for name, values in r.slices.items():
                assert not any("fees" in k for k in values), (key, name)
