"""Offline logic of ``scripts/run_reranker_cut.py`` (R-A2).

Every frame here is [SYNTHETIC]: ``m-1``-style labels stand in for message IDs,
``h-1`` for fingerprints and ``text ...`` for text. The script is loaded with
``importlib`` (scripts are not a package), as in ``test_run_popular_question.py``.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.lever_result import build_manifest
from metis_auto.analysis.levers import ReplayContext

ROOT = Path(__file__).resolve().parents[3]
SLOPE = 0.5


@pytest.fixture(scope="module")
def rr():
    name = "run_reranker_cut_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "run_reranker_cut.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def ctx() -> ReplayContext:
    return ReplayContext(
        period_bounds={
            "tune": (pd.Timestamp("2026-03-01"), pd.Timestamp("2026-07-31 23:59")),
            "report": (pd.Timestamp("2026-08-01"), pd.Timestamp("2026-10-31 23:59")),
        },
        price_table={
            "version": "prices-synthetic",
            "per_tokens": 1_000_000,
            "prices": [
                {"price_ref": "p-syn", "input": 1.0, "cached_input": 0.1, "output": 2.0}
            ],
        },
        catalogue={"models": [{"model_id": "syn-model", "price_ref": "p-syn"}]},
        seed=7,
    )


def chunk_rows(messages, dup=True) -> pd.DataFrame:
    """[SYNTHETIC] six unique chunks per message (+ one copy of the best)."""
    rows = []
    for m in messages:
        for i, s in enumerate((0.9, 0.8, 0.7, 0.6, 0.5, 0.4), start=1):
            rows.append((m, f"c-{i}", f"h-{m}-{i}", 100 * i, s))
        if dup:
            rows.append((m, "c-1", f"h-{m}-1", 100, 0.3))
    return pd.DataFrame(
        rows, columns=["message_id", "chunk_id", "h_exact", "n_chars", "relevancy"]
    )


def frame(n_rag=4, n_plain=2, n_workflow=1) -> pd.DataFrame:
    """[SYNTHETIC] requests: RAG LLM rows, LLM rows without RAG, workflow rows."""
    n = n_rag + n_plain + n_workflow
    return pd.DataFrame(
        {
            "ai_message_id": [f"m-{i}" for i in range(n)],
            "session_id": [f"s-{i // 2}" for i in range(n)],
            "period": "report",
            "llm_request": [True] * (n_rag + n_plain) + [False] * n_workflow,
            "a_rag_state": ["ok"] * n_rag + ["null"] * (n_plain + n_workflow),
            "bot_provider_model": "syn-model",
            "a_bill_inputTokens": 10_000.0,
            "a_bill_cachedInputTokens": 0.0,
            "a_bill_outputTokens": 100.0,
            "block_fees": 0.002,
            "block_token_cost": 0.05,
        },
        index=pd.RangeIndex(50, 50 + n),
    )


def version(rr, req, **kw):
    cls = rr.load_version_class()
    return cls(
        None,
        kw.get("floor", 0),
        kw.get("threshold"),
        kw.get("top_k"),
        chunks=chunk_rows(req["ai_message_id"]),
        tokens_per_char=SLOPE,
    )


def manifest():
    return build_manifest(
        {"synthetic": True},
        ctx(),
        code_commit="abc1234",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )


# --- thresholds and grid


def test_thresholds_are_quantiles_of_known_scores_only(rr):
    scores = pd.Series([0.1, 0.2, 0.3, 0.4, math.nan, 0.5])
    got = rr.threshold_grid(scores, (0.25, 0.5))
    assert got == {"q25": pytest.approx(0.2), "q50": pytest.approx(0.3)}


def test_grid_has_every_top_k_and_threshold_plus_none(rr):
    grid = rr.grid_points((3, 8), {"q10": 0.1, "q50": 0.5})
    assert len(grid) == 3 * 3
    assert (None, "none", None) in grid and (3, "q50", 0.5) in grid


# --- metrics


def test_point_metrics_split_raw_dedup_and_cut_tokens(rr):
    req = frame()
    out = version(rr, req, top_k=3).apply(req, ctx())
    m = rr.point_metrics(req, out, seed=1)
    assert m["eligible_requests"] == 4 and m["eligible_cost_known"] == 4
    assert m["raw_chunk_tokens"] == pytest.approx(4 * 2200 * SLOPE)
    assert m["dedup_tokens_s6_not_counted"] == pytest.approx(4 * 100 * SLOPE)
    assert m["saved_input_tokens"] == pytest.approx(4 * 1500 * SLOPE)
    assert m["chunk_share_removed"] == pytest.approx(1500 / 2100)
    raw = 6 * (10_000 + 200) / 1e6  # six LLM rows at the logged model
    assert m["cost_share_saved"] == pytest.approx(4 * 750 / 1e6 / raw)
    assert m["ci_low"] <= m["cost_share_saved"] <= m["ci_high"]
    assert m["score_mass_kept"] == pytest.approx(2.4 / 3.9)


def test_point_metrics_without_eligible_rows_are_missing_not_zero(rr):
    req = frame(n_rag=0)
    out = version(rr, req, top_k=3).apply(req, ctx())
    m = rr.point_metrics(req, out, seed=1)
    assert m["eligible_requests"] == 0
    assert math.isnan(m["chunk_share_removed"]) and math.isnan(m["score_mass_kept"])


# --- headline choice


def _pts(rows):
    cols = ["top_k", "threshold_rule", "threshold", "saved_input_tokens"]
    return pd.DataFrame(rows, columns=cols + ["score_mass_kept"])


def test_headline_is_most_saving_point_that_keeps_enough_score_mass(rr):
    tune = _pts(
        [
            (3, "none", None, 900.0, 0.80),  # saves most, keeps too little
            (5, "none", None, 600.0, 0.92),
            (8, "q10", 0.1, 600.0, 0.95),  # tie on saving: larger top_k wins
            (12, "none", None, 100.0, 0.99),
        ]
    )
    pick, passed = rr.choose_headline(tune, min_mass=0.9)
    assert passed and (pick["top_k"], pick["threshold_rule"]) == (8, "q10")


def test_headline_falls_back_to_the_gentlest_point(rr):
    tune = _pts([(3, "none", None, 900.0, 0.5), (12, "none", None, 100.0, 0.6)])
    pick, passed = rr.choose_headline(tune, min_mass=0.9)
    assert not passed and pick["top_k"] == 12 and pick["threshold_rule"] == "none"


# --- LeverResult


def test_lever_result_counts_only_the_cut_not_dedup(rr):
    req = frame()
    v = version(rr, req, top_k=3)
    out = v.apply(req, ctx())
    r = rr.headline_result(v, req, out, manifest(), extra=("[SYNTHETIC] note",))
    assert r.lever_id == "context.reranker_cut.observed_relevancy"
    assert r.step == "context" and r.baseline == "todays_models"
    assert r.correctness_state == "unmeasured"
    assert r.evidence_class == "hypothetical reconstruction"
    assert r.n_requests == 7 and r.n_eligible == 4
    assert float(r.saving["total"]) == pytest.approx(4 * 750 / 1e6)
    assert float(r.baseline_cost["total"]) == pytest.approx(6 * 10_200 / 1e6)
    llm = r.slices["llm_only"]
    assert float(llm["saved_input_tokens"]) == pytest.approx(4 * 750)
    assert float(llm["dedup_tokens_s6_not_counted"]) == pytest.approx(4 * 50)
    assert "baseline:fees" not in llm and "saving:fees" not in llm
    assert set(r.slices) == {"all", "llm_only"}
    assert r.ci_low is not None and r.ci_low <= r.ci_high
    assert "[SYNTHETIC] note" in r.assumptions


def test_unknown_cost_rows_leave_both_sides(rr):
    req = frame()
    req.loc[req.index[0], "bot_provider_model"] = "unpriced-model"
    v = version(rr, req, top_k=3)
    r = rr.headline_result(v, req, v.apply(req, ctx()), manifest(), extra=())
    llm = r.slices["llm_only"]
    assert float(llm["n_cost_known"]) == 5
    assert float(r.saving["total"]) == pytest.approx(3 * 750 / 1e6)
    # tokens need no price: every eligible row counts, and the priced ones are shown
    assert float(llm["saved_input_tokens"]) == pytest.approx(4 * 750)
    assert float(llm["n_eligible"]) == 4 and float(llm["n_eligible_cost_known"]) == 3


# --- sampling and text


def test_sample_is_seeded_and_eligible_only(rr):
    req = frame(n_rag=30)
    ok = req["a_rag_state"].eq("ok")
    a = rr.sample_requests(req, ok, 10, seed=3)
    b = rr.sample_requests(req, ok, 10, seed=3)
    assert list(a.index) == list(b.index) and len(a) == 10
    assert a["a_rag_state"].eq("ok").all()


def test_content_is_attached_by_position_and_chunk_id_is_checked(rr):
    derived = chunk_rows(["m-1"], dup=False)
    raw = derived[["message_id", "chunk_id"]].assign(
        content=[f"text {i}" for i in range(6)]
    )
    got = rr.attach_content(derived, raw)
    assert got["content"].tolist() == [f"text {i}" for i in range(6)]
    raw.loc[2, "chunk_id"] = "c-other"
    with pytest.raises(RuntimeError, match="chunk_id"):
        rr.attach_content(derived, raw)


def test_curve_rows_hold_numbers_and_labels_only(rr):
    req = frame()
    v = version(rr, req)
    curve = rr.curve(v, req, ctx(), {"q50": 0.6}, top_ks=(3,), floor=3, seed=1)
    allowed = {"top_k", "threshold_rule", "threshold", "floor"}
    text_cols = [
        c for c in curve.columns if curve[c].dtype == object and c not in allowed
    ]
    assert text_cols == []
    assert set(curve["threshold_rule"]) == {"none", "q50"}
    saved = curve.set_index(["top_k", "threshold_rule"])["saved_input_tokens"]
    assert saved[(3, "none")] >= 0 and np.isfinite(saved.to_numpy(float)).all()
