"""Synthetic smoke run of R-B2's run helpers (exp-ctx-002/run.py). SYNTHETIC only."""

from datetime import UTC, datetime

import pandas as pd
import pytest

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
    pytest.importorskip("metis_auto.analysis.lever_result")
    from metis_auto.analysis.lever_result import LeverResult

    text = run.lever_result_json(
        res,
        req,
        seed=1,
        code_commit="unknown",
        python_version="3.13.5",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    result = LeverResult.from_json(text)
    assert result.step == "context"
    assert result.evidence_class == "hypothetical reconstruction"
    assert result.saving["fees"] == 0
    assert any("tokens only" in a for a in result.assumptions)
