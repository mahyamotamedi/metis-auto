"""Synthetic smoke run of R-B1's run helpers (exp-cache-002/run.py).
SYNTHETIC fixtures only: labels such as ``user-01`` and made-up query text."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from metis_auto.analysis.cache_guard import CacheGuard

RUN = "caching/exp-cache-002-retrieval-result-cache/run.py"


@pytest.fixture(scope="module")
def run(load_experiment):
    return load_experiment(RUN)


def _rag(*queries):
    return json.dumps(
        [
            {
                "query": q,
                "relevantChunks": [{"id": "chunk-a", "content": "synthetic a"}],
            }
            for q in queries
        ]
    )


@pytest.fixture
def frames():
    t = pd.Timestamp("2026-04-01 09:00")
    req = pd.DataFrame(
        {
            "ai_message_id": ["m0", "m1", "m2", "m3"],
            "session_id": ["s1", "s1", "s2", "s3"],
            "user_id": ["user-01", "user-01", "user-01", "user-02"],
            "bot_id": ["bot-01"] * 4,
            "bot_user_id": ["owner-01"] * 4,
            "u_timestamp": [t + pd.Timedelta(minutes=m) for m in (0, 10, 20, 30)],
            "a_timestamp": [
                t + pd.Timedelta(minutes=m, seconds=5) for m in (0, 10, 20, 30)
            ],
            "bot_rag_top_k": [5.0] * 4,
            "bot_rag_reranking": ["off"] * 4,
            "bot_n_corpora": [1] * 4,
            "a_bill_totalCost": [0.012, 0.014, 0.012, float("nan")],
            "llm_request": [True, True, True, True],
        },
        index=[10, 11, 12, 13],
    )
    rag = pd.DataFrame(
        {
            "message_id": ["m0", "m1", "m2", "m3"],
            "rag": [
                _rag("q one"),
                _rag("q one", "q two"),
                _rag("Q  one"),
                _rag("q one"),
            ],
        }
    )
    per_call = pd.DataFrame(
        {
            "message_id": ["m0", "m1", "m1", "m2"],
            "amount": [0.002, 0.002, 0.002, 0.002],
        }
    )
    return req, rag, per_call


def test_build_lookups_preserves_requests_and_attributes_fees(run, frames):
    req, rag, per_call = frames
    lk = run.build_lookups(req, rag, per_call)
    assert lk["req"].tolist() == [10, 11, 11, 12, 13]
    assert lk["pos"].tolist() == [0, 0, 1, 0, 0]
    assert lk["fee"].iloc[:4].tolist() == [0.002] * 4
    assert pd.isna(lk["fee"].iloc[4])  # no per-call item for m3
    assert lk["corpus_version"].isna().all()  # no version evidence: never invented
    assert set(lk["tenant"]) == {"user-01", "user-02"}
    bot_scope = run.build_lookups(req, rag, per_call, scope="bot")
    assert set(bot_scope["tenant"]) == {"owner-01"}


def test_fee_blocks_use_recorded_per_call_amounts(run, frames):
    req, _, per_call = frames
    out = run.fee_blocks(req, per_call)
    assert out["block_fees"].tolist()[:3] == pytest.approx([0.002, 0.004, 0.002])
    assert out["block_token_cost"].tolist()[:3] == pytest.approx([0.01, 0.01, 0.01])
    assert out[["block_fees", "block_token_cost"]].iloc[3].isna().all()
    assert out.index.equals(req.index)


def test_evaluate_smoke(run, frames):
    req, rag, per_call = frames
    req = run.fee_blocks(req, per_call)
    lookups = run.build_lookups(req, rag, per_call)
    guard = CacheGuard(
        approved=None, blocked=frozenset(), disabled_bots=frozenset(), key_version="r1"
    )
    ctx = SimpleNamespace(guard=guard, seed=3)
    res = run.evaluate(req, lookups, pd.Timedelta(days=7), ctx, shadow_rate=1.0)
    s = res["summary"]
    assert s["status"]["hit"] == 2  # m1 "q one" and m2 "Q  one"
    assert res["rates"]["requests_reused_all"] == pytest.approx(2 / 4)
    assert res["rates"]["requests_reused_llm"] == pytest.approx(2 / 4)
    assert res["fees"]["fee_avoided"] == pytest.approx(0.004)
    assert res["fees"]["share_of_fee_block"] == pytest.approx(0.004 / 0.008)
    assert res["fees"]["share_of_total_cost"] == pytest.approx(0.004 / 0.038)
    assert res["after"]["block_token_cost"].equals(req["block_token_cost"])
    assert "tenant_rank:1" in res["tenants"]
    assert json.dumps(res["summary"])  # content-free and serialisable


def test_lever_result_json_validates(run, frames):
    pytest.importorskip("metis_auto.analysis.lever_result")
    from metis_auto.analysis.lever_result import LeverResult

    req, rag, per_call = frames
    req = run.fee_blocks(req, per_call)
    lookups = run.build_lookups(req, rag, per_call)
    guard = CacheGuard(
        approved=None, blocked=frozenset(), disabled_bots=frozenset(), key_version="r1"
    )
    res = run.evaluate(
        req, lookups, pd.Timedelta(days=7), SimpleNamespace(guard=guard, seed=3), 0.0
    )
    text = run.lever_result_json(
        res,
        req,
        ttl=pd.Timedelta(days=7),
        seed=3,
        code_commit="unknown",
        python_version="3.13.5",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
        extra_assumptions=("synthetic smoke run",),
    )
    result = LeverResult.from_json(text)
    assert result.saving["token_cost"] == 0
    assert result.saving["fees"] > 0
    assert result.evidence_class == "simulation"
    assert any("measured potential" in a for a in result.assumptions)
    assert any("interim" in a for a in result.assumptions)
