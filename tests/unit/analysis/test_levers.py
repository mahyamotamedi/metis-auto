"""Lever base: ``StepVersion``, ``ReplayContext``, ``combine`` (final plan S-1).

Every frame and version here is [SYNTHETIC]: invented numbers, no dataset content.
Review Focus 1: a request served from cache must not also be counted as a
context or routing saving.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from metis_auto.analysis.lever_result import LeverResult, Manifest
from metis_auto.analysis.levers import (
    ReplayContext,
    combine,
    summarise_slices,
    with_blocks,
)
from metis_auto.contracts._base import Privacy
from metis_auto.contracts.privacy import iter_fields

NAN = np.nan


def synthetic_frame() -> pd.DataFrame:
    """[SYNTHETIC] six rows. Row 0 is a cache hit that also has chunks; row 4 is a
    workflow row with unknown (not zero) cost."""
    return pd.DataFrame(
        {
            "llm_request": [True, True, True, True, False, True],
            "rag_n_chunks": [10, 5, 0, 8, 0, 0],
            "block_fees": [0.002, 0.0, 0.0, 0.004, NAN, 0.0],
            "block_token_cost": [0.10, 0.20, 0.10, 0.30, NAN, 0.10],
        },
        index=[10, 11, 12, 13, 14, 15],
    )


def make_ctx() -> ReplayContext:
    return ReplayContext(
        period_bounds={},
        price_table={"version": "prices-synthetic"},
        catalogue={},
        seed=7,
    )


class Spy:
    """Records which rows each version was given, and in which order."""

    calls: list[str]
    seen: dict[str, list[int]]

    def __init__(self) -> None:
        self.calls = []
        self.seen = {}

    def log(self, name: str, req: pd.DataFrame) -> None:
        self.calls.append(name)
        self.seen[name] = list(req.index)


class StubCache:
    step = "cache"

    def __init__(self, spy: Spy, hits: tuple[int, ...] = (10, 14)) -> None:
        self.name, self.spy, self.hits = "stub-cache", spy, hits

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        self.spy.log("cache", req)
        out = req.copy()
        out["served_from_cache"] = out.index.isin(self.hits)
        for col in ("block_fees", "block_token_cost"):
            out.loc[out["served_from_cache"], col] = 0.0
        return out


class StubContext:
    step = "context"

    def __init__(self, spy: Spy) -> None:
        self.name, self.spy = "stub-context", spy

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        self.spy.log("context", req)
        out = req.copy()
        has = out["rag_n_chunks"] > 0
        out.loc[has, "block_token_cost"] = out.loc[has, "block_token_cost"] * 0.8
        return out


class StubRouting:
    step = "routing"

    def __init__(self, spy: Spy) -> None:
        self.name, self.spy = "stub-routing", spy

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        self.spy.log("routing", req)
        out = req.copy()
        out["routed_model"] = "cheap-model"
        out["block_token_cost"] = out["block_token_cost"] * 0.5
        return out


def total_saving(base: pd.DataFrame, after: pd.DataFrame) -> Decimal:
    return summarise_slices(base, after)["llm_only"]["saving:total"]


def test_combine_applies_cache_then_context_then_routing():
    spy = Spy()
    out = combine(
        synthetic_frame(),
        StubCache(spy),
        StubContext(spy),
        StubRouting(spy),
        make_ctx(),
    )
    assert spy.calls == ["cache", "context", "routing"]
    # Cache sees every LLM row; context and routing never see hit rows.
    assert spy.seen["cache"] == [10, 11, 12, 13, 15]
    assert spy.seen["context"] == [11, 12, 13, 15]
    assert spy.seen["routing"] == [11, 12, 13, 15]
    # Same index and order as the input, new columns present for all rows.
    assert list(out.index) == [10, 11, 12, 13, 14, 15]
    assert out["served_from_cache"].tolist() == [
        True,
        False,
        False,
        False,
        False,
        False,
    ]
    # Row 11: 0.20 -> context 0.8 -> routing 0.5 (the order is visible in the value).
    assert out.loc[11, "block_token_cost"] == pytest.approx(0.20 * 0.8 * 0.5)
    # Row 13 has chunks too; row 12 has none, so only routing applies.
    assert out.loc[12, "block_token_cost"] == pytest.approx(0.10 * 0.5)


def test_cache_hit_gets_zero_context_and_routing_saving():
    base = synthetic_frame()
    spy = Spy()
    out = combine(base, StubCache(spy), StubContext(spy), StubRouting(spy), make_ctx())
    # The hit row's cost is exactly what the cache left: zero, unchanged afterwards.
    assert out.loc[10, "block_fees"] == 0.0
    assert out.loc[10, "block_token_cost"] == 0.0
    assert 10 not in spy.seen["context"]
    assert 10 not in spy.seen["routing"]
    # No routed model is recorded for a row that was never routed.
    assert pd.isna(out.loc[10, "routed_model"])


def test_combined_saving_is_below_sum_of_standalone_savings():
    base = synthetic_frame()
    ctx = make_ctx()
    cache_only = combine(base, StubCache(Spy()), None, None, ctx)
    context_only = combine(base, None, StubContext(Spy()), None, ctx)
    routing_only = combine(base, None, None, StubRouting(Spy()), ctx)
    spy = Spy()
    combined = combine(base, StubCache(spy), StubContext(spy), StubRouting(spy), ctx)

    standalone = [
        total_saving(base, f) for f in (cache_only, context_only, routing_only)
    ]
    assert all(s > 0 for s in standalone)
    assert total_saving(base, combined) < sum(standalone)


def test_workflow_rows_never_counted():
    base = synthetic_frame()
    spy = Spy()
    # The stub cache would hit the workflow row (14) if it were ever given to it.
    out = combine(base, StubCache(spy), StubContext(spy), StubRouting(spy), make_ctx())
    assert 14 not in spy.seen["cache"]
    assert not out.loc[14, "served_from_cache"]
    assert pd.isna(out.loc[14, "block_token_cost"])  # unknown stays unknown
    slices = summarise_slices(base, out)
    assert slices["llm_only"]["n_requests"] == Decimal(5)
    assert slices["llm_only"]["n_cache_hits"] == Decimal(1)
    # Workflow rows add nothing to a cost, and are reported, not zeroed.
    assert slices["all"]["n_requests"] == Decimal(6)
    assert slices["all"]["n_cost_known"] == Decimal(5)
    assert slices["all"]["baseline:total"] == slices["llm_only"]["baseline:total"]
    assert slices["all"]["n_cache_hits"] == Decimal(1)
    # The same hit is reported over all requests and over LLM requests only.
    assert slices["all"]["cache_hit_rate"] == Decimal("0.166666667")
    assert slices["llm_only"]["cache_hit_rate"] == Decimal("0.200000000")


def test_with_blocks_derives_fee_and_residual_and_keeps_unknown():
    req = pd.DataFrame(
        {
            "a_bill_totalCost": [0.010, 0.001, NAN],
            "a_n_per_call_only_items": [2.0, NAN, NAN],
        }
    )
    out = with_blocks(req)
    # 0.010 recorded = 2 x 0.002 fee + 0.006 residual; the fee is a derived proxy.
    assert out.loc[0, "block_fees"] == pytest.approx(0.004)
    assert out.loc[0, "block_token_cost"] == pytest.approx(0.006)
    # No per-call items means a zero fee, not an unknown one; all cost is residual.
    assert out.loc[1, "block_fees"] == 0.0
    assert out.loc[1, "block_token_cost"] == pytest.approx(0.001)
    # Unknown recorded cost stays unknown in both blocks, never zero.
    assert pd.isna(out.loc[2, "block_fees"]) and pd.isna(out.loc[2, "block_token_cost"])
    assert "block_fees" not in req  # the input frame is not modified


def test_every_result_has_all_and_llm_only_slices():
    base = synthetic_frame()
    spy = Spy()
    out = combine(base, StubCache(spy), StubContext(spy), StubRouting(spy), make_ctx())
    slices = summarise_slices(base, out)
    assert {"all", "llm_only"} <= set(slices)
    manifest = Manifest(
        data_revision="30f578f283b903cdbd06cd1b5f7f962f76452ded",
        code_commit="0" * 40,
        config_hash="a" * 64,
        seed=7,
        price_version="prices-synthetic",
        python_version="3.13.5",
        created_at="2026-11-02T09:00:00Z",
    )
    fields = dict(
        lever_id="synthetic.combined",
        step="cache",
        version="v0",
        n_requests=6,
        n_eligible=5,
        baseline="as_logged",
        baseline_cost={"total": Decimal("0.8")},
        saving={"total": Decimal("0.1")},
        evidence_class="simulation",
        correctness_state="unmeasured",
        manifest=manifest,
    )
    ok = LeverResult(slices=slices, **fields)
    assert {"all", "llm_only"} <= set(ok.slices)
    for missing in ("all", "llm_only"):
        partial = {k: v for k, v in slices.items() if k != missing}
        with pytest.raises(ValidationError, match=missing):
            LeverResult(slices=partial, **fields)


def test_lever_result_has_no_text_or_id_field():
    forbidden = (
        "text",
        "content",
        "prompt",
        "answer",
        "instruction",
        "message",
        "bot",
        "user",
        "session",
        "fingerprint",
    )
    for model in (LeverResult, Manifest):
        for path, privacy in iter_fields(model):
            assert privacy is not None, f"{model.__name__}.{path} is unclassified"
            assert privacy not in (
                Privacy.CONTENT,
                Privacy.FINGERPRINT,
                Privacy.REFERENCE,
            ), f"{model.__name__}.{path} is {privacy}"
            leaf = path.rsplit(".", 1)[-1]
            assert not any(word in leaf for word in forbidden), path
            assert leaf == "config_hash" or "hash" not in leaf, path
