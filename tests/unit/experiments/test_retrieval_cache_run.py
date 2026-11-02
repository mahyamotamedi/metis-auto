"""Synthetic smoke run of R-B1's run helpers (exp-cache-002/run.py).
SYNTHETIC fixtures only: labels such as ``user-01`` and made-up query text."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from metis_auto.analysis.cache_guard import CacheGuard

D = Decimal

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


def _guard_ctx(seed=3):
    guard = CacheGuard(
        approved=None, blocked=frozenset(), disabled_bots=frozenset(), key_version="r1"
    )
    return SimpleNamespace(guard=guard, seed=seed)


def _with_other_content(rag, message_id):
    """The same queries, but chunk content that differs from the earlier lookup."""
    out = rag.copy()
    other = json.dumps(
        [
            {
                "query": q,
                "relevantChunks": [{"id": "chunk-a", "content": "synthetic other"}],
            }
            for q in ("q one", "q two")
        ]
    )
    out.loc[out["message_id"] == message_id, "rag"] = other
    return out


def test_ttl_choice_uses_only_tune_split_rows(run, frames):
    req, rag, per_call = frames
    # m1's "q one" hit disagrees with the cached chunks; m2's agrees.
    rag = _with_other_content(rag, "m1")
    req = run.fee_blocks(req, per_call)
    lookups = run.build_lookups(req, rag, per_call)
    split = pd.Series(["tune", "excluded", "tune", "tune"], index=req.index)

    tune_only = run.choose_ttl(
        req, lookups, (7,), _guard_ctx(), 0.0, scored=split.eq("tune")
    )
    everyone = run.choose_ttl(
        req, lookups, (7,), _guard_ctx(), 0.0, scored=split.ne("unknown")
    )

    # Only the scored (tune split) hit counts: agreement 1, the rule passes.
    assert tune_only["by_ttl"]["7d"]["summary"]["agreement"]["n_hits"] == 1
    assert tune_only["chosen_ttl_days"] == 7
    # Scoring the excluded row too would have rejected the TTL (mean 0.5).
    assert everyone["by_ttl"]["7d"]["summary"]["agreement"]["n_hits"] == 2
    assert everyone["chosen_ttl_days"] is None


def test_cache_history_may_cross_the_period_boundary(run, frames):
    req, rag, per_call = frames
    req = run.fee_blocks(req, per_call)
    # m0 is a tune-period row outside the tune split (history only); m2 is a
    # later report-period row of a tune session, the only scored row.
    req["period"] = ["tune", "tune", "report", "report"]
    split = pd.Series(["excluded", "excluded", "tune", "excluded"], index=req.index)
    lookups = run.build_lookups(req, rag, per_call)

    res = run.evaluate(
        req, lookups, pd.Timedelta(days=7), _guard_ctx(), 0.0, scored=split.eq("tune")
    )

    # m2's "Q  one" is served from m0's entry, across the period boundary.
    assert res["summary"]["status"] == {"hit": 1}
    assert res["fees"]["fee_avoided"] == pytest.approx(0.002)
    assert res["rates"]["n_requests_all"] == 1
    assert res["after"].index.tolist() == [12]


def _baselines():
    """[SYNTHETIC] baseline_costs-shaped mapping: as-logged in recorded units
    (the known LLM rows of ``frames`` sum to 0.038), the rest repriced."""
    counts = {"n_requests": D(4), "n_known": D(3), "n_unknown": D(1)}
    repriced = {"token_cost": D("0.5"), "total": D("0.5")} | counts
    return {
        "premium_gpt_5_5": repriced,
        "as_logged": {"fees": D("0.008"), "token_cost": D("0.03"), "total": D("0.038")}
        | counts,
        "todays_models": repriced,
        "best_single_cheap": repriced,
    }


def _replay_ctx():
    from metis_auto.analysis.levers import ReplayContext

    return ReplayContext(
        period_bounds={
            "tune": (pd.Timestamp("2026-03-01"), pd.Timestamp("2026-07-31 23:59"))
        },
        price_table={"version": "prices-synthetic"},
        catalogue={},
        seed=3,
        min_n=30,
        guard=_guard_ctx().guard,
    )


def _results(run, frames):
    req, rag, per_call = frames
    req = run.fee_blocks(req, per_call)
    lookups = run.build_lookups(req, rag, per_call)
    ctx = _replay_ctx()
    res = run.evaluate(req, lookups, pd.Timedelta(days=7), ctx, 0.0)
    return run.lever_results_json(
        res,
        req,
        baselines=_baselines(),
        split_counts={"tune": 4, "excluded_period:tune": 0},
        ttl=pd.Timedelta(days=7),
        ctx=ctx,
        code_commit="unknown",
        python_version="3.13.5",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
        extra_assumptions=("synthetic smoke run",),
    )


def test_lever_result_json_validates(run, frames):
    from metis_auto.analysis.lever_result import LeverResult

    texts = _results(run, frames)
    assert set(texts) == {
        "premium_gpt_5_5",
        "as_logged",
        "todays_models",
        "best_single_cheap",
    }
    result = LeverResult.from_json(texts["as_logged"])
    assert result.lever_id == "rb1.retrieval-cache.ttl-7d.user.tune.as_logged"
    assert result.saving["token_cost"] == 0
    assert result.saving["fees"] > 0
    assert result.baseline_cost["fees"] + result.baseline_cost["token_cost"] == D(
        "0.038"
    )
    assert result.evidence_class == "simulation"
    assert result.slices["split"]["tune"] == 4
    assert any("measured potential" in a for a in result.assumptions)
    assert not any("interim" in a for a in result.assumptions)


def test_rb1_saving_not_computed_against_repriced_baselines(run, frames):
    from metis_auto.analysis.compare import compare
    from metis_auto.analysis.lever_result import LeverResult

    texts = _results(run, frames)
    for key in ("premium_gpt_5_5", "todays_models", "best_single_cheap"):
        result = LeverResult.from_json(texts[key])
        # Not computed in price-file units: no key at all, never a zero.
        assert result.saving == {}
        assert "fees" not in result.baseline_cost
        assert result.baseline_cost["total"] == D("0.5")
        assert set(result.baseline_cost) == {"token_cost", "total"}
        assert result.ci_low is None and result.ci_high is None
        assert any("not computed" in a for a in result.assumptions)
        row = compare([result], baseline=key, max_tenant_share=D("0.35")).iloc[0]
        assert row["saving"] is None
        assert row["status"] == "insufficient evidence"
