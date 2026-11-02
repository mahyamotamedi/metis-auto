"""EXP-CTX-001 token_cost saving (sprint task S-6b; FR-ACCT-01, FR-ACCT-02,
FR-CTX-03; ADR-0032, ADR-0036).

Every frame, model name, rate and price here is SYNTHETIC: invented numbers,
no dataset content, no real price. The version lives in ``experiments/``, so it
is loaded by file path.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.baselines_full import (
    lower_uncached_input,
    repriced_row_costs,
    token_counts,
)
from metis_auto.analysis.lever_result import LeverResult, build_manifest
from metis_auto.analysis.levers import ReplayContext, with_blocks
from metis_auto.wiring.lever_view import waterfall

ROOT = Path(__file__).resolve().parents[3]
VERSION_FILE = ROOT / "experiments/context/exp-ctx-001-within-message-dedup/version.py"
NAN = np.nan
REPRICED = ("premium_gpt_5_5", "todays_models", "best_single_cheap")

# SYNTHETIC price table: syn-tiered has a cheap tier up to 1,000 input tokens and
# a dear tier above it; per_tokens 1 keeps the arithmetic readable.
PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1,
    "prices": [
        {"price_ref": "p-small", "input": "1", "output": "2", "cached_input": "0.5"},
        {
            "price_ref": "p-tiered",
            "max_input_tokens": 1000,
            "input": "1",
            "output": "1",
            "cached_input": "0.1",
        },
        {
            "price_ref": "p-tiered",
            "min_input_tokens": 1001,
            "input": "2",
            "output": "2",
            "cached_input": "0.2",
        },
        {"price_ref": "p-premium", "input": "10", "output": "20", "cached_input": "5"},
    ],
}
CATALOGUE = {
    "models": [
        {"model_id": "syn-small", "price_ref": "p-small", "enabled": True},
        {"model_id": "syn-tiered", "price_ref": "p-tiered", "enabled": False},
        {"model_id": "syn-premium", "price_ref": "p-premium", "enabled": False},
    ]
}
CTX = ReplayContext(period_bounds={}, price_table=PRICES, catalogue=CATALOGUE, seed=0)
RATES = {"syn-small": 2.0, "syn-tiered": 4.0}  # SYNTHETIC implied input per 1M


@pytest.fixture(scope="module")
def version():
    name = "exp_ctx_001_saving_under_test"
    spec = importlib.util.spec_from_file_location(name, VERSION_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(name, None)


def _chunks(dup_chars: dict[str, int]) -> pd.DataFrame:
    """SYNTHETIC chunk rows: per message one chunk plus one exact copy of it."""
    rows = []
    for msg, chars in dup_chars.items():
        rows += [(msg, "c1", f"h-{msg}", chars), (msg, "c2", f"h-{msg}", chars)]
    return pd.DataFrame(rows, columns=["message_id", "chunk_id", "h_exact", "n_chars"])


def _requests(rows: list[tuple]) -> pd.DataFrame:
    """SYNTHETIC requests: (message, llm, model, input, cached, output, cost, fees)."""
    frame = pd.DataFrame(
        rows,
        columns=[
            "ai_message_id",
            "llm_request",
            "bot_provider_model",
            "a_bill_inputTokens",
            "a_bill_cachedInputTokens",
            "a_bill_outputTokens",
            "a_bill_totalCost",
            "a_n_per_call_only_items",
        ],
    )
    return with_blocks(frame)


def _manifest():
    return build_manifest(
        {"synthetic": True},
        CTX,
        code_commit="unknown",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )


def test_saved_tokens_are_uncached_input_only(version):
    # SYNTHETIC: m1 has 1,000 duplicate characters (500 tokens at 0.5 per char)
    # but only 100 uncached input tokens, so it saves 100; m2 has room for all
    # 500; m3 has no duplicate; m4 has a duplicate but unknown tokens.
    req = _requests(
        [
            ("m1", True, "syn-small", 1000, 900, 10, 1.0, 0),
            ("m2", True, "syn-small", 2000, 0, 10, 1.0, 0),
            ("m3", True, "syn-small", 2000, 0, 10, 1.0, 0),
            ("m4", True, "syn-small", NAN, NAN, NAN, 1.0, 0),
        ]
    )
    chunks = _chunks({"m1": 1000, "m2": 1000, "m4": 1000})
    dedup = version.WithinMessageDedup(chunks, tokens_per_char=0.5)
    out = dedup.apply(req, CTX)
    saved = out[version.SAVED_TOKENS]
    assert saved.iloc[:3].tolist() == [100.0, 500.0, 0.0]
    assert pd.isna(saved.iloc[3])  # unknown tokens: unknown saving, not zero

    # The helper lowers input and never touches the cached part.
    tokens = token_counts(req)
    lowered = lower_uncached_input(tokens, pd.Series([500.0, 500.0, 0.0, 500.0]))
    assert lowered["input"].iloc[:3].tolist() == [900.0, 1500.0, 2000.0]
    assert lowered["saved"].iloc[:3].tolist() == [100.0, 500.0, 0.0]
    pd.testing.assert_series_equal(lowered["cached"], tokens["cached"])
    pd.testing.assert_series_equal(lowered["output"], tokens["output"])


def test_as_logged_uses_model_implied_rate_and_unknown_stays_unknown(version):
    # SYNTHETIC: m1 (rate 2 per 1M) saves 1,000 tokens = 0.002 recorded units;
    # m2's model has no rate, so its saving is unknown (never 0) and the row
    # leaves both sides of the result; m3 has no duplicate, so it saves exactly
    # 0 even without a rate.
    req = _requests(
        [
            ("m1", True, "syn-small", 5000, 0, 10, 1.0, 1),
            ("m2", True, "syn-unrated", 5000, 0, 10, 1.0, 1),
            ("m3", True, "syn-unrated", 5000, 0, 10, 0.5, 0),
        ]
    )
    dedup = version.WithinMessageDedup(
        _chunks({"m1": 2000, "m2": 2000}), tokens_per_char=0.5, input_rate_per_m=RATES
    )
    out = dedup.apply(req, CTX)
    assert out[version.SAVING_KNOWN].tolist() == [True, False, True]
    before, after = version.baseline_frames(
        req, out, CTX, baseline="as_logged", premium_model="syn-premium"
    )
    result = version.lever_result(
        before, after, baseline="as_logged", manifest=_manifest()
    )
    assert result.saving["token_cost"] == Decimal("0.002")
    assert result.slices["llm_only"]["n_cost_known"] == Decimal(2)
    assert result.slices["llm_only"]["n_saving_unknown"] == Decimal(1)
    # The unknown row is out of the baseline too: 0.998 + 0.002 fee + 0.5.
    assert result.baseline_cost["total"] == Decimal("1.5")


def test_repriced_saving_can_cross_a_price_tier(version):
    # SYNTHETIC: 1,100 input tokens put the row in syn-tiered's dear tier
    # (1,100 x 2 + 10 x 2 = 2,220). Saving 200 tokens moves it to the cheap
    # tier (900 x 1 + 10 x 1 = 910): a saving of 1,310, more than 200 x 2.
    req = _requests([("m1", True, "syn-tiered", 1100, 0, 10, 1.0, 0)])
    tokens = token_counts(req)
    before = repriced_row_costs(req, CTX, premium_model="syn-premium")
    lowered = lower_uncached_input(tokens, pd.Series([200.0]))
    after = repriced_row_costs(
        req, CTX, premium_model="syn-premium", tokens=lowered, cheap_model="syn-small"
    )
    assert before.loc[0, "todays_models"] == 2220.0
    assert after.loc[0, "todays_models"] == 910.0

    out = version.WithinMessageDedup(_chunks({"m1": 400}), tokens_per_char=0.5).apply(
        req, CTX
    )
    b, a = version.baseline_frames(
        req, out, CTX, baseline="todays_models", premium_model="syn-premium"
    )
    result = version.lever_result(b, a, baseline="todays_models", manifest=_manifest())
    assert result.saving["token_cost"] == Decimal("1310")


@pytest.mark.parametrize("baseline", ("as_logged", *REPRICED))
def test_fees_block_unchanged(version, baseline):
    # SYNTHETIC: two LLM rows with per-call fees and duplicates, one workflow row.
    req = _requests(
        [
            ("m1", True, "syn-small", 5000, 0, 10, 1.0, 2),
            ("m2", True, "syn-tiered", 5000, 1000, 10, 2.0, 1),
            ("w1", False, "default", NAN, NAN, NAN, NAN, NAN),
        ]
    )
    dedup = version.WithinMessageDedup(
        _chunks({"m1": 2000, "m2": 2000, "w1": 2000}),
        tokens_per_char=0.5,
        input_rate_per_m=RATES,
    )
    out = dedup.apply(req, CTX)
    pd.testing.assert_series_equal(out["block_fees"], req["block_fees"])
    before, after = version.baseline_frames(
        req, out, CTX, baseline=baseline, premium_model="syn-premium"
    )
    pd.testing.assert_series_equal(after["block_fees"], before["block_fees"])
    result = version.lever_result(
        before, after, baseline=baseline, manifest=_manifest()
    )
    assert result.saving["fees"] == Decimal(0)
    if baseline == "as_logged":
        assert result.baseline_cost["fees"] == Decimal("0.006")
    else:
        # ADR-0036: fees are not priced in price-file units, so no fees key.
        assert "fees" not in result.baseline_cost
        assert "baseline:fees" not in result.slices["all"]
    assert result.saving["token_cost"] > 0


@pytest.mark.parametrize("baseline", ("as_logged", *REPRICED))
def test_lever_result_has_all_blocks_and_total(version, baseline):
    # SYNTHETIC: the same frame as above.
    req = _requests(
        [
            ("m1", True, "syn-small", 5000, 0, 10, 1.0, 2),
            ("m2", True, "syn-tiered", 5000, 1000, 10, 2.0, 1),
            ("w1", False, "default", NAN, NAN, NAN, NAN, NAN),
        ]
    )
    dedup = version.WithinMessageDedup(
        _chunks({"m1": 2000, "m2": 2000}), tokens_per_char=0.5, input_rate_per_m=RATES
    )
    out = dedup.apply(req, CTX)
    before, after = version.baseline_frames(
        req, out, CTX, baseline=baseline, premium_model="syn-premium"
    )
    result = version.lever_result(
        before, after, baseline=baseline, manifest=_manifest(), assumptions=("a",)
    )
    assert result.step == "context"
    assert result.version == "ctx.within_message_dedup"
    assert result.lever_id == f"ctx.within_message_dedup.{baseline}"
    assert result.baseline == baseline
    assert result.evidence_class == "hypothetical reconstruction"
    assert result.correctness_state == "unmeasured"
    assert (result.n_requests, result.n_eligible) == (3, 2)
    assert {"all", "llm_only"} <= set(result.slices)
    assert result.slices["all"]["n_requests"] == Decimal(3)
    assert result.slices["llm_only"]["n_requests"] == Decimal(2)
    assert set(result.saving) == {"fees", "token_cost", "total"}
    assert result.saving["total"] == result.saving["fees"] + result.saving["token_cost"]
    blocks = {"fees", "token_cost"} if baseline == "as_logged" else {"token_cost"}
    assert set(result.baseline_cost) == blocks | {"total"}
    assert result.baseline_cost["total"] == sum(
        (result.baseline_cost[b] for b in blocks), Decimal(0)
    )
    assert LeverResult.from_json(result.to_json()) == result
    view = waterfall(result)
    assert view.saving_total == result.saving["total"]
    if baseline == "as_logged":
        assert view.baseline_total == result.baseline_cost["total"]
    else:
        assert view.baseline_total is None  # fees unknown in price-file units
