"""R-B3 kNN router (nearest-profile policy), exp-route-011/version.py. SYNTHETIC only.

Traces: plan R-B3 ("Routing without quality labels"), FR-ROUTE-03, FR-ROUTE-05,
Review Focus 2 and 3, ADR-0036.
"""

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.baselines_full import baseline_costs
from metis_auto.analysis.levers import ReplayContext

VERSION = "routing/exp-route-011-knn-router/version.py"
ELIG = "routing/exp-route-011-knn-router/eligibility_interim.py"

# Synthetic price file: "cheap" < "mid" < "dear"; "sep" reports cached tokens
# outside its input count; "tiered" has a long-context tier.
CATALOGUE = {
    "version": "cat-synthetic",
    "models": [
        {"model_id": m, "price_ref": f"p-{m}", "enabled": e}
        for m, e in (
            ("cheap", True),
            ("mid", True),
            ("dear", True),
            ("sep", True),
            ("tiered", False),
            ("premium", False),
        )
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


def ctx(min_n=None):
    bounds = {"tune": (pd.Timestamp("2026-03-01"), pd.Timestamp("2026-07-31"))}
    return ReplayContext(
        period_bounds=bounds,
        price_table=PRICES,
        catalogue=CATALOGUE,
        seed=7,
        min_n=min_n,
    )


def frame(n, **cols):
    """``n`` synthetic LLM rows; every keyword overrides a column."""
    base = {
        "session_id": [f"s{i}" for i in range(n)],
        "bot_id": ["bot-01"] * n,
        "user_id": ["user-01"] * n,
        "u_h_norm": [f"q{i}" for i in range(n)],
        "u_lang": ["fa"] * n,
        "n_prior_msgs": [0] * n,
        "prior_chars": [0] * n,
        "a_rag_n_chunks": [0] * n,
        "a_rag_chunk_chars": [np.nan] * n,
        "u_att_n": [0.0] * n,
        "u_n_chars": [100.0] * n,
        "bot_n_functions": [0] * n,
        "bot_provider_model": ["dear"] * n,
        "a_bill_inputTokens": [1000.0] * n,
        "a_bill_cachedInputTokens": [0.0] * n,
        "a_bill_outputTokens": [100.0] * n,
        "a_billing_state": ["items"] * n,
        "a_bill_totalCost": [0.01] * n,
        "a_n_per_call_only_items": [0.0] * n,
        "llm_request": [True] * n,
    }
    base.update(cols)
    return pd.DataFrame(base)


def allow_all(row, catalogue, prices, rules):
    return tuple(rules["candidates"])


@pytest.fixture(scope="module")
def v(load_experiment):
    return load_experiment(VERSION)


def router(v, train, k=3, eligible=allow_all, candidates=("cheap", "mid"), **kw):
    return v.KnnRouter(
        k=k,
        train=train,
        candidates=candidates,
        eligible_models=eligible,
        rules={"candidates": list(candidates)},
        **kw,
    )


# --- plan test names ---


def test_labels_only_from_declared_source(v):
    train = frame(6)
    r = router(v, train)
    assert r.label_source is None
    for source in ("golden-v2", "logged_model", "cheapest_model"):
        with pytest.raises(ValueError, match="blocked"):
            router(v, train, label_source=source)
    # A label-like column in the frame is never read: same decisions.
    query = frame(2, session_id=["x1", "x2"], u_h_norm=["y1", "y2"])
    plain = r.apply(query, ctx())
    labelled = r.apply(query.assign(quality_label=[0, 1]), ctx())
    assert plain["routed_model"].tolist() == labelled["routed_model"].tolist()


def test_quality_not_proven_in_assumptions_without_labels(v):
    assert "cost simulation; quality not proven" in v.ASSUMPTIONS


def test_small_n_insufficient_or_wide_interval(v):
    train = frame(6, bot_provider_model=["cheap"] * 6)
    query = frame(2, session_id=["x1", "x2"], u_h_norm=["y1", "y2"])
    # The query's bot has 6 fitting rows; min_n 10 makes it insufficient.
    out = router(v, train).apply(query, ctx(min_n=10))
    assert out["route_reason"].tolist() == ["insufficient_bot"] * 2
    assert out["routed_model"].tolist() == ["dear", "dear"]
    out = router(v, train).apply(query, ctx(min_n=5))
    assert out["route_reason"].tolist() == ["moved"] * 2


# --- fitting, neighbours, decisions ---


def test_scaling_is_fitted_on_training_rows_only(v):
    train = frame(4, u_n_chars=[10.0, 20.0, 30.0, 40.0])
    r = router(v, train)
    huge = frame(4, u_n_chars=[1e6] * 4, session_id=list("abcd"))
    expected = np.log1p(np.array([10.0, 20.0, 30.0, 40.0]))
    col = v.NUMERIC.index("u_n_chars")
    assert r.scaler.center[col] == pytest.approx(expected.mean())
    assert r.scaler.scale[col] == pytest.approx(expected.std())
    r.apply(huge, ctx())  # applying never refits
    assert r.scaler.center[col] == pytest.approx(expected.mean())


def test_missing_numbers_take_the_training_median(v):
    train = frame(3, u_n_chars=[10.0, 20.0, 1000.0])
    r = router(v, train)
    raw = v.profile_matrix(frame(1, u_n_chars=[np.nan]))
    filled = r.scaler.fill(raw)
    col = v.NUMERIC.index("u_n_chars")
    assert filled[0, col] == pytest.approx(np.log1p(20.0))
    # No RAG chunks: chunk characters are 0, not missing.
    raw = v.profile_matrix(frame(1, a_rag_n_chunks=[0], a_rag_chunk_chars=[np.nan]))
    assert raw[0, v.NUMERIC.index("a_rag_chunk_chars")] == 0.0


def test_no_self_neighbour_same_session_or_family_excluded(v):
    # Training rows 0-1 share the query's session, 2 its family, 3-5 are free.
    train = frame(
        6,
        session_id=["q-s", "q-s", "o1", "o2", "o3", "o4"],
        u_h_norm=["f0", "f1", "q-f", "f3", "f4", "f5"],
        bot_provider_model=["cheap", "cheap", "cheap", "mid", "mid", "mid"],
    )
    query = frame(1, session_id=["q-s"], u_h_norm=["q-f"])
    out = router(v, train, k=3).apply(query, ctx())
    assert out.loc[0, "routed_model"] == "mid"  # cheap only via excluded rows
    assert out.loc[0, "route_reason"] == "moved"


def test_family_is_bot_and_question(v):
    train = frame(
        3,
        session_id=["o1", "o2", "o3"],
        u_h_norm=["q-f"] * 3,
        bot_id=["bot-02", "bot-02", "bot-02"],
        bot_provider_model=["cheap"] * 3,
    )
    query = frame(1, session_id=["x"], u_h_norm=["q-f"])  # bot-01: another family
    out = router(v, train, k=3).apply(query, ctx())
    assert out.loc[0, "routed_model"] == "cheap"


def test_neighbours_may_come_from_other_bots(v):
    assert v.CROSS_BOT is True
    train = frame(4, bot_id=["bot-09"] * 4, bot_provider_model=["cheap"] * 4)
    query = frame(1, session_id=["x"], u_h_norm=["y"])
    assert router(v, train).apply(query, ctx()).loc[0, "routed_model"] == "cheap"


def test_ties_are_broken_by_training_order(v):
    train_x = np.zeros((5, 2))
    query_x = np.zeros((1, 2))
    groups = (np.array([1, 2, 3, 4, 5]), np.array([-1] * 5))
    qgroups = (np.array([0]), np.array([-1]))
    idx = v.nearest(train_x, query_x, k=3, train_groups=groups, query_groups=qgroups)
    assert idx.tolist() == [[0, 1, 2]]
    shuffled = v.nearest(
        train_x[::-1], query_x, k=3, train_groups=groups, query_groups=qgroups
    )
    assert shuffled.tolist() == [[0, 1, 2]]


def test_nearest_pads_when_too_few_neighbours(v):
    train_x = np.array([[0.0], [1.0]])
    groups = (np.array([1, 0]), np.array([-1, -1]))
    idx = v.nearest(
        train_x,
        np.array([[0.0]]),
        k=2,
        train_groups=groups,
        query_groups=(np.array([0]), np.array([-1])),
    )
    assert idx.tolist() == [[0, -1]]  # training row 1 is the query's own session


def test_cold_start_keeps_the_incumbent(v):
    train = frame(2, bot_provider_model=["cheap"] * 2)
    query = frame(1, session_id=["x"], u_h_norm=["y"])
    out = router(v, train, k=3).apply(query, ctx())
    assert out.loc[0, "route_reason"] == "too_few_neighbours"
    assert out.loc[0, "routed_model"] == "dear"
    new_bot = frame(1, session_id=["x"], u_h_norm=["y"], bot_id=["bot-new"])
    out = router(v, frame(6, bot_provider_model=["cheap"] * 6)).apply(
        new_bot, ctx(min_n=2)
    )
    assert out.loc[0, "route_reason"] == "insufficient_bot"


def test_never_routes_upward(v):
    train = frame(6, bot_provider_model=["dear"] * 3 + ["mid"] * 3)
    query = frame(2, session_id=["x", "y"], u_h_norm=["a", "b"])
    query["bot_provider_model"] = ["cheap", "mid"]
    out = router(v, train, k=6, candidates=("mid", "dear")).apply(query, ctx())
    assert out["routed_model"].tolist() == ["cheap", "mid"]
    assert out["route_reason"].tolist() == ["no_cheaper_candidate"] * 2
    assert (out["route_cost_routed"] <= out["route_cost_incumbent"]).all()


def test_only_candidates_are_chosen(v):
    train = frame(3, bot_provider_model=["sep"] * 3)  # "sep" is not a candidate
    query = frame(1, session_id=["x"], u_h_norm=["y"])
    out = router(v, train).apply(query, ctx())
    assert out.loc[0, "route_reason"] == "no_eligible_candidate"


def test_hard_constraints_come_from_the_injected_eligible_models(v):
    seen = []

    def only_mid(row, catalogue, prices, rules):
        seen.append((row["input_tokens"], catalogue["version"], prices["version"]))
        return ("mid",)

    train = frame(6, bot_provider_model=["cheap"] * 3 + ["mid"] * 3)
    query = frame(1, session_id=["x"], u_h_norm=["y"])
    out = router(v, train, k=6, eligible=only_mid).apply(query, ctx())
    assert out.loc[0, "routed_model"] == "mid"
    assert seen == [(1000.0, "cat-synthetic", "prices-synthetic")]


def test_incumbent_without_a_price_is_kept(v):
    train = frame(3, bot_provider_model=["cheap"] * 3)
    query = frame(1, session_id=["x"], u_h_norm=["y"], bot_provider_model=["unlisted"])
    out = router(v, train).apply(query, ctx())
    assert out.loc[0, "route_reason"] == "incumbent_unpriced"
    assert out.loc[0, "routed_model"] == "unlisted"
    assert pd.isna(out.loc[0, "route_cost_incumbent"])


def test_unknown_tokens_are_kept_and_unknown(v):
    train = frame(3, bot_provider_model=["cheap"] * 3)
    query = frame(1, session_id=["x"], u_h_norm=["y"], a_bill_inputTokens=[np.nan])
    out = router(v, train).apply(query, ctx())
    assert out.loc[0, "route_reason"] == "unknown_tokens"
    assert pd.isna(out.loc[0, "route_cost_routed"])


def test_fee_and_recorded_blocks_unchanged(v):
    train = frame(3, bot_provider_model=["cheap"] * 3)
    query = frame(2, session_id=["x", "y"], u_h_norm=["a", "b"])
    query["block_fees"] = [0.002, 0.004]
    query["block_token_cost"] = [0.01, 0.02]
    out = router(v, train).apply(query, ctx())
    assert out["route_reason"].tolist() == ["moved", "moved"]
    for col in ("block_fees", "block_token_cost", "a_bill_totalCost"):
        assert out[col].tolist() == query[col].tolist()
    assert out.index.equals(query.index)


def test_support_is_the_share_of_neighbours_on_the_routed_model(v):
    train = frame(4, bot_provider_model=["cheap", "dear", "dear", "dear"])
    query = frame(1, session_id=["x"], u_h_norm=["y"])
    out = router(v, train, k=4).apply(query, ctx())
    assert out.loc[0, "routed_model"] == "cheap"
    assert out.loc[0, "route_support"] == pytest.approx(0.25)


def test_candidate_costs_match_baselines_full(v):
    req = frame(
        4,
        bot_provider_model=["sep", "dear", "tiered", "tiered"],
        a_bill_inputTokens=[500.0, 1000.0, 900.0, 2000.0],
        a_bill_cachedInputTokens=[800.0, 200.0, 0.0, 0.0],
        a_bill_outputTokens=[10.0, 20.0, 30.0, 40.0],
    )
    sep = frozenset({"sep"})
    costs = v.candidate_costs(req, ["sep", "dear", "tiered"], ctx(), sep)
    incumbent = [costs.loc[i, m] for i, m in enumerate(req["bot_provider_model"])]
    ref = baseline_costs(req, ctx(), premium_model="premium", cached_separately=sep)
    total = Decimal(f"{sum(incumbent):.9f}")
    assert total == ref["todays_models"]["token_cost"]
    # "sep" adds cached tokens back: (500 + 800 - 800) x 3 + 800 x 0.1 + 10 x 6.
    assert costs.loc[0, "sep"] == pytest.approx((500 * 3 + 800 * 0.1 + 60) / 1e6)
    # The tier follows the effective input.
    assert costs.loc[2, "tiered"] == pytest.approx((900 + 30) / 1e6)
    assert costs.loc[3, "tiered"] == pytest.approx((2000 + 40) * 10 / 1e6)


def test_unpriced_model_costs_are_unknown(v):
    costs = v.candidate_costs(frame(1), ["unlisted"], ctx(), frozenset())
    assert pd.isna(costs.loc[0, "unlisted"])


def test_interim_eligibility(load_experiment):
    e = load_experiment(ELIG)
    cat = {
        "models": [
            {
                "model_id": "a",
                "price_ref": "p-cheap",
                "enabled": True,
                "context_window": {"value": 1000},
                "max_output_tokens": {"value": 100},
            },
            {"model_id": "b", "price_ref": "p-mid", "enabled": True},  # no limits
            {
                "model_id": "c",
                "price_ref": "p-none",
                "enabled": True,
                "context_window": {"value": 10**6},
                "max_output_tokens": {"value": 10**5},
            },
            {
                "model_id": "r",
                "price_ref": "p-dear",
                "enabled": True,
                "context_window": {"value": 10**6},
                "max_output_tokens": {"value": 10**5},
            },
        ]
    }
    rules = {"candidates": ["a", "b", "c", "r", "z"], "retiring": ["r"]}
    row = {
        "input_tokens": 800.0,
        "output_tokens": 50.0,
        "u_att_n": 0,
        "bot_n_functions": 0,
    }
    assert e.interim_eligible_models(row, cat, PRICES, rules) == ("a",)
    assert (
        e.interim_eligible_models({**row, "input_tokens": 990.0}, cat, PRICES, rules)
        == ()
    )
    assert e.interim_eligible_models({**row, "u_att_n": 1}, cat, PRICES, rules) == ()
    assert (
        e.interim_eligible_models({**row, "bot_n_functions": 2}, cat, PRICES, rules)
        == ()
    )
    assert (
        e.interim_eligible_models({**row, "input_tokens": np.nan}, cat, PRICES, rules)
        == ()
    )
    assert "interim eligibility" in e.LABEL
