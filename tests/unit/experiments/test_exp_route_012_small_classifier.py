"""EXP-ROUTE-012 small classifier (sprint task R-C3; FR-ROUTE-01..05, FR-REQ-06,
H-5; ADR-0036, ADR-0038, ADR-0041, ADR-0045, ADR-XXXX
(small-classifier-routing)).

Every frame, bot, session, label, size, token count, rate and price here is
SYNTHETIC: invented values, no dataset content, no real price. The version lives
in ``experiments/``, so it is loaded by file path.
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

from metis_auto.analysis.lever_result import LeverResult, build_manifest
from metis_auto.analysis.levers import ReplayContext, combine, with_blocks
from metis_auto.analysis.routing_base import REASON_COLUMN, eligibility_frame

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/routing/exp-route-012-small-classifier"
NAN = np.nan
REASONING = {"name": "hidden_reasoning_billed_as_output", "verified": True}


def _limits(window: int = 100_000, out: int = 10_000) -> dict:
    return {"context_window": {"value": window}, "max_output_tokens": {"value": out}}


# SYNTHETIC catalogue and prices (per_tokens 1: cost = tokens x price).
CATALOGUE = {
    "version": "cat-synthetic",
    "models": [
        {"model_id": "syn-incumbent", "price_ref": "p-inc", "enabled": False},
        {"model_id": "syn-cheap-a", "price_ref": "p-a", "enabled": True} | _limits(),
        {"model_id": "syn-cheap-b", "price_ref": "p-b", "enabled": True}
        | _limits(window=500),
        {
            "model_id": "syn-reason",
            "price_ref": "p-r",
            "enabled": True,
            "capabilities": [REASONING],
        }
        | _limits(),
        {"model_id": "syn-pricey", "price_ref": "p-x", "enabled": True} | _limits(),
        {"model_id": "syn-premium", "price_ref": "p-prem", "enabled": False},
    ],
}
PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1,
    "prices": [
        {"price_ref": "p-inc", "input": "10", "output": "20", "cached_input": "5"},
        {"price_ref": "p-a", "input": "2", "output": "4", "cached_input": "1"},
        {"price_ref": "p-b", "input": "1", "output": "2", "cached_input": "0.5"},
        {"price_ref": "p-r", "input": "0.1", "output": "0.2", "cached_input": "0.05"},
        {"price_ref": "p-x", "input": "50", "output": "90", "cached_input": "25"},
        {"price_ref": "p-prem", "input": "100", "output": "200", "cached_input": "50"},
    ],
}
RULES = {
    "candidates": ["syn-reason", "syn-cheap-a", "syn-cheap-b", "syn-pricey"],
    "candidates_jev": [],
    "avoid_long_context_tier": True,
    "retiring": [],
}
CTX = ReplayContext(
    period_bounds={}, price_table=PRICES, catalogue=CATALOGUE, seed=0, min_n=2
)
# SYNTHETIC implied recorded-unit rates per 1M tokens.
RATES = {
    "syn-cheap-a": {"input": 1.0, "output": 2.0, "cached": 0.5},
    "syn-cheap-b": {"input": 0.5, "output": 1.0, "cached": NAN},
    "syn-reason": {"input": 0.1, "output": 0.1, "cached": 0.1},
}
SEP = frozenset()
PRIMARY = ("syn-cheap-a", "syn-cheap-b", "syn-pricey")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def v():
    yield _load("exp_route_012_under_test", EXP / "version.py")
    sys.modules.pop("exp_route_012_under_test", None)


@pytest.fixture(scope="module")
def script():
    yield _load(
        "small_classifier_levers_under_test",
        ROOT / "scripts/small_classifier_levers.py",
    )
    sys.modules.pop("small_classifier_levers_under_test", None)


def frame(*rows: dict) -> pd.DataFrame:
    """SYNTHETIC requests: each dict overrides the defaults (a simple request)."""
    defaults = {
        "session_id": "syn-s1",
        "turn": 0,
        "a_order": 0,
        "bot_id": "bot-syn",
        "user_id": "tenant-syn",
        "u_h_norm": NAN,
        "u_n_chars": 50.0,
        "u_lang": "fa",
        "n_prior_msgs": 0,
        "prior_chars": 0.0,
        "a_rag_n_queries": 0.0,
        "u_att_n": 0.0,
        "bot_n_functions": 0.0,
        "bot_ins_n_chars": 300.0,
        "bot_provider_name": "syn-provider",
        "bot_provider_model": "syn-incumbent",
        "a_billing_state": "items",
        "a_bill_inputTokens": 100.0,
        "a_bill_cachedInputTokens": 0.0,
        "a_bill_outputTokens": 10.0,
        "a_bill_totalCost": 0.01,
        "a_n_per_call_only_items": 0,
        "a_n_chars": 200,
        "a_is_json": False,
        "a_finish_reason": "STOP",
        "a_tool_n_calls": 0,
        "llm_request": True,
    }
    out = pd.DataFrame([defaults | r for r in rows])
    out.index = pd.RangeIndex(len(out)) * 10  # not 0..n-1, to catch positional bugs
    return with_blocks(out)


def rules_version(v, candidates=PRIMARY, **kw):
    kw.setdefault("max_u_chars", 200)
    kw.setdefault("max_input_tokens", 1000)
    return v.SmallClassifier(
        "rules", rules=RULES, candidates=candidates, cached_separately=SEP, **kw
    )


def manifest() -> object:
    return build_manifest(
        {"test": "synthetic"},
        CTX,
        code_commit="unknown",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 3, tzinfo=UTC),
    )


def results(v, req, version, **kw) -> dict[str, LeverResult]:
    out = combine(req, None, None, version, CTX)
    found = {}
    for key in ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap"):
        before, after = v.baseline_frames(
            req,
            out,
            CTX,
            baseline=key,
            premium_model="syn-premium",
            cached_separately=SEP,
            cheap_model="syn-cheap-a",
            rates=RATES,
        )
        found[key] = v.lever_result(
            before,
            after,
            out,
            version_id=version.name,
            baseline=key,
            manifest=manifest(),
            assumptions=v.assumptions(key, version),
            min_n=kw.get("min_n", 2),
            tenant_cap=0.35,
        )
    return found


def labelled(n_sessions: int, rows_per: int, seed: int = 1) -> tuple:
    """SYNTHETIC labelled frame: label = short message (plus noise)."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_sessions):
        for t in range(rows_per):
            chars = float(rng.integers(5, 400))
            rows.append(
                {
                    "session_id": f"syn-s{s}",
                    "turn": t,
                    "a_order": t,
                    "u_n_chars": chars,
                    "bot_id": f"bot-syn-{(s // 2) % 3}",
                    # SYNTHETIC duplicate family shared by sessions 2k and 2k+1
                    "u_h_norm": f"syn-fam-{s // 2}" if t == 0 else NAN,
                    "a_bill_inputTokens": 50.0 + chars,
                }
            )
    req = frame(*rows)
    noise = rng.random(len(req)) < 0.1
    labels = pd.Series((req["u_n_chars"] < 150) ^ noise, index=req.index)
    return req, labels


# --- labels and features ------------------------------------------------------


def test_labels_only_from_declared_source(v):
    req, labels = labelled(10, 3)
    with pytest.raises(ValueError, match="labels_source"):
        v.fit_logistic(req, labels, labels_source=None, l2=1.0, cached_separately=SEP)
    for undeclared in ("", "logged_model", "cost:cheapest", "a_is_json"):
        with pytest.raises(ValueError, match="labels_source"):
            v.fit_logistic(
                req, labels, labels_source=undeclared, l2=1.0, cached_separately=SEP
            )
    model = v.fit_logistic(
        req, labels, labels_source="synthetic:unit-test", l2=1.0, cached_separately=SEP
    )
    assert model.labels_source == "synthetic:unit-test"
    with pytest.raises(ValueError, match="model"):
        v.SmallClassifier(
            "logistic", rules=RULES, candidates=PRIMARY, cached_separately=SEP
        )
    with pytest.raises(ValueError, match="mode"):
        v.SmallClassifier("knn", rules=RULES, candidates=PRIMARY, cached_separately=SEP)
    clf = v.SmallClassifier(
        "logistic", rules=RULES, candidates=PRIMARY, cached_separately=SEP, model=model
    )
    out = combine(req, None, None, clf, CTX)
    assert out[v.SIMPLE].dtype == bool
    assert "synthetic:unit-test" in " ".join(v.assumptions("todays_models", clf))


def test_answer_derived_features_refused(v):
    req, labels = labelled(6, 2)
    for bad in ("a_n_chars", "a_is_json", "a_finish_reason", "a_tool_n_calls"):
        with pytest.raises(ValueError, match="before generation"):
            v.feature_matrix(req, features=("u_n_chars", bad), cached_separately=SEP)
    for bad in ("a_bill_outputTokens", "block_token_cost", "a_bill_totalCost"):
        with pytest.raises(ValueError, match="before generation"):
            v.fit_logistic(
                req,
                labels,
                labels_source="synthetic:unit-test",
                l2=1.0,
                features=("u_n_chars", bad),
                cached_separately=SEP,
            )
    # Changing what the answer was must not change which requests are simple.
    changed = req.assign(
        a_n_chars=5000, a_is_json=True, a_finish_reason="LENGTH", a_tool_n_calls=3
    )
    model = v.fit_logistic(
        req, labels, labels_source="synthetic:unit-test", l2=1.0, cached_separately=SEP
    )
    for clf in (
        rules_version(v),
        v.SmallClassifier(
            "logistic",
            rules=RULES,
            candidates=PRIMARY,
            cached_separately=SEP,
            model=model,
        ),
    ):
        a = combine(req, None, None, clf, CTX)[v.SIMPLE]
        b = combine(changed, None, None, clf, CTX)[v.SIMPLE]
        assert a.equals(b)


# --- cross-validation and small n ---------------------------------------------


def test_session_grouped_nested_cv(v):
    req, labels = labelled(30, 3)
    seen: list[pd.Index] = []

    def spy(train, y, **kw):
        seen.append(train.index)
        return v.fit_logistic(train, y, **kw)

    res = v.nested_cv(
        req,
        labels,
        labels_source="synthetic:unit-test",
        l2_grid=(0.1, 10.0),
        outer=3,
        inner=2,
        seed=7,
        min_n=10,
        cached_separately=SEP,
        fit=spy,
    )
    folds = res["outer_folds"]
    assert folds.index.equals(req.index)
    # No session and no duplicate family in two outer folds.
    assert (folds.groupby(req["session_id"]).nunique() == 1).all()
    fam = req["u_h_norm"].notna()
    assert (folds[fam].groupby(req.loc[fam, "u_h_norm"]).nunique() == 1).all()
    assert len(res["outer"]) == 3
    for f, fold in enumerate(res["outer"]):
        test_rows = folds.index[folds == f]
        assert fold["l2"] in (0.1, 10.0)
        assert fold["n_test"] == len(test_rows)
    # No fit (inner or outer) ever saw the rows of the outer fold it scores:
    # every fit's training set misses at least one whole outer fold.
    for idx in seen:
        assert any(not set(idx) & set(folds.index[folds == f]) for f in range(3))
    assert res["labels_source"] == "synthetic:unit-test"


def test_small_n_insufficient_or_wide_interval(v):
    small, small_labels = labelled(4, 3)  # 12 labels
    res = v.nested_cv(
        small,
        small_labels,
        labels_source="synthetic:unit-test",
        l2_grid=(1.0,),
        outer=2,
        inner=2,
        seed=0,
        min_n=30,
        cached_separately=SEP,
    )
    assert res["status"] == "insufficient"
    assert res["accuracy"] is None and res["ci"] is None
    rng = np.random.default_rng(3)
    req, _ = labelled(20, 2)  # 40 labels, pure noise
    noise = pd.Series(rng.random(len(req)) < 0.5, index=req.index)
    res = v.nested_cv(
        req,
        noise,
        labels_source="synthetic:unit-test",
        l2_grid=(1.0,),
        outer=2,
        inner=2,
        seed=0,
        min_n=30,
        cached_separately=SEP,
    )
    assert res["status"] == "estimated"
    lo, hi = res["ci"]
    assert lo <= res["accuracy"] <= hi and hi - lo > 0.1
    # Per bot: a bot below min_n is insufficient and carries no saving share.
    req = frame(
        *[{"session_id": f"syn-a{i}", "bot_id": "bot-big"} for i in range(3)],
        {"session_id": "syn-b0", "bot_id": "bot-small"},
    )
    res = results(v, req, rules_version(v), min_n=2)["todays_models"]
    by_n = {s["n_requests"]: s for k, s in res.slices.items() if k.startswith("bot_")}
    assert by_n[Decimal(3)]["insufficient"] == 0 and "saving_share" in by_n[3]
    assert by_n[Decimal(1)]["insufficient"] == 1 and "saving_share" not in by_n[1]


# --- routing rules -------------------------------------------------------------


def test_quality_not_proven_in_assumptions_without_labels(v):
    req = frame({}, {"session_id": "syn-s2", "u_n_chars": 900.0})
    for res in results(v, req, rules_version(v)).values():
        assert "quality not proven: no labels (P-1..P-3 not run)" in res.assumptions
        assert res.correctness_state == "unmeasured"
        assert res.evidence_class == "simulation"
        assert res.step == "routing"


def test_never_routes_upward(v):
    req = frame(
        {},  # simple, on the dear incumbent: moves to syn-cheap-b
        {"session_id": "syn-s2", "bot_provider_model": "syn-cheap-b"},  # cheapest
        {"session_id": "syn-s3", "bot_provider_model": "syn-cheap-a"},
        {"session_id": "syn-s4", "u_n_chars": 900.0},  # not simple
    )
    version = rules_version(v)
    out = combine(req, None, None, version, CTX)
    assert out[v.MOVED].tolist() == [True, False, True, False]
    assert out[v.ROUTED].tolist() == [
        "syn-cheap-b",
        "syn-cheap-b",
        "syn-cheap-b",
        "syn-incumbent",
    ]
    assert out.loc[20, v.REASON] == "moved" and out.loc[10, v.REASON] == (
        "no_cheaper_candidate"
    )
    assert (out[v.ROUTED] != "syn-pricey").all()
    for key, res in results(v, req, version).items():
        assert res.saving["token_cost"] >= 0, key
    for key in ("premium_gpt_5_5", "todays_models", "best_single_cheap", "as_logged"):
        before, after = v.baseline_frames(
            req,
            out,
            CTX,
            baseline=key,
            premium_model="syn-premium",
            cached_separately=SEP,
            cheap_model="syn-cheap-a",
            rates=RATES,
        )
        known = before["block_token_cost"].notna() & after["block_token_cost"].notna()
        diff = before["block_token_cost"] - after["block_token_cost"]
        assert (diff[known] >= 0).all(), key
        assert (diff[known & ~after[v.MOVED_B]] == 0).all(), key
        assert (diff[known & after[v.MOVED_B]] > 0).all(), key
    # todays_models moves exactly the rows the version moved.
    _, after = v.baseline_frames(
        req,
        out,
        CTX,
        baseline="todays_models",
        premium_model="syn-premium",
        cached_separately=SEP,
        cheap_model="syn-cheap-a",
        rates=RATES,
    )
    assert after[v.MOVED_B].equals(out[v.MOVED].astype(bool))


def test_fee_block_unchanged_by_routing(v):
    req = frame({"a_n_per_call_only_items": 3, "a_bill_totalCost": 0.02})
    out = combine(req, None, None, rules_version(v), CTX)
    assert out[v.MOVED].all()
    assert out["block_fees"].equals(req["block_fees"])
    for key, res in results(v, req, rules_version(v)).items():
        assert res.saving["fees"] == 0, key
        assert res.saving["total"] == res.saving["token_cost"], key
    assert results(v, req, rules_version(v))["as_logged"].baseline_cost[
        "fees"
    ] == Decimal("0.006000000")


def test_uses_routing_base_eligibility(v):
    req = frame(
        {"u_att_n": 1.0},  # attachments: no candidate
        {"session_id": "syn-s2", "u_att_n": NAN},  # unknown: no candidate
        {"session_id": "syn-s3", "bot_n_functions": 2.0},
        # 600 tokens: over syn-cheap-b's 500 window, so syn-cheap-a
        {"session_id": "syn-s4", "a_bill_inputTokens": 600.0},
        {"session_id": "syn-s5", "a_bill_outputTokens": NAN},  # unknown tokens
    )
    out = combine(req, None, None, rules_version(v), CTX)
    elig = eligibility_frame(req, CTX, rules=RULES, cached_separately=SEP)
    assert out[v.REASON].tolist()[:3] == [
        "attachments",
        "attachments_unknown",
        "functions",
    ]
    assert out.loc[40, v.REASON] == elig.loc[40, REASON_COLUMN] == "unknown_tokens"
    assert out.loc[30, v.ROUTED] == "syn-cheap-a"
    for i, model in out[v.TARGET].dropna().items():
        assert elig.loc[i, model]
    assert not out.loc[[0, 10, 20, 40], v.MOVED].any()


def test_reasoning_models_excluded_in_primary(v):
    sets = v.candidate_sets(RULES, CATALOGUE)
    assert sets["primary"] == PRIMARY
    assert sets["with_reasoning_models"] == tuple(RULES["candidates"])
    req = frame({})
    primary = rules_version(v, candidates=sets["primary"])
    out = combine(req, None, None, primary, CTX)
    assert out[v.ROUTED].tolist() == ["syn-cheap-b"]  # syn-reason is cheaper
    # A reasoning candidate in the primary set is refused, not silently priced.
    with pytest.raises(ValueError, match="hidden_reasoning_billed_as_output"):
        combine(
            req,
            None,
            None,
            rules_version(v, candidates=tuple(RULES["candidates"])),
            CTX,
        )
    secondary = rules_version(
        v, candidates=sets["with_reasoning_models"], include_reasoning_models=True
    )
    out = combine(req, None, None, secondary, CTX)
    assert out[v.ROUTED].tolist() == ["syn-reason"]
    assert primary.name == "route.small_classifier.rules"
    assert secondary.name == "route.small_classifier.rules.with_reasoning_models"
    text = " ".join(v.assumptions("todays_models", secondary))
    assert "lower bound on candidate cost, hidden reasoning not counted" in text


def test_unknown_routed_rate_is_unknown_saving(v):
    req = frame(
        {},  # moves to syn-cheap-b: no cached rate but no cached tokens -> known
        {"session_id": "syn-s2", "a_bill_cachedInputTokens": 40.0},  # needs cached
        {"session_id": "syn-s3", "u_n_chars": 900.0},  # not simple: saves 0
    )
    res = results(v, req, rules_version(v))["as_logged"]
    s = res.slices["llm_only"]
    assert s["n_saving_unknown"] == 1
    assert s["n_cost_known"] == 2  # the unknown row left both sides
    out = combine(req, None, None, rules_version(v), CTX)
    before, after = v.baseline_frames(
        req,
        out,
        CTX,
        baseline="as_logged",
        premium_model="syn-premium",
        cached_separately=SEP,
        cheap_model="syn-cheap-a",
        rates=RATES,
    )
    assert pd.isna(after.loc[10, "block_token_cost"])
    assert after.loc[20, "block_token_cost"] == before.loc[20, "block_token_cost"]
    # syn-cheap-b at 0.5 / 1.0 per 1M: 100 x 0.5 + 10 x 1.0 = 60 per 1M.
    assert after.loc[0, "block_token_cost"] == pytest.approx(60 / 1e6)
    # A target with no rate at all is unknown too.
    out2 = combine(req, None, None, rules_version(v), CTX)
    _, after2 = v.baseline_frames(
        req,
        out2,
        CTX,
        baseline="as_logged",
        premium_model="syn-premium",
        cached_separately=SEP,
        cheap_model="syn-cheap-a",
        rates={},
    )
    assert after2[v.SAVING_UNKNOWN].tolist() == [True, True, False]


# --- threshold choice and the writer ----------------------------------------------


def test_least_aggressive_threshold(v):
    table = {
        1000: {"moved_share": 0.10, "saving_share": 0.050},
        2000: {"moved_share": 0.20, "saving_share": 0.058},
        4000: {"moved_share": 0.30, "saving_share": 0.064},
        8000: {"moved_share": 0.35, "saving_share": 0.066},
    }
    assert v.least_aggressive(table, tolerance=0.01) == 2000
    assert v.least_aggressive(table, tolerance=0.0) == 8000


def test_write_levers_on_synthetic(v, script, tmp_path):
    req = frame(
        {},
        {"session_id": "syn-s2", "u_n_chars": 900.0},
        {"session_id": "syn-s3", "bot_id": "bot-two", "user_id": "tenant-two"},
        {"session_id": "syn-s4", "a_bill_inputTokens": 9000.0, "u_n_chars": 20.0},
    )
    paths = script.write_levers(
        req,
        ctx=CTX,
        rules=RULES,
        rates=RATES,
        max_u_chars=200,
        max_input_tokens=10_000,
        premium_model="syn-premium",
        out_dir=tmp_path,
        code_commit="unknown",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 3, tzinfo=UTC),
        cached_separately=SEP,
        min_n=1,
        tenant_cap=0.35,
    )
    names = sorted(p.name for p in paths)
    assert names == sorted(
        f"route.small_classifier.rules{s}.{b}.json"
        for s in ("", ".with_reasoning_models")
        for b in ("as_logged", "best_single_cheap", "premium_gpt_5_5", "todays_models")
    )
    res = LeverResult.from_json(
        (tmp_path / "route.small_classifier.rules.todays_models.json").read_text()
    )
    for key in ("all", "llm_only", "over_8k", "traffic_weighted", "routing"):
        assert key in res.slices
    assert res.slices["over_8k"]["n_requests"] == 1
    assert {k for k in res.slices if k.startswith("bot_rank:")} == {
        "bot_rank:1",
        "bot_rank:2",
    }
    tenants = {k: s for k, s in res.slices.items() if k.startswith("tenant_rank:")}
    assert tenants["tenant_rank:1"]["share"] == Decimal("0.750000000")
    assert tenants["tenant_rank:1"]["over_cap"] == 1
    assert res.slices["routing"]["moved_to:syn-cheap-b"] >= 1
    text = "".join(p.read_text() for p in paths)
    for leaked in ("syn-s1", "bot-syn", "bot-two", "tenant-syn", "tenant-two"):
        assert leaked not in text
