"""Synthetic smoke run of R-B2's run helpers (exp-ctx-002/run.py). SYNTHETIC only."""

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest

D = Decimal
RUN = "context/exp-ctx-002-cross-turn-chunk-policy/run.py"


@pytest.fixture(scope="module")
def run(load_experiment):
    return load_experiment(RUN)


@pytest.fixture
def frames():
    req = pd.DataFrame(
        {
            "ai_message_id": ["m0", "m1", "m2"],
            "session_id": ["s1", "s1", "s1"],
            "user_id": ["user-01"] * 3,
            "bot_id": ["bot-01"] * 3,
            "turn": [0, 1, 2],
            "bot_provider_model": ["model-sep", "model-incl", "model-incl"],
            "a_bill_inputTokens": [5000.0, 5000.0, 5000.0],
            "a_bill_cachedInputTokens": [1000.0, 1000.0, float("nan")],
            "a_bill_totalCost": [0.03, 0.03, 0.03],
            "llm_request": [True, True, True],
            "block_fees": [0.002, 0.002, 0.002],
            "block_token_cost": [0.028, 0.028, 0.028],
        },
        index=[5, 6, 7],
    )
    chunks = pd.DataFrame(
        {
            "message_id": ["m0", "m1", "m1", "m2"],
            "chunk_id": ["chunk-a", "chunk-a", "chunk-b", "chunk-a"],
            "n_chars": [1000, 1000, 400, 1000],
            "h_exact": ["h-a", "h-a", "h-b", "h-a"],
        }
    )
    items = pd.DataFrame(
        {
            "message_id": ["m0", "m1", "m2", "m2"],
            "inputTokens": [5000, 5000, 4000, 1000],
            "costBreakdown.input_tokens": [0.005, 0.004, 0.004, float("nan")],
        }
    )
    return req, chunks, items


def test_build_chunks_keeps_request_order_and_scope(run, frames):
    req, chunks, _ = frames
    ch = run.build_chunks(req, chunks)
    assert ch["req"].tolist() == [5, 6, 6, 7]
    assert ch["turn"].tolist() == [0, 1, 1, 2]
    assert ch["content_hash"].tolist() == ["h-a", "h-a", "h-b", "h-a"]
    assert ch["scope"].nunique() == 1


def test_request_inputs_follow_convention_and_need_full_breakdown(run, frames):
    req, _, items = frames
    out = run.request_inputs(req, items, frozenset({"model-sep"}))
    assert out["input_tokens_ordinary"].tolist() == [5000.0, 4000.0, 5000.0]
    assert out.loc[5, "input_cost_ordinary"] == pytest.approx(0.005)
    assert out.loc[6, "input_cost_ordinary"] == pytest.approx(0.004)
    assert pd.isna(out.loc[7, "input_cost_ordinary"])  # a token item lacks it
    assert out.index.equals(req.index)


def test_evaluate_and_lever_result_smoke(run, frames):
    req, chunks, items = frames
    req = run.request_inputs(req, items, frozenset({"model-sep"}))
    ch = run.build_chunks(req, chunks)
    res = run.evaluate(req, ch, pointer_tokens=8, window=1, ledger=False, tpc=0.5)
    assert res["summary"]["reasons"]["dropped"] == 1  # m1's chunk-a
    assert res["summary"]["tokens"]["saved"] == 500 - 8
    assert res["summary"]["n_requests_changed"] == 1
    never = run.evaluate(req, ch, pointer_tokens=8, window=0, ledger=False, tpc=0.5)
    assert never["summary"]["tokens"]["saved"] == 0
    from metis_auto.analysis.lever_result import LeverResult

    texts = run.lever_results_json(
        res,
        req,
        repriced=None,
        ctx=_ctx(),
        code_commit="unknown",
        python_version="3.13.5",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    result = LeverResult.from_json(texts["as_logged"])
    assert result.lever_id == "rb2.cross-turn.k-1.ptr-8.pointer.as_logged"
    assert result.step == "context"
    assert result.evidence_class == "hypothetical reconstruction"
    assert result.saving["fees"] == 0
    assert any("tokens only" in a for a in result.assumptions)
    assert not any("interim" in a for a in result.assumptions)


# --- Repriced baselines: [SYNTHETIC] catalogue and prices, invented numbers ---

PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1_000_000,
    "prices": [
        {"price_ref": "p-small", "input": "1", "output": "2", "cached_input": "0.5"},
        {"price_ref": "p-premium", "input": "10", "output": "20", "cached_input": "5"},
    ],
}
CATALOGUE = {
    "models": [
        {"model_id": "model-sep", "price_ref": "p-small", "enabled": True},
        {"model_id": "model-incl", "price_ref": "p-small", "enabled": False},
        {"model_id": "syn-premium", "price_ref": "p-premium", "enabled": False},
    ]
}


def _ctx():
    from metis_auto.analysis.levers import ReplayContext

    return ReplayContext(
        period_bounds={}, price_table=PRICES, catalogue=CATALOGUE, seed=1, min_n=30
    )


def _tokens_frame():
    return pd.DataFrame(
        {
            "bot_provider_model": ["model-sep", "model-incl", "model-incl"],
            "a_bill_inputTokens": [30.0, 100.0, 2000.0],
            "a_bill_cachedInputTokens": [10.0, 80.0, 0.0],
            "a_bill_outputTokens": [5.0, 5.0, 5.0],
            "a_bill_totalCost": [0.03, 0.03, 0.03],
            "a_n_per_call_only_items": [1, 0, 0],
            "llm_request": [True, True, True],
            "ctx_tokens_saved": [50.0, 50.0, 1000.0],
        },
        index=[5, 6, 7],
    )


def test_rb2_after_frame_never_below_cached_tokens(run):
    before = _tokens_frame()
    after = run.after_tokens(before, frozenset({"model-sep"}))

    # model-sep reports cached tokens outside its input: floor 0.
    assert after.loc[5, "a_bill_inputTokens"] == 0
    # model-incl counts cached inside input: never below the 80 cached tokens.
    assert after.loc[6, "a_bill_inputTokens"] == 80
    assert after.loc[7, "a_bill_inputTokens"] == 1000
    assert after["a_bill_cachedInputTokens"].equals(before["a_bill_cachedInputTokens"])
    assert after.index.equals(before.index)


def test_rb2_repriced_saving_equals_baseline_difference(run):
    from metis_auto.analysis.baselines_full import baseline_costs

    before = _tokens_frame()
    separate = frozenset({"model-sep"})
    out = run.repriced_savings(
        before, _ctx(), premium_model="syn-premium", cached_separately=separate
    )

    after = run.after_tokens(before, separate)
    kw = {"premium_model": "syn-premium", "cached_separately": separate}
    b, a = baseline_costs(before, _ctx(), **kw), baseline_costs(after, _ctx(), **kw)
    assert set(out["saving"]) == {
        "premium_gpt_5_5",
        "todays_models",
        "best_single_cheap",
    }
    for key, saving in out["saving"].items():
        diff = b[key]["token_cost"] - a[key]["token_cost"]
        assert saving == {"token_cost": diff, "total": diff}
        assert "fees" not in saving
    assert out["before"] == b
    # Premium: the ordinary input that can go is 30 (model-sep, floor 0) + 20
    # (100 - 80 cached) + 1000 tokens, at 10 per 1M. Cached tokens are untouched.
    assert out["saving"]["premium_gpt_5_5"]["token_cost"] == D("0.010500000")


def test_rb2_after_frame_is_float_when_nothing_was_dropped(run):
    # The conservative scenario drops nothing; its saved column can be object.
    before = _tokens_frame()
    before["ctx_tokens_saved"] = pd.Series([0, 0, 0], index=before.index, dtype=object)
    after = run.after_tokens(before, frozenset({"model-sep"}))

    assert after["a_bill_inputTokens"].dtype == "float64"
    assert after["a_bill_inputTokens"].equals(before["a_bill_inputTokens"])
