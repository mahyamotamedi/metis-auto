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

from metis_auto.analysis.lever_result import LeverResult, build_manifest
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


def pricing(rr):
    return rr.Pricing(ctx(), "syn-model", "syn-model")


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
    v = version(rr, req, top_k=3)
    out = v.apply(req, ctx())
    m = rr.point_metrics(v, req, out, seed=1, pricing=pricing(rr))
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
    v = version(rr, req, top_k=3)
    m = rr.point_metrics(v, req, v.apply(req, ctx()), seed=1, pricing=pricing(rr))
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
    r = rr.headline_result(
        v, req, out, manifest(), pricing=pricing(rr), extra=("[SYNTHETIC] note",)
    )
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
    assert "baseline:fees" not in llm and float(llm["saving:fees"]) == 0  # ADR-0038
    assert {"all", "llm_only"} <= set(r.slices)
    # sprint final Stage 1: over_8k is added; families whose columns the synthetic
    # frame lacks are stated, never silently missing
    assert "over_8k" in r.slices
    assert any("not computed" in a and "lever_enrich" in a for a in r.assumptions)
    assert r.ci_low is not None and r.ci_low <= r.ci_high
    assert "[SYNTHETIC] note" in r.assumptions


def test_unknown_cost_rows_leave_both_sides(rr):
    req = frame()
    req.loc[req.index[0], "bot_provider_model"] = "unpriced-model"
    v = version(rr, req, top_k=3)
    out = v.apply(req, ctx())
    r = rr.headline_result(v, req, out, manifest(), pricing=pricing(rr), extra=())
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
    curve = rr.curve(
        v, req, ctx(), {"q50": 0.6}, top_ks=(3,), floor=3, seed=1, pricing=pricing(rr)
    )
    allowed = {"top_k", "threshold_rule", "threshold", "floor"}
    text_cols = [
        c for c in curve.columns if curve[c].dtype == object and c not in allowed
    ]
    assert text_cols == []
    assert set(curve["threshold_rule"]) == {"none", "q50"}
    saved = curve.set_index(["top_k", "threshold_rule"])["saved_input_tokens"]
    assert saved[(3, "none")] >= 0 and np.isfinite(saved.to_numpy(float)).all()


# --- four baselines (ADR-0036, ADR-0038)

RATES = {"syn-model": 2.0}  # [SYNTHETIC] implied input rate per 1M, recorded units
BASELINE_KEYS = ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap")
REPRICED = ("premium_gpt_5_5", "todays_models", "best_single_cheap")


def ctx4() -> ReplayContext:
    """[SYNTHETIC] prices for the logged, a premium and a cheap model."""
    base = ctx()
    prices = [
        *base.price_table["prices"],
        {"price_ref": "p-prem", "input": 5.0, "cached_input": 0.5, "output": 10.0},
        {"price_ref": "p-cheap", "input": 0.1, "cached_input": 0.01, "output": 0.2},
    ]
    models = [
        *base.catalogue["models"],
        {"model_id": "syn-premium", "price_ref": "p-prem"},
        {"model_id": "syn-cheap", "price_ref": "p-cheap"},
    ]
    return ReplayContext(
        period_bounds=base.period_bounds,
        price_table=base.price_table | {"prices": prices},
        catalogue={"models": models},
        seed=base.seed,
    )


def pricing4(rr, rates=RATES):
    return rr.Pricing(ctx4(), "syn-premium", "syn-cheap", rates=rates)


def result4(rr, req, baseline, rates=RATES):
    v = version(rr, req, top_k=3)
    out = v.apply(req, ctx4())
    return rr.headline_result(
        v,
        req,
        out,
        manifest(),
        pricing=pricing4(rr, rates),
        extra=(),
        baseline=baseline,
    )


def test_four_baselines_written_per_scorer(rr, tmp_path):
    req = frame()
    lexical = rr._load("lexical_overlap")
    rows = chunk_rows(req["ai_message_id"])
    rows["content"] = "text " + rows["h_exact"]
    queries = {m: f"text h-{m}-1" for m in req["ai_message_id"]}
    cls = rr.load_version_class()
    for scorer in (None, lexical):
        v = cls(scorer, 0, None, 3, chunks=rows, tokens_per_char=SLOPE, queries=queries)
        out = v.apply(req, ctx4())
        paths = rr.write_results(
            v,
            req,
            out,
            lambda baseline: manifest(),
            pricing=pricing4(rr),
            extra=("[SYNTHETIC] note",),
            out_dir=tmp_path,
        )
        name = v.scorer_name
        assert {p.name for p in paths} == {
            f"context.reranker_cut.{name}.{b}.json" for b in BASELINE_KEYS
        }
        for path in paths:
            r = LeverResult.from_json(path.read_text(encoding="utf-8"))
            assert r.lever_id == f"context.reranker_cut.{name}"
            assert path.name == f"{r.lever_id}.{r.baseline}.json"
    assert len(list(tmp_path.glob("*.json"))) == 8


def test_as_logged_uses_implied_input_rate_and_never_changes_fees(rr):
    r = result4(rr, frame(), "as_logged")
    # 4 eligible requests x 750 cut tokens x 2.0 per 1M (S-6's 50 tokens not counted)
    assert float(r.saving["token_cost"]) == pytest.approx(4 * 750 * 2.0 / 1e6)
    assert float(r.saving["fees"]) == 0
    assert float(r.baseline_cost["fees"]) == pytest.approx(6 * 0.002)  # recorded
    assert float(r.baseline_cost["token_cost"]) == pytest.approx(6 * 0.05)
    assert float(r.slices["llm_only"]["saving:fees"]) == 0


def test_model_without_implied_rate_is_unknown_not_zero(rr):
    req = frame()
    # one RAG row and one LLM row without RAG run on a model with no implied rate
    req.loc[req.index[[0, 4]], "bot_provider_model"] = "syn-no-rate"
    r = result4(rr, req, "as_logged")
    llm = r.slices["llm_only"]
    assert float(llm["n_saving_unknown"]) == 1  # the RAG row: saving unknown
    assert float(llm["n_cost_known"]) == 5  # it leaves both sides; nothing to cut: 0
    assert float(r.baseline_cost["token_cost"]) == pytest.approx(5 * 0.05)
    assert float(r.saving["token_cost"]) == pytest.approx(3 * 750 * 2.0 / 1e6)
    assert float(r.saving["token_cost"]) > 0


def test_repriced_baseline_has_no_fees_key(rr):
    for baseline in REPRICED:
        r = result4(rr, frame(), baseline)
        assert set(r.baseline_cost) == {"token_cost", "total"}, baseline
        assert float(r.saving["fees"]) == 0
        for name in ("all", "llm_only"):
            assert "baseline:fees" not in r.slices[name]
    assert "fees" in result4(rr, frame(), "as_logged").baseline_cost


def test_recorded_and_repriced_units_never_mixed(rr):
    req = frame()
    got = {b: result4(rr, req, b) for b in BASELINE_KEYS}
    logged = got["as_logged"]
    assert float(logged.baseline_cost["total"]) == pytest.approx(6 * (0.002 + 0.05))
    per_row = {"premium_gpt_5_5": 10_000 * 5.0 + 100 * 10.0}
    per_row |= {"todays_models": 10_000 * 1.0 + 100 * 2.0}
    per_row |= {"best_single_cheap": 10_000 * 0.1 + 100 * 0.2}
    cut = {"premium_gpt_5_5": 5.0, "todays_models": 1.0, "best_single_cheap": 0.1}
    for b in REPRICED:
        r = got[b]
        assert r.baseline_cost["total"] == r.baseline_cost["token_cost"]
        assert float(r.baseline_cost["total"]) == pytest.approx(6 * per_row[b] / 1e6)
        assert float(r.saving["total"]) == pytest.approx(4 * 750 * cut[b] / 1e6)
        assert any("price-file units" in a for a in r.assumptions)
        assert not any("recorded units" in a for a in r.assumptions)
    assert any("recorded units" in a for a in logged.assumptions)
    assert not any("price-file units" in a for a in logged.assumptions)


# --- cut-first (a): the real reranker through the injected-scorer interface ----


def test_real_reranker_refuses_to_start_when_weights_are_missing(rr, capsys, tmp_path):
    """The committed table is pinned, and an empty assets folder has no files:
    the run stops with code 2 before it reads any data."""
    code = rr.main(
        ["--scorers", "bge_reranker_v2_m3", "--reranker-assets", str(tmp_path)]
    )
    out = capsys.readouterr().out
    assert code == 2 and "no data was read" in out
    assert "model.safetensors: missing" in out
    assert "scripts/fetch_reranker_assets.py" in out
    assert "not pinned" not in out


def test_run_refuses_when_a_file_differs_from_its_pin(rr, capsys, tmp_path):
    from metis_auto.adapters.rerankers.assets import load_specs

    spec = load_specs(ROOT / "config/reference/rerankers.toml")["bge-reranker-v2-m3"]
    folder = tmp_path / spec.directory
    folder.mkdir(parents=True)
    for f in spec.files:
        (folder / f.name).write_bytes(b"synthetic, not the real weights")
    code = rr.main(
        ["--scorers", "bge_reranker_v2_m3", "--reranker-assets", str(tmp_path)]
    )
    out = capsys.readouterr().out
    assert code == 2 and "sha256 differs from the pin" in out


def test_committed_reranker_table_is_fully_pinned():
    from metis_auto.adapters.rerankers.assets import load_specs, unpinned_reasons

    spec = load_specs(ROOT / "config/reference/rerankers.toml")["bge-reranker-v2-m3"]
    assert unpinned_reasons(spec) == []
    assert spec.revision == "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    assert {f.name for f in spec.files} >= {
        "model.safetensors",
        "tokenizer.json",
        "config.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "sentencepiece.bpe.model",
    }
    assert all(len(f.sha256 or "") == 64 for f in spec.files)
    text = (ROOT / "config/reference/rerankers.toml").read_text(encoding="utf-8")
    assert "unpinned" not in text.split("version =")[1].splitlines()[0]


def test_default_scorers_never_include_the_real_reranker(rr):
    assert "bge_reranker_v2_m3" not in rr.DEFAULT_SCORERS
    assert set(rr.DEFAULT_SCORERS) < set(rr.SCORERS)


def test_missing_and_mismatching_files_are_named(rr, tmp_path):
    from metis_auto.adapters.rerankers.assets import (
        RerankerFile,
        RerankerSpec,
        not_ready_reasons,
    )

    good = tmp_path / "bge/rev1"
    good.mkdir(parents=True)
    (good / "a.bin").write_bytes(b"synthetic")
    import hashlib

    pin = hashlib.sha256(b"synthetic").hexdigest()
    spec = RerankerSpec(
        "bge",
        "syn/model",
        "rev1",
        (RerankerFile("a.bin", pin), RerankerFile("b.bin", pin)),
    )
    reasons = not_ready_reasons(spec, tmp_path)
    assert any("b.bin: missing" in r for r in reasons)
    assert not any("a.bin" in r for r in reasons)
    (good / "b.bin").write_bytes(b"tampered")
    assert any("b.bin: sha256 differs" in r for r in not_ready_reasons(spec, tmp_path))
    (good / "b.bin").write_bytes(b"synthetic")
    assert not_ready_reasons(spec, tmp_path) == []


def test_no_gpu_refuses_even_with_ready_weights(tmp_path):
    import hashlib

    from metis_auto.adapters.rerankers.assets import RerankerFile, RerankerSpec
    from metis_auto.adapters.rerankers.bge_local import check_ready

    d = tmp_path / "bge/rev1"
    d.mkdir(parents=True)
    (d / "a.bin").write_bytes(b"x")
    spec = RerankerSpec(
        "bge",
        "syn/model",
        "rev1",
        (RerankerFile("a.bin", hashlib.sha256(b"x").hexdigest()),),
    )
    assert any(
        "local GPU" in r for r in check_ready(spec, tmp_path, device_probe=lambda: None)
    )
    assert check_ready(spec, tmp_path, device_probe=lambda: "cuda") == []


def _fetch_module():
    spec = importlib.util.spec_from_file_location(
        "fetch_reranker_under_test", ROOT / "scripts" / "fetch_reranker_assets.py"
    )
    fetch = importlib.util.module_from_spec(spec)
    sys.modules["fetch_reranker_under_test"] = fetch
    spec.loader.exec_module(fetch)
    return fetch


def test_fetch_script_refuses_an_unpinned_table_and_downloads_nothing(capsys, tmp_path):
    table = tmp_path / "rerankers.toml"
    table.write_text(
        '[[rerankers]]\nref = "syn"\nmodel = "syn/model"\n', encoding="utf-8"
    )
    fetch = _fetch_module()
    assert fetch.main([], table=table, root=tmp_path / "assets") == 1
    assert "refused (nothing downloaded)" in capsys.readouterr().out
    assert not (tmp_path / "assets").exists()


def test_fetch_check_on_the_pinned_table_reports_missing_without_network(
    capsys, tmp_path
):
    """--check never downloads: on an empty folder every file is MISSING."""
    fetch = _fetch_module()
    code = fetch.main(
        ["--check"], table=ROOT / "config/reference/rerankers.toml", root=tmp_path
    )
    out = capsys.readouterr().out
    assert code == 1 and out.count("MISSING or wrong hash") == 6
    assert "refused" not in out and list(tmp_path.iterdir()) == []


def test_data_folder_for_rerankers_is_git_ignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "data/rerankers/" in lines


def test_injected_scorer_gets_its_name_as_the_lever_label(rr):
    cls = rr.load_version_class()

    def bge_reranker_v2_m3(query, texts):
        return [float(len(t)) for t in texts]

    chunks = chunk_rows(["m-0"]).assign(content="text")
    v = cls(
        bge_reranker_v2_m3,
        0,
        None,
        None,
        chunks=chunks,
        tokens_per_char=SLOPE,
        queries={"m-0": "q"},
    )
    assert v.lever_id == "context.reranker_cut.bge_reranker_v2_m3"
    assert any("text model" in a for a in v.assumptions)
