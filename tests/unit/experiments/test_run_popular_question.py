"""Offline logic of ``scripts/run_popular_question.py`` (R-A1 phase 2).

Every frame and file here is [SYNTHETIC]: labels such as ``q-1`` stand in for
grouping hashes and ``text-...`` strings for message text. The script is loaded
with ``importlib`` (scripts are not a package), as in
``tests/architecture/test_docs_conventions.py``.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.lever_result import LeverResult, build_manifest
from metis_auto.analysis.levers import ReplayContext, combine, with_blocks

ROOT = Path(__file__).resolve().parents[3]
BASE = pd.Timestamp("2026-08-01")


@pytest.fixture(scope="module")
def rp():
    name = "run_popular_question_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "run_popular_question.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cache(rp):
    return rp.load_cache_class()(90, 3, 2, "first_turn", rp.KEY_VERSION)


def ctx(rp=None, guard=None) -> ReplayContext:
    return ReplayContext(
        period_bounds={
            "tune": (pd.Timestamp("2026-03-01"), pd.Timestamp("2026-07-31 23:59")),
            "report": (pd.Timestamp("2026-08-01"), pd.Timestamp("2026-10-31 23:59")),
        },
        price_table={"version": "prices-synthetic", "per_tokens": 1_000_000},
        catalogue={},
        seed=7,
        guard=guard,
    )


def row(day, session, q="q-1", a="ans-1", n=0, **over) -> dict:
    """[SYNTHETIC] one eligible first-turn LLM request, report period by default."""
    t = BASE + pd.Timedelta(days=day, hours=10, minutes=n)
    r = {
        "llm_request": True,
        "period": "report" if day >= 0 else "tune",
        "bot_id": "bot-a",
        "bot_provider_model": "syn-model",
        "session_id": session,
        "user_id": "owner-a",
        "u_lang": "fa",
        "u_timestamp": t,
        "a_timestamp": t + pd.Timedelta(seconds=30),
        "u_content_state": "text",
        "a_content_state": "text",
        "a_finish_reason": "STOP",
        "u_att_n": 0,
        "a_tool_n_calls": 0,
        "a_action_types": "",
        "bot_memory_enabled": False,
        "a_rag_state": "null",
        "a_rag_n_queries": 0,
        "n_prior_msgs": 1,
        "u_h_norm": q,
        "a_h_norm": a,
        "bot_ins_h_exact": "ins-a",
        "a_bill_totalCost": 0.012,
        "a_n_per_call_only_items": 1,
        "a_bill_inputTokens": 100,
        "a_bill_cachedInputTokens": 0,
        "a_bill_outputTokens": 10,
        "user_message_id": f"um-{session}-{day}-{n}",
        "ai_message_id": f"am-{session}-{day}-{n}",
    }
    r.update(over)
    return r


def frame(*rows: dict) -> pd.DataFrame:
    return with_blocks(pd.DataFrame(list(rows), index=range(100, 100 + len(rows))))


def popular_frame() -> pd.DataFrame:
    """[SYNTHETIC] q-1 popular in the tune period, then asked in the report period."""
    return frame(
        *(row(-10, f"t{i}") for i in range(3)),
        row(1, "r1"),
        row(2, "r2", u_lang="en", user_id="owner-b"),
        row(3, "r3", q="q-2", a_bill_inputTokens=9000),
        row(3, "wf", llm_request=False, a_bill_totalCost=np.nan),
    )


def report_pair(rp, cache):
    req = popular_frame()
    out = combine(req, cache, None, None, ctx())
    rep = req["period"].eq("report")
    return req[rep], out[rep]


def test_ranks_are_opaque_and_ordered_by_volume(rp):
    s = pd.Series(["x", "y", "y", "z", "y", "x", None])
    ranks = rp.rank_labels(s, "bot-")
    assert ranks.iloc[1] == ranks.iloc[2] == "bot-01"  # y: 3 requests
    assert ranks.iloc[0] == ranks.iloc[5] == "bot-02"  # x: 2
    assert ranks.iloc[3] == "bot-03"
    assert pd.isna(ranks.iloc[6])
    assert not set(ranks.dropna()) & {"x", "y", "z"}


def test_effective_input_adds_cached_tokens_for_separate_models(rp):
    req = pd.DataFrame(
        {
            "bot_provider_model": ["m-sep", "m-in"],
            "a_bill_inputTokens": [100, 100],
            "a_bill_cachedInputTokens": [50, 50],
        }
    )
    assert rp.effective_input(req, frozenset({"m-sep"})).tolist() == [150, 100]


def test_report_slices_have_lang_tenant_and_over_8k(rp, cache):
    before, after = report_pair(rp, cache)
    slices = rp.report_slices(before, after, cached_separately=frozenset())
    assert {"all", "llm_only", "lang:fa", "lang:en", "over_8k"} <= set(slices)
    assert slices["tenant_rank:1"]["share"] == Decimal("0.666666667")
    assert slices["over_8k"]["n_requests"] == 1
    assert slices["llm_only"]["n_cache_hits"] == 2
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9_.:\-]*", k) for k in slices)


def test_saving_ci_is_session_clustered_and_brackets_the_estimate(rp, cache):
    before, after = report_pair(rp, cache)
    est, lo, hi = rp.saving_ci(before, after, seed=7)
    assert lo <= est <= hi
    assert est == pytest.approx(2 / 3)


def test_as_logged_result_is_a_valid_candidate_simulation(rp, cache):
    before, after = report_pair(rp, cache)
    c = ctx()
    manifest = build_manifest(
        {"variant": "first_turn"},
        c,
        code_commit="unknown",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    result = rp.as_logged_result(cache, before, after, manifest, ("extra.",))
    assert isinstance(result, LeverResult)
    assert result.baseline == "as_logged"
    assert result.lever_id == "cache.popular_question.first_turn"
    assert (result.evidence_class, result.correctness_state) == (
        "simulation",
        "unmeasured",
    )
    assert result.n_requests == 4 and result.n_eligible == 3
    assert result.saving["total"] == result.slices["llm_only"]["saving:total"]
    assert any("proxy" in a for a in result.assumptions)
    assert "extra." in result.assumptions
    assert result.ci_low is not None and result.ci_high is not None
    text = result.to_json()
    for leak in ("q-1", "ans-1", "bot-a", "owner-a", "am-", "um-"):
        assert leak not in text


def test_diagnostics_are_aggregates_only(rp, cache):
    before, after = report_pair(rp, cache)
    keys = cache.keys(before)
    d = rp.diagnostics(cache, before, after, keys, shadow_rate=1.0, seed=7)
    assert d["hits"] == 2 and d["eligible"] == 3
    assert d["hit_rate_all"] == pytest.approx(2 / 4)
    assert d["hit_rate_eligible"] == pytest.approx(2 / 3)
    assert d["distinct_served_keys"] == 1
    assert d["shadow_rows"] == 2 and d["agreement"] == pytest.approx(1.0)
    assert all(isinstance(v, int | float) for v in d.values())


def test_review_items_take_top_keys_once_then_seeded_random_hits(rp):
    hits = pd.Series([True] * 6 + [False], index=range(10, 17))
    keys = pd.Series(["k1", "k1", "k1", "k2", "k2", "k3", "k1"], index=hits.index)
    sources = pd.Series([1, 1, 1, 2, 2, 3], index=range(10, 16))
    a = rp.review_items(hits, keys, sources, n_top=2, n_random=2, seed=3)
    b = rp.review_items(hits, keys, sources, n_top=2, n_random=2, seed=3)
    pd.testing.assert_frame_equal(a, b)  # seeded
    assert a["item"].tolist() == [1, 2, 3, 4]
    assert a["sample"].tolist() == ["top_key", "top_key", "random", "random"]
    top = a[a["sample"] == "top_key"]
    assert set(keys[top["row"]]) == {"k1", "k2"}  # the two keys with most hits
    assert a["row"].is_unique and set(a["row"]) <= set(hits.index[hits])
    assert (a["source_row"] == sources[a["row"]].to_numpy()).all()


def test_attach_text_joins_by_message_id(rp, tmp_path):
    pd.DataFrame(
        {
            "message_id": ["um-1", "am-src", "am-hit", "am-other"],
            "content": ["text-question", "text-stored", "text-hit", "text-x"],
        }
    ).to_parquet(tmp_path / "chat_message-00000-of-00001.parquet")
    items = pd.DataFrame(
        {
            "item": [1],
            "sample": ["top_key"],
            "bot_rank": ["bot-01"],
            "question_id": ["um-1"],
            "stored_answer_id": ["am-src"],
            "hit_answer_id": ["am-hit"],
        }
    )
    sheet = rp.attach_text(items, tmp_path)
    assert list(sheet.columns) == [
        "item",
        "sample",
        "bot_rank",
        "question_text",
        "stored_answer_text",
        "hit_answer_text",
        "verdict",
        "note",
    ]
    assert sheet.iloc[0][
        ["question_text", "stored_answer_text", "hit_answer_text"]
    ].tolist() == [
        "text-question",
        "text-stored",
        "text-hit",
    ]
    assert sheet.iloc[0]["verdict"] == "" and sheet.iloc[0]["note"] == ""


def test_sheet_is_refused_outside_git_ignored_paths(rp, tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "is_git_ignored", lambda path: False)
    with pytest.raises(SystemExit, match="git-ignored"):
        rp.write_sheet(pd.DataFrame({"item": [1]}), tmp_path / "sheet.csv")
    assert not (tmp_path / "sheet.csv").exists()


def test_sensitivity_reads_the_tune_period_only(rp):
    req = popular_frame()
    grid = rp.sensitivity(
        rp.load_cache_class(), req, ctx(), windows=(30, 90), min_counts=(2, 3)
    )
    assert list(grid.columns) == [
        "window_days",
        "min_count",
        "eligible",
        "hits",
        "hit_rate_eligible",
        "saving_share",
    ]
    assert len(grid) == 4
    assert (grid["eligible"] == 3).all()  # the three tune rows only
    assert (grid["hits"] == 0).all()  # nothing in the tune period repeats in time


def test_repriced_results_use_price_units_and_token_cost_only(rp, cache):
    before, after = report_pair(rp, cache)
    c = ReplayContext(
        period_bounds=ctx().period_bounds,
        price_table={
            "version": "prices-synthetic",
            "per_tokens": 1_000_000,
            "prices": [
                {
                    "price_ref": "p-syn",
                    "input": "1",
                    "output": "2",
                    "cached_input": "0.5",
                }
            ],
        },
        catalogue={
            "models": [{"model_id": "syn-model", "price_ref": "p-syn", "enabled": True}]
        },
        seed=7,
    )
    manifest = build_manifest(
        {"variant": "first_turn"},
        c,
        code_commit="unknown",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    results, missing = rp.repriced_results(
        cache,
        before,
        after,
        c,
        dict.fromkeys(rp.BASELINE_KEYS, manifest),
        (),
        premium_model="syn-model",
        cached_separately=frozenset(),
    )
    assert set(results) == {"premium_gpt_5_5", "todays_models", "best_single_cheap"}
    assert missing == {}
    r = results["todays_models"]
    assert r.baseline == "todays_models"
    assert set(r.saving) == {"token_cost", "total"}  # no fee block in price units
    # r1, r2 hit (120 tokens-cost units each); r3 has 9,000 input tokens.
    assert r.slices["llm_only"]["saving_share"] == Decimal(
        "0.025917927"
    )  # 240 / (240 + 9,020)
    assert "baseline:fees" not in r.slices["all"]  # no recorded amounts mixed in
    assert any("price-file units" in a for a in r.assumptions)
