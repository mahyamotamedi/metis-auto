"""R-B3 run helpers (exp-route-011/run.py): folds, nested CV, repricing and
``LeverResult`` files. SYNTHETIC only. Traces: plan R-B3, ADR-0036, ADR-0032."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest
from test_knn_router import CATALOGUE, allow_all, ctx, frame

from metis_auto.analysis.lever_result import LeverResult

RUN = "routing/exp-route-011-knn-router/run.py"
CREATED = datetime(2026, 11, 2, tzinfo=UTC)


@pytest.fixture(scope="module")
def run(load_experiment):
    return load_experiment(RUN)


def population(n=40, seed=0):
    """Two kinds of request: short ones (logged on "cheap" by one bot) and
    long ones (on "dear" by another)."""
    rng = np.random.default_rng(seed)
    short = rng.random(n) < 0.5
    return frame(
        n,
        session_id=[f"s{i // 2}" for i in range(n)],
        bot_id=np.where(short, "bot-a", "bot-b").tolist(),
        user_id=[f"user-{i % 3}" for i in range(n)],
        u_h_norm=[f"q{i // 4}" for i in range(n)],  # joins session pairs
        u_n_chars=np.where(short, 20.0, 2000.0).tolist(),
        bot_provider_model=np.where(short, "cheap", "dear").tolist(),
    )


def make(load_experiment):
    v = load_experiment("routing/exp-route-011-knn-router/version.py")

    def factory(train, k):
        return v.KnnRouter(
            k=k,
            train=train,
            candidates=("cheap", "mid"),
            eligible_models=allow_all,
            rules={"candidates": ["cheap", "mid"]},
        )

    return factory


def test_folds_keep_sessions_and_families_together(run):
    req = frame(
        6,
        session_id=["a", "a", "b", "c", "d", "e"],
        u_h_norm=["x", "y", "y", "z", "w", "w"],
    )
    folds = run.component_folds(req, n_folds=3, seed=1)
    # a-b share family y, so a, b form one component; d-e share family w.
    assert folds[0] == folds[1] == folds[2]
    assert folds[4] == folds[5]
    assert folds.index.equals(req.index)
    assert run.component_folds(req, n_folds=3, seed=1).equals(folds)


def test_session_grouped_nested_cv(run, load_experiment):
    req = population()
    fits = []
    base = make(load_experiment)

    def factory(train, k):
        fits.append(set(train.index))
        return base(train, k)

    res = run.nested_cv(req, (1, 3), ctx(), factory, outer=3, inner=2, seed=5)
    outer = run.component_folds(req, n_folds=3, seed=5)
    for f in range(3):
        held = req[outer == f]
        fit_rows = req[outer != f]
        assert set(held["session_id"]).isdisjoint(fit_rows["session_id"])
        fam = run.family_key(req)
        assert set(fam[held.index].dropna()).isdisjoint(fam[fit_rows.index].dropna())
    # Every fit (inner and outer) uses rows outside the fold it is scored on,
    # and never a held-out outer row when choosing k for that outer fold.
    for rec in res["fits"]:
        assert set(rec["fit"]).isdisjoint(rec["scored"])
        if rec["level"] == "inner":
            assert set(rec["fit"]) | set(rec["scored"]) <= set(
                req.index[outer != rec["outer"]]
            )
    assert len(fits) == len(res["fits"])
    assert set(res["chosen_k"]) == {0, 1, 2}
    oof = res["oof"]
    assert set(oof) == {1, 3} and all(oof[k].index.equals(req.index) for k in oof)


def test_criterion_is_least_aggressive_not_highest_saving(run):
    assert run.least_aggressive({5: 0.30, 15: 0.10, 50: 0.10}) == 15
    assert run.least_aggressive({5: 0.0, 15: 0.0}) == 5
    assert run.CRITERION.startswith("least aggressive")


def results(run, load_experiment):
    req = population()
    router = make(load_experiment)(req, 3)
    after = router.apply(req, ctx())
    after["block_fees"], after["block_token_cost"] = 0.002, 0.004
    texts = run.lever_results_json(
        after,
        req,
        k=3,
        split="tune",
        with_reasoning=False,
        ctx=ctx(),
        premium_model="premium",
        cheap_model="cheap",
        cached_separately=frozenset(),
        rates={"cheap": {"input": 1.0, "cached": 0.5, "output": 2.0}},
        code_commit="abcdef1",
        python_version="3.13.5",
        created_at=CREATED,
        extra_assumptions=("synthetic run assumption",),
    )
    return {k: LeverResult.from_json(t) for k, t in texts.items()}, after


def test_one_result_per_baseline_with_units_never_mixed(run, load_experiment):
    res, after = results(run, load_experiment)
    assert set(res) == {
        "premium_gpt_5_5",
        "as_logged",
        "todays_models",
        "best_single_cheap",
    }
    assert {r.lever_id for r in res.values()} == {
        f"rb3.knn-router.k-3.tune.{b}" for b in res
    }
    assert {r.version for r in res.values()} == {"route.knn.k3"}
    for key, r in res.items():
        assert r.step == "routing" and r.evidence_class == "simulation"
        assert "cost simulation; quality not proven" in r.assumptions
        assert "synthetic run assumption" in r.assumptions
        assert {"all", "llm_only", "traffic_weighted", "routing"} <= set(r.slices)
        if key == "as_logged":  # recorded units, the target at implied rates
            assert set(r.saving) == {"fees", "token_cost", "total"}
            assert r.manifest.price_version == "full-eda-implied-unit-rates"
        else:
            assert "fees" not in r.baseline_cost and "fees" not in r.saving
            assert set(r.saving) == {"token_cost", "total"}
    moved = int((after["route_reason"] == "moved").sum())
    assert res["todays_models"].slices["routing"]["n_moved"] == Decimal(moved)


def test_interval_and_point_estimate_agree(run, load_experiment):
    res, _ = results(run, load_experiment)
    r = res["todays_models"]
    share = r.slices["all"]["saving_share"]
    assert r.ci_low <= float(share) <= r.ci_high


def test_results_are_content_free(run, load_experiment):
    res, _ = results(run, load_experiment)
    text = json.dumps([json.loads(r.to_json()) for r in res.values()])
    for raw in ("user-0", "bot-a", "bot-b", "s1", "q3"):
        assert f'"{raw}"' not in text and f":{raw}" not in text


def test_catalogue_fixture_is_synthetic():
    assert CATALOGUE["version"] == "cat-synthetic"
