"""EXP-CTX-004 history budget, stepped window (sprint task R-C2; FR-CTX-02,
FR-CTX-03, FR-ACCT-02, H-1, X4; ADR-0036, ADR-0038, ADR-0039,
ADR-0044).

Every frame, bot, size, token count, rate and price here is SYNTHETIC: invented
values, no dataset content, no real price. The version lives in
``experiments/``, so it is loaded by file path.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.lever_result import LeverResult
from metis_auto.analysis.levers import ReplayContext, combine, with_blocks

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/context/exp-ctx-004-history-budget"
NAN = np.nan
COEF = 0.5  # SYNTHETIC tokens per chunk character
INPUT_RATES = {"syn-small": 2.0}  # SYNTHETIC implied input per 1M
CACHED_RATES = {"syn-small": 1.0}  # SYNTHETIC implied cached input per 1M
BASE = {"bot-syn": 100.0}  # SYNTHETIC turn-0 base per bot
PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1,
    "prices": [
        {"price_ref": "p-small", "input": "1", "output": "2", "cached_input": "0.5"},
        {"price_ref": "p-premium", "input": "10", "output": "20", "cached_input": "5"},
    ],
}
CATALOGUE = {
    "models": [
        {"model_id": "syn-small", "price_ref": "p-small", "enabled": True},
        {"model_id": "syn-premium", "price_ref": "p-premium", "enabled": False},
    ]
}
CTX = ReplayContext(
    period_bounds={}, price_table=PRICES, catalogue=CATALOGUE, seed=0, min_n=1
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def v():
    yield _load("exp_ctx_004_under_test", EXP / "version.py")
    sys.modules.pop("exp_ctx_004_under_test", None)


@pytest.fixture(scope="module")
def script():
    yield _load(
        "history_budget_levers_under_test", ROOT / "scripts/history_budget_levers.py"
    )
    sys.modules.pop("history_budget_levers_under_test", None)


def frame(*rows: dict) -> pd.DataFrame:
    """SYNTHETIC requests: each dict overrides the defaults below."""
    defaults = {
        "session_id": "syn-s1",
        "turn": 0,
        "u_n_chars": 50.0,
        "a_n_chars": 50,
        "bot_id": "bot-syn",
        "bot_provider_name": "syn-provider",
        "bot_provider_model": "syn-small",
        "bot_memory_enabled": False,
        "bot_summarizer_mode": "IGNORE",
        "a_billing_state": "items",
        "a_bill_inputTokens": 100.0,
        "a_bill_cachedInputTokens": 0.0,
        "a_bill_outputTokens": 10.0,
        "a_bill_callCount": 1.0,
        "a_rag_chunk_chars": NAN,
        "a_bill_totalCost": 1.0,
        "a_n_per_call_only_items": 1,
        "llm_request": True,
    }
    out = pd.DataFrame([defaults | r for r in rows])
    if "a_order" not in out:
        out["a_order"] = out["turn"]
    return with_blocks(out)


def session(sid: str, sizes: list[float], last_input: float, **last) -> list[dict]:
    """SYNTHETIC session: prior turns with the given chars (u + a, split in
    halves), then one request whose input is ``last_input``."""
    rows = [
        {
            "session_id": sid,
            "turn": i,
            "u_n_chars": size / 2,
            "a_n_chars": int(size / 2),
            "a_bill_inputTokens": 100.0,
        }
        for i, size in enumerate(sizes)
    ]
    rows.append(
        {"session_id": sid, "turn": len(sizes), "a_bill_inputTokens": last_input} | last
    )
    return rows


def budget(v, req, budget_tokens, step_turns=1, base=BASE, **kw):
    return v.HistoryBudget(
        budget_tokens,
        step_turns,
        turns=req,
        turn0_base=base,
        tokens_per_char=COEF,
        input_rate_per_m=INPUT_RATES,
        cached_rate_per_m=CACHED_RATES,
        **kw,
    )


def last_row(out: pd.DataFrame, sid: str) -> pd.Series:
    rows = out[out["session_id"] == sid]
    return rows.loc[rows["turn"].idxmax()]


def test_budget_only_reduces_requests_above_it(v):
    # s1: history 400 tokens > 250. s2: history 50 tokens < 250.
    req = frame(
        *session("syn-s1", [100, 100, 200], 500.0), *session("syn-s2", [100], 150.0)
    )
    out = combine(req, None, budget(v, req, 250), None, CTX)
    over, under = last_row(out, "syn-s1"), last_row(out, "syn-s2")
    assert over[v.HIST_TOKENS] == 400 and under[v.HIST_TOKENS] == 50
    assert over[v.SAVED] > 0
    assert over[v.HIST_TOKENS] - over[v.SAVED] <= 250
    assert under[v.SAVED] == 0
    assert under["block_token_cost"] == req.loc[under.name, "block_token_cost"]
    assert (out.loc[out["turn"] == 0, v.SAVED] == 0).all()


def test_stepped_window_drops_whole_turns(v):
    # Prior turns of 100, 100 and 200 chars carry 100, 100 and 200 of 400 tokens.
    req = frame(*session("syn-s1", [100, 100, 200], 500.0))
    one = last_row(combine(req, None, budget(v, req, 350, 1), None, CTX), "syn-s1")
    assert one[v.TURNS_DROPPED] == 1 and one[v.SAVED] == 100  # oldest turn only
    two = last_row(combine(req, None, budget(v, req, 350, 2), None, CTX), "syn-s1")
    assert two[v.TURNS_DROPPED] == 2 and two[v.SAVED] == 200  # two at a time
    deep = last_row(combine(req, None, budget(v, req, 250, 1), None, CTX), "syn-s1")
    assert deep[v.TURNS_DROPPED] == 2 and deep[v.SAVED] == 200  # never a part turn


def test_memory_and_summarising_bots_excluded(v):
    req = frame(
        *session("syn-s1", [100, 100, 200], 500.0, bot_memory_enabled=True),
        *session("syn-s2", [100, 100, 200], 500.0, bot_summarizer_mode="AI_SUMMARIZE"),
        *session("syn-s3", [100, 100, 200], 500.0),
    )
    out = combine(req, None, budget(v, req, 250), None, CTX)
    assert last_row(out, "syn-s1")[v.HIST_STATE] == "memory"
    assert last_row(out, "syn-s2")[v.HIST_STATE] == "summariser"
    for sid in ("syn-s1", "syn-s2"):
        row = last_row(out, sid)
        assert row[v.SAVED] == 0
        assert row["block_token_cost"] == req.loc[row.name, "block_token_cost"]
    assert last_row(out, "syn-s3")[v.SAVED] > 0


def test_hist_tokens_unknown_without_turn0_median(v):
    # bot-syn has two turn-0 rows, bot-few one; min_n = 2. Turn-0 base is the
    # median of (effective input - chunk tokens) over single-call turn-0 rows.
    req = frame(
        {"session_id": "syn-a", "turn": 0, "a_bill_inputTokens": 150.0,
         "a_rag_chunk_chars": 100.0},  # 150 - 50 chunk tokens = 100
        {"session_id": "syn-b", "turn": 0, "a_bill_inputTokens": 100.0},
        {"session_id": "syn-b", "turn": 1, "a_bill_inputTokens": 400.0},
        {"session_id": "syn-c", "turn": 0, "bot_id": "bot-few"},
        {"session_id": "syn-c", "turn": 1, "bot_id": "bot-few",
         "a_bill_inputTokens": 400.0},
    )  # fmt: skip
    base = v.turn0_base(req, tokens_per_char=COEF, min_n=2)
    assert base.to_dict() == {"bot-syn": 100.0}
    with pytest.raises(ValueError):
        v.turn0_base(req, tokens_per_char=COEF, min_n=None)
    out = combine(req, None, budget(v, req, 100, base=base), None, CTX)
    known, unknown = last_row(out, "syn-b"), last_row(out, "syn-c")
    assert known[v.HIST_TOKENS] == 300
    assert pd.isna(unknown[v.HIST_TOKENS])  # unknown, never 0
    assert unknown[v.HIST_STATE] == "unknown" and unknown[v.SAVED] == 0


def test_multi_call_request_has_unknown_history(v):
    req = frame(*session("syn-s1", [100, 100], 500.0, a_bill_callCount=4.0))
    row = last_row(combine(req, None, budget(v, req, 100), None, CTX), "syn-s1")
    assert pd.isna(row[v.HIST_TOKENS]) and row[v.HIST_STATE] == "multi_call"
    assert row[v.SAVED] == 0


def test_removed_tokens_come_from_cached_first(v):
    # History 800 over two equal turns; budget 500 drops the oldest: 400 tokens.
    req = frame(*session("syn-s1", [100, 100], 900.0, a_bill_cachedInputTokens=300.0))
    row = last_row(combine(req, None, budget(v, req, 500), None, CTX), "syn-s1")
    assert row[v.SAVED] == 400
    assert row[v.SAVED_CACHED] == 300  # cached part first
    assert row[v.SAVED_UNCACHED_ONLY] == 400  # sensitivity: S-6 rule
    primary_cut = (300 * 1.0 + 100 * 2.0) / 1e6
    assert row["block_token_cost"] == pytest.approx(1.0 - 1 * 0.002 - primary_cut)
    assert row[v.CUT_UNCACHED_ONLY] == pytest.approx(400 * 2.0 / 1e6)


def test_fees_block_unchanged(v):
    req = frame(*session("syn-s1", [100, 100, 200], 500.0))
    out = combine(req, None, budget(v, req, 250), None, CTX)
    assert last_row(out, "syn-s1")[v.SAVED] > 0
    pd.testing.assert_series_equal(out["block_fees"], req["block_fees"])
    for key in ("as_logged", "premium_gpt_5_5"):
        before, after = v.baseline_frames(
            req, out, CTX, baseline=key, premium_model="syn-premium"
        )
        pd.testing.assert_series_equal(before["block_fees"], after["block_fees"])


def test_gated_rows_get_no_saving(v):
    req = frame(*session("syn-s1", [100, 100, 200], 500.0))
    req["memo_status"] = None
    req.loc[req.index[-1], "memo_status"] = "skipped_phatic"
    row = last_row(combine(req, None, budget(v, req, 250), None, CTX), "syn-s1")
    assert row[v.HIST_STATE] == "gated" and row[v.SAVED] == 0
    assert row["block_token_cost"] == req.loc[row.name, "block_token_cost"]


def test_parameters_have_no_default(v):
    for cls, names in (
        (v.HistoryBudget, ("budget_tokens", "step_turns")),
        (v.HalfOnLong, ("min_input_tokens", "step_turns")),
    ):
        params = inspect.signature(cls).parameters
        for name in names:
            assert params[name].default is inspect.Parameter.empty
    req = frame(*session("syn-s1", [100], 500.0))
    kw = dict(turns=req, turn0_base=BASE, tokens_per_char=COEF)
    for bad in ((None, 1), (2000, None), (0, 1), (2000, 0), (True, 1)):
        with pytest.raises(ValueError):
            v.HistoryBudget(*bad, **kw)
    with pytest.raises(ValueError):
        v.HalfOnLong(None, 1, **kw)


def test_half_budget_only_on_long_requests(v):
    # Long: input 10,100 > 8,000, history 10,000 over two equal turns; half =
    # 5,000, so the oldest turn goes. Short: input 600, untouched.
    req = frame(
        *session("syn-long", [100, 100], 10_100.0),
        *session("syn-short", [100, 100], 600.0),
    )
    half = v.HalfOnLong(
        8000, 1, turns=req, turn0_base=BASE, tokens_per_char=COEF,
        input_rate_per_m=INPUT_RATES, cached_rate_per_m=CACHED_RATES,
    )  # fmt: skip
    assert half.name == "ctx.history_budget.half_over_8k"
    out = combine(req, None, half, None, CTX)
    assert last_row(out, "syn-long")[v.SAVED] == 5000
    assert last_row(out, "syn-short")[v.SAVED] == 0
    assert bool(last_row(out, "syn-long")[v.OVER_8K])


def test_result_labelled_upper_bound(v, script, tmp_path):
    req = frame(
        *session("syn-s1", [100, 100, 200], 500.0),
        *session("syn-long", [100, 100], 10_100.0, a_bill_cachedInputTokens=600.0),
        {"session_id": "syn-w", "turn": 1, "bot_provider_name": "workflow",
         "llm_request": False, "a_bill_inputTokens": NAN, "a_bill_totalCost": NAN},
    )  # fmt: skip
    paths = script.write_levers(
        req,
        turns=req,
        turn0_base=BASE,
        ctx=CTX,
        variants=script.VARIANTS,
        tokens_per_char=COEF,
        input_rate_per_m=INPUT_RATES,
        cached_rate_per_m=CACHED_RATES,
        premium_model="syn-premium",
        out_dir=tmp_path,
        code_commit="unknown",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
        config_extra={"split": "synthetic"},
    )
    results = [LeverResult.from_json(p.read_text()) for p in paths]
    assert len(results) == 4 * 4  # variants x baselines
    ids = {r.lever_id for r in results}
    assert "ctx.history_budget.b4000.as_logged" in ids
    assert "ctx.history_budget.half_over_8k.best_single_cheap" in ids
    for r in results:
        assert r.step == "context"
        assert r.evidence_class == "hypothetical reconstruction"
        assert r.correctness_state == "unmeasured"
        text = " ".join(r.assumptions)
        assert "upper bound" in text
        assert "tokens only, quality not measured (FR-CTX-03)" in text
        assert {"all", "llm_only", "over_8k"} <= set(r.slices)
        assert r.saving["fees"] == 0
        if r.baseline != "as_logged":
            assert "fees" not in r.baseline_cost
    logged = {r.version: r for r in results if r.baseline == "as_logged"}
    b2000 = logged["ctx.history_budget.b2000"].slices["history_budget"]
    assert b2000["n_reduced"] == 1  # history 400 fits; only the long one is cut
    hb = logged["ctx.history_budget.half_over_8k"].slices["history_budget"]
    assert hb["n_reduced"] == 1 and hb["saved_tokens"] == 5000
    assert hb["saved_tokens_from_cached"] == 600
    assert hb["saved_tokens_uncached_only"] == 5000
    assert hb["saved_share_top_bot"] == 1  # one SYNTHETIC bot: rank share only
    text = "".join(p.read_text() for p in paths)
    for secret in ("syn-s1", "syn-long", "bot-syn"):
        assert secret not in text
