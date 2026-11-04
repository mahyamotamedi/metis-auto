"""``scripts/decision_router_levers.py``: the rules-only decision router as a
full-data routing result (sprint final Stage 2; ADR-0047 point 4, ADR-0046
points 4-6, ADR-0045). Every frame, model, price and text is [SYNTHETIC]."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.lever_result import LeverResult
from metis_auto.analysis.levers import ReplayContext, with_blocks
from metis_auto.settings import load_settings
from metis_auto.wiring.from_settings import pipeline_config

ROOT = Path(__file__).resolve().parents[3]
NAN = np.nan
BASELINES = ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap")


def _limits(window: int = 100_000, out: int = 10_000) -> dict:
    return {"context_window": {"value": window}, "max_output_tokens": {"value": out}}


CATALOGUE = {
    "version": "cat-synthetic",
    "models": [
        {"model_id": "syn-incumbent", "price_ref": "p-inc", "enabled": False},
        {"model_id": "syn-low", "price_ref": "p-low", "enabled": True, "tier": 0}
        | _limits(),
        {"model_id": "syn-high", "price_ref": "p-high", "enabled": True, "tier": 1}
        | _limits(),
        {"model_id": "syn-premium", "price_ref": "p-prem", "enabled": False},
    ],
}
PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1,
    "prices": [
        {"price_ref": "p-inc", "input": "10", "output": "20", "cached_input": "5"},
        {"price_ref": "p-low", "input": "1", "output": "2", "cached_input": "0.5"},
        {"price_ref": "p-high", "input": "3", "output": "6", "cached_input": "1.5"},
        {"price_ref": "p-prem", "input": "100", "output": "200", "cached_input": "50"},
    ],
}
RULES = {
    "candidates": ["syn-low", "syn-high"],
    "candidates_jev": [],
    "avoid_long_context_tier": True,
    "retiring": [],
}
CTX = ReplayContext(
    period_bounds={}, price_table=PRICES, catalogue=CATALOGUE, seed=0, min_n=1
)
RATES = {
    "syn-low": {"input": 1.0, "output": 2.0, "cached": 0.5},
    "syn-high": {"input": 3.0, "output": 6.0, "cached": 1.5},
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    yield _load(
        "decision_router_levers_under_test", ROOT / "scripts/decision_router_levers.py"
    )
    sys.modules.pop("decision_router_levers_under_test", None)


@pytest.fixture(scope="module")
def cfg():
    return pipeline_config(load_settings(environ={}, dotenv=None, runtime=None))


def frame(n: int = 6) -> pd.DataFrame:
    """SYNTHETIC: rows 0-1 tier 0 (greetings), rows 2-5 tier 1."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "session_id": f"syn-s{i}",
                "user_message_id": f"m{i}",
                "turn": 0,
                "a_order": 0,
                "bot_id": "bot-a" if i % 2 else "bot-b",
                "user_id": "tenant-a" if i < 4 else "tenant-b",
                "u_n_chars": 30.0,
                "u_lang": "fa" if i < 3 else "en",
                "u_att_n": 0.0,
                "bot_n_functions": 0.0,
                "bot_provider_name": "syn-provider",
                "bot_provider_model": "syn-incumbent",
                "a_billing_state": "items",
                "a_bill_inputTokens": 100.0 + 9000.0 * (i == 5),
                "a_bill_cachedInputTokens": 0.0,
                "a_bill_outputTokens": 10.0,
                "a_bill_totalCost": 0.01,
                "a_n_per_call_only_items": 0,
                "llm_request": True,
            }
        )
    out = pd.DataFrame(rows)
    out.index = pd.RangeIndex(len(out)) * 10
    return with_blocks(out)


def flags(n: int = 6) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "message_id": [f"m{i}" for i in range(n)],
            "has_code": [False] * n,
            "has_coding_intent": [False] * n,
            "is_greeting": [True, True] + [False] * (n - 2),
            "label_state": ["ok"] * n,
        }
    )


def write(script, cfg, tmp_path, req=None):
    req = frame() if req is None else req
    tiers = script.rules_only.rules_only_tiers(req, flags(len(req)), cfg)
    return script.write_levers(
        req,
        tiers=tiers,
        ctx=CTX,
        rules=RULES,
        rates=RATES,
        premium_model="syn-premium",
        out_dir=tmp_path,
        code_commit="unknown",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 3, tzinfo=UTC),
        cached_separately=frozenset(),
        split="report",
        tenant_cap=0.35,
    )


def test_one_result_per_baseline_with_the_required_labels(script, cfg, tmp_path):
    paths = write(script, cfg, tmp_path)
    assert sorted(p.name for p in paths) == sorted(
        f"route.decision_router.rules_only.{b}.json" for b in BASELINES
    )
    res = LeverResult.from_json(
        (tmp_path / "route.decision_router.rules_only.todays_models.json").read_text()
    )
    text = " ".join(res.assumptions)
    assert "quality not proven" in text
    assert "rules-only" in text
    assert "THX-01" in text and "agreement 1.0" in text
    assert "Jev" in text and "72%" in text and "synthetic" in text.lower()
    assert res.step == "routing" and res.correctness_state == "unmeasured"
    assert res.evidence_class == "simulation"
    for key in ("all", "llm_only", "over_8k", "traffic_weighted", "routing"):
        assert key in res.slices
    assert any(k.startswith("lang:") for k in res.slices)
    assert any(k.startswith("tenant_rank:") for k in res.slices)


def test_never_routes_upward_and_fees_unchanged(script, cfg, tmp_path):
    write(script, cfg, tmp_path)
    for b in BASELINES:
        res = LeverResult.from_json(
            (tmp_path / f"route.decision_router.rules_only.{b}.json").read_text()
        )
        assert res.saving["token_cost"] >= 0, b
        if "fees" in res.saving:
            assert res.saving["fees"] == 0, b
        assert (b == "as_logged") == ("fees" in res.baseline_cost), b


def test_a_tier_with_no_eligible_candidate_keeps_the_incumbent(script, cfg, tmp_path):
    req = frame()
    req.loc[req.index[:2], "u_att_n"] = 1.0  # attachments: R-0 excludes every candidate
    write(script, cfg, tmp_path, req)
    res = LeverResult.from_json(
        (tmp_path / "route.decision_router.rules_only.todays_models.json").read_text()
    )
    assert res.slices["routing"]["reason:no_eligible_in_tier"] >= 1


def test_no_text_id_or_hash_reaches_the_files(script, cfg, tmp_path):
    paths = write(script, cfg, tmp_path)
    text = "".join(p.read_text() for p in paths)
    for leaked in ("syn-s0", "bot-a", "bot-b", "tenant-a", "tenant-b", "m0"):
        assert leaked not in text


def test_interval_and_missing_slices_filled(script, cfg, tmp_path):
    write(script, cfg, tmp_path)
    res = LeverResult.from_json(
        (tmp_path / "route.decision_router.rules_only.as_logged.json").read_text()
    )
    assert (res.ci_low is None) == (res.ci_high is None)
    assert res.slices["tenant_rank:1"]["share"] == Decimal("0.666666667")


def test_derive_writes_flags_without_text(script, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    pd.DataFrame(
        {
            "message_id": ["a", "b", "c"],
            "type": ["USER", "USER", "AI"],
            "content": ["hello", "x = 1\nprint(x)\n", "an answer"],
        }
    ).to_parquet(raw / "chat_message-00000-of-00001.parquet")
    out = tmp_path / "flags.parquet"
    table = script.derive(
        raw, out, pipeline_config(load_settings(environ={}, dotenv=None, runtime=None))
    )
    saved = pd.read_parquet(out)
    assert set(saved["message_id"]) == {"a", "b"}
    assert list(saved.columns) == list(table.columns)
    assert not any(
        saved[c].astype(str).str.contains("hello|print").any() for c in saved.columns
    )


def test_refuses_when_the_router_is_not_off(script):
    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    script.rules_only.require_offline(loaded.settings)
    bad = loaded.settings.model_copy(
        update={"router": loaded.settings.router.model_copy(update={"mode": "hosted"})}
    )
    with pytest.raises(SystemExit):
        script.rules_only.require_offline(bad)


def test_tune_and_report_results_do_not_overwrite_each_other(script, cfg, tmp_path):
    """The report file keeps the plain lever id; a tune run is marked ``.tune``."""
    req = frame()
    tiers = script.rules_only.rules_only_tiers(req, flags(len(req)), cfg)
    common = dict(
        tiers=tiers,
        ctx=CTX,
        rules=RULES,
        rates=RATES,
        premium_model="syn-premium",
        out_dir=tmp_path,
        code_commit="unknown",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 3, tzinfo=UTC),
        cached_separately=frozenset(),
        tenant_cap=0.35,
    )
    script.write_levers(req, split="report", **common)
    script.write_levers(req, split="tune", **common)
    names = {p.name for p in tmp_path.glob("*.json")}
    assert len(names) == 8
    tune = LeverResult.from_json(
        (tmp_path / "route.decision_router.rules_only.tune.as_logged.json").read_text()
    )
    assert tune.version == "route.decision_router.rules_only"
    assert tune.lever_id == "route.decision_router.rules_only.tune.as_logged"
