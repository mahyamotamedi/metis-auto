"""Missing slices and the session-clustered interval for a lever result
(sprint final Stage 1; plan "Slices, always"; ADR-0032, ADR-0036).

Every frame here is [SYNTHETIC]: invented numbers, no dataset content.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.lever_enrich import ENRICH_NOTE, enrich
from metis_auto.analysis.lever_result import LeverResult, build_manifest
from metis_auto.analysis.levers import ReplayContext, summarise_slices
from metis_auto.analysis.stats import cluster_bootstrap_ratio

NAN = np.nan


def frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """[SYNTHETIC] eight rows: two languages, three tenants, two bots, one
    workflow row with unknown cost, one long request (> 8,000 tokens)."""
    before = pd.DataFrame(
        {
            "llm_request": [True, True, True, True, True, True, False, True],
            "block_fees": [0.01, 0.0, 0.02, 0.0, 0.0, 0.01, NAN, 0.0],
            "block_token_cost": [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, NAN, 0.70],
            "u_lang": ["fa", "fa", "en", "en", "fa", None, "fa", "en"],
            "user_id": ["u1", "u1", "u2", "u2", "u1", "u3", "u1", "u1"],
            "bot_id": ["b1", "b1", "b2", "b2", "b1", "b2", "b1", "b1"],
            "session_id": ["s1", "s1", "s2", "s3", "s4", "s5", "s6", "s7"],
            "a_bill_inputTokens": [100, 200, 300, 9000, 500, 600, NAN, 700],
            "a_bill_cachedInputTokens": [0, 0, 0, 0, 0, 0, NAN, 0],
            "a_bill_outputTokens": [10, 20, 30, 40, 50, 60, NAN, 70],
            "bot_provider_model": ["m"] * 8,
        },
        index=range(100, 108),
    )
    after = before.copy()
    after["block_token_cost"] = before["block_token_cost"] * [
        0.5,
        1.0,
        0.9,
        0.2,
        1.0,
        0.7,
        1.0,
        0.4,
    ]
    return before, after


def ctx() -> ReplayContext:
    return ReplayContext(
        period_bounds={},
        price_table={"version": "prices-synthetic"},
        catalogue={},
        seed=7,
    )


def result_from(
    before: pd.DataFrame, after: pd.DataFrame, *, repriced: bool = False
) -> LeverResult:
    slices = summarise_slices(before, after)
    names = ("token_cost", "total") if repriced else ("fees", "token_cost", "total")
    if repriced:
        for s in slices.values():
            del s["baseline:fees"]
    top = slices["llm_only"]
    manifest = build_manifest(
        {"version": "synthetic"},
        ctx(),
        code_commit="abc1234",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    return LeverResult(
        lever_id="ctx.synthetic",
        step="context",
        version="ctx.synthetic",
        n_requests=len(before),
        n_eligible=4,
        baseline="todays_models" if repriced else "as_logged",
        baseline_cost={b: top[f"baseline:{b}"] for b in names},
        saving={b: top[f"saving:{b}"] for b in names},
        slices=slices,
        evidence_class="hypothetical reconstruction",
        correctness_state="unmeasured",
        assumptions=("synthetic",),
        manifest=manifest,
    )


def test_adds_lang_over_8k_tenant_and_traffic_weighted_slices():
    before, after = frames()
    out = enrich(result_from(before, after), before, after, before)
    keys = set(out.slices)
    assert {"lang:fa", "lang:en", "lang:unknown", "over_8k", "traffic_weighted"} <= keys
    assert {"tenant_rank:1", "tenant_rank:2", "tenant_rank:3"} <= keys
    # tenant u1 holds four of the seven LLM requests: rank 1, share 4/7
    assert out.slices["tenant_rank:1"]["n_requests"] == 4
    assert out.slices["tenant_rank:1"]["share"] == Decimal("0.571428571")
    # the 9,000-token request alone is over 8,000
    assert out.slices["over_8k"]["n_requests"] == 1
    assert out.slices["over_8k"]["saving:token_cost"] == Decimal("0.320000000")
    assert ENRICH_NOTE in out.assumptions


def test_ranks_never_ids():
    before, after = frames()
    out = enrich(result_from(before, after), before, after, before)
    text = out.to_json()
    for raw in ("u1", "u2", "u3", "b1", "b2", "s1"):
        assert f'"{raw}' not in text


def test_traffic_weighted_is_request_weighted_per_bot_share():
    before, after = frames()
    out = enrich(result_from(before, after), before, after, before)
    tw = out.slices["traffic_weighted"]
    llm = before["llm_request"]
    b = before[llm]
    base = b["block_fees"] + b["block_token_cost"]
    save = base - (after[llm]["block_fees"] + after[llm]["block_token_cost"])
    per_bot = pd.DataFrame({"b": base, "s": save, "bot": b["bot_id"]}).groupby("bot")
    sums, n = per_bot[["b", "s"]].sum(), per_bot.size()
    want = float(((sums["s"] / sums["b"]) * n).sum() / n.sum())
    assert float(tw["saving_share"]) == pytest.approx(want, abs=1e-9)
    assert float(tw["bot_mean_saving_share"]) == pytest.approx(
        float((sums["s"] / sums["b"]).mean()), abs=1e-9
    )


def test_existing_slices_are_kept_unchanged():
    before, after = frames()
    first = result_from(before, after)
    slices = {**first.slices, "over_8k": {"n_requests": Decimal(99)}}
    given = first.model_copy(update={"slices": slices})
    out = enrich(given, before, after, before)
    assert out.slices["over_8k"] == {"n_requests": Decimal(99)}
    assert out.slices["all"] == first.slices["all"]
    assert out.slices["llm_only"] == first.slices["llm_only"]


def test_interval_is_session_clustered_on_the_result_share():
    before, after = frames()
    out = enrich(result_from(before, after), before, after, before)
    llm = before["llm_request"]
    cols = ["block_fees", "block_token_cost"]
    den = before.loc[llm, cols].sum(axis=1).to_numpy()
    num = den - after.loc[llm, cols].sum(axis=1).to_numpy()
    est, lo, hi = cluster_bootstrap_ratio(
        num, den, before.loc[llm, "session_id"].to_numpy(), seed=7
    )
    assert (out.ci_low, out.ci_high) == (pytest.approx(lo), pytest.approx(hi))
    assert lo <= est <= hi


def test_existing_interval_is_not_replaced():
    before, after = frames()
    given = result_from(before, after).model_copy(
        update={"ci_low": 0.1, "ci_high": 0.2}
    )
    out = enrich(given, before, after, before)
    assert (out.ci_low, out.ci_high) == (0.1, 0.2)


def test_interval_refused_when_rows_do_not_reproduce_the_result():
    before, after = frames()
    other = after.copy()
    other["block_token_cost"] = before["block_token_cost"]  # saves nothing
    with pytest.raises(ValueError, match="do not reproduce"):
        enrich(result_from(before, after), before, other, before)


def test_repriced_result_slices_carry_no_fee_keys():
    before, after = frames()
    out = enrich(result_from(before, after, repriced=True), before, after, before)
    for name in ("lang:fa", "over_8k", "tenant_rank:1", "traffic_weighted"):
        assert not any("fees" in k for k in out.slices[name]), name


def test_empty_saving_gets_baseline_only_slices_and_no_interval():
    before, after = frames()
    given = result_from(before, after, repriced=True).model_copy(update={"saving": {}})
    out = enrich(given, before, after, before)
    assert out.ci_low is None and out.ci_high is None
    for name in ("lang:fa", "over_8k", "tenant_rank:1", "traffic_weighted"):
        assert not any(k.startswith("saving") for k in out.slices[name]), name
        assert "baseline:total" in out.slices[name] or name == "traffic_weighted"


def test_workflow_rows_add_nothing():
    before, after = frames()
    out = enrich(result_from(before, after), before, after, before)
    # the workflow row is Persian and tenant u1; it is counted in neither slice
    assert out.slices["lang:fa"]["n_requests"] == 3
    assert out.slices["tenant_rank:1"]["n_cost_known"] == 4


def test_frames_must_share_the_index():
    before, after = frames()
    with pytest.raises(ValueError, match="index"):
        enrich(result_from(before, after), before, after.iloc[1:], before)


def test_missing_column_is_stated_not_silently_skipped():
    before, after = frames()
    req = before.drop(columns=["u_lang"])
    out = enrich(result_from(before, after), before, after, req)
    assert not any(k.startswith("lang:") for k in out.slices)
    assert any(
        "language not computed" in a and "lever_enrich" in a for a in out.assumptions
    )
    assert "over_8k" in out.slices  # the other families are still added


def test_enrich_twice_adds_nothing_more():
    before, after = frames()
    once = enrich(result_from(before, after), before, after, before)
    assert enrich(once, before, after, before) == once
