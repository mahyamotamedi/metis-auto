"""Offline logic of ``scripts/measure_pipeline_b_overhead.py`` (final plan L-1,
Pipeline B). Every frame, version and file here is [SYNTHETIC]; the clock is
injected, so timings are exact and no real data is read.

Traces: QA-LAT (Q-14, 100 ms p95), FR-ROUTE-04, ADR-0032,
ADR-0055.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from test_knn_router import ctx as knn_ctx
from test_knn_router import frame as knn_frame

from metis_auto.analysis.lever_result import LeverResult, Manifest

ROOT = Path(__file__).resolve().parents[3]
CREATED = datetime(2026, 11, 3, tzinfo=UTC)
BASELINES = ("as_logged", "todays_models", "premium_gpt_5_5", "best_single_cheap")


@pytest.fixture(scope="module")
def mo():
    name = "measure_pipeline_b_overhead_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "measure_pipeline_b_overhead.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeClock:
    """[SYNTHETIC] nanosecond clock that only moves when told."""

    def __init__(self) -> None:
        self.now = 0

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += int(ms * 1e6)


class FakeVersion:
    """[SYNTHETIC] version: each ``apply`` costs ``ms`` on the fake clock."""

    step = "routing"
    name = "fake"

    def __init__(self, clock: FakeClock, ms: float) -> None:
        self.clock, self.ms, self.calls = clock, ms, 0

    def apply(self, req: pd.DataFrame, ctx) -> pd.DataFrame:
        self.calls += 1
        self.clock.advance(self.ms)
        return req.copy()


def requests(n: int = 40) -> pd.DataFrame:
    """[SYNTHETIC] scoped requests: tune/report periods, three split labels,
    LLM and workflow rows, four tenants (one large)."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "session_id": f"synthetic-session-{i // 2}",
                "user_id": "synthetic-tenant-big" if i % 4 else f"synthetic-t{i % 3}",
                "bot_id": "synthetic-bot",
                "a_order": i,
                "period": "tune" if i % 5 else "report",
                "split": ("tune", "tune", "report", "excluded")[i % 4],
                "llm_request": i % 7 != 0,
            }
        )
    return pd.DataFrame(rows, index=pd.RangeIndex(100, 100 + n))


def lever_file(folder: Path, lever_id: str, version: str, step: str) -> Path:
    """[SYNTHETIC] ``LeverResult`` file."""
    result = LeverResult(
        lever_id=lever_id,
        step=step,
        version=version,
        n_requests=10,
        n_eligible=5,
        baseline=lever_id.rsplit(".", 1)[1],
        baseline_cost={"token_cost": Decimal("1")},
        saving={"token_cost": Decimal("0.1")},
        slices={"all": {}, "llm_only": {}},
        evidence_class="simulation",
        correctness_state="unmeasured",
        assumptions=("synthetic fixture",),
        manifest=Manifest(
            data_revision="0" * 40,
            code_commit="abcdef1",
            config_hash="0" * 64,
            seed=7,
            price_version="prices-synthetic-1",
            python_version="3.13.0",
            created_at=CREATED,
        ),
    )
    path = folder / f"{lever_id}.json"
    path.write_text(result.to_json(), encoding="utf-8")
    return path


def test_overhead_fields_filled_and_labelled_offline_estimate(mo, tmp_path):
    paths = [
        lever_file(tmp_path, f"rb3.knn-router.k-5.tune.{b}", "route.knn.k5", "routing")
        for b in BASELINES
    ]
    stats = {"n": 1000, "p50_ms": 1.5, "p95_ms": 3.25, "max_ms": 9.0}
    mo.write_overhead(paths, stats, machine="SYNTHETIC-OS x86_64", caveat="c")
    for path in paths:
        r = LeverResult.from_json(path.read_text(encoding="utf-8"))
        assert (r.overhead_ms_p50, r.overhead_ms_p95) == (1.5, 3.25)
        label = [a for a in r.assumptions if a.startswith("Overhead:")]
        assert len(label) == 1
        assert label[0].startswith(
            "Overhead: offline per-request estimate, tune period, one-row apply, "
            "no load test; machine SYNTHETIC-OS x86_64"
        )
        assert "synthetic fixture" in r.assumptions
        assert r.manifest.code_commit == "abcdef1"  # the saving is unchanged
        sample = [a for a in r.assumptions if a.startswith("Overhead sample:")]
        assert len(sample) == 1 and "report-period" in sample[0]

    # Unmeasured: None, never 0, and said so.
    mo.write_overhead(paths, None, machine="SYNTHETIC-OS", reason="no data")
    r = LeverResult.from_json(paths[0].read_text(encoding="utf-8"))
    assert r.overhead_ms_p50 is None and r.overhead_ms_p95 is None
    assert [a for a in r.assumptions if a.startswith("Overhead:")] == [
        "Overhead: not measured (no data); fields left empty, never 0"
    ]


def test_samples_only_tune_period_llm_rows(mo):
    req = requests()
    rows = mo.sample_tune_rows(req, 1000, seed=1, tenant_cap=1.0)
    assert len(rows) > 0
    assert rows["period"].eq("tune").all()
    assert rows["split"].eq("tune").all()
    assert rows["llm_request"].all()
    pool = req["period"].eq("tune") & req["split"].eq("tune") & req["llm_request"]
    assert set(rows.index) == set(req.index[pool])  # fewer than n: all of them


def test_tenant_cap_applied_to_sample(mo):
    req = requests(400)
    rows = mo.sample_tune_rows(req, 50, seed=3, tenant_cap=0.35)
    share = rows["user_id"].value_counts(normalize=True).max()
    assert share <= 0.35
    assert len(rows) <= 50


def test_same_seed_same_sample(mo):
    req = requests(400)
    a = mo.sample_tune_rows(req, 30, seed=11, tenant_cap=0.35)
    b = mo.sample_tune_rows(req, 30, seed=11, tenant_cap=0.35)
    c = mo.sample_tune_rows(req, 30, seed=12, tenant_cap=0.35)
    assert a.index.tolist() == b.index.tolist()
    assert a.index.tolist() != c.index.tolist()


def test_fit_time_not_included_for_knn(mo):
    clock = FakeClock()

    def build():  # "fitting" costs 5 s on the clock, before timing starts
        clock.advance(5000)
        return FakeVersion(clock, ms=2.0)

    rows = requests(8)
    stats, version = mo.measure_version(build, rows, None, clock=clock)
    assert stats["n"] == 8
    assert stats["p50_ms"] == stats["p95_ms"] == stats["max_ms"] == 2.0
    assert version.calls == 9  # one warm-up, not timed

    # The real rb3 builder fits the router on the training frame it is given.
    train = knn_frame(6)
    st = {
        "ctx": knn_ctx(),
        "routing": {"candidates": ["cheap"], "avoid_long_context_tier": True},
        "candidates": ["cheap"],
    }
    router = mo.rb3_builder(st, train, frozenset(), k=3)()
    assert router.name == "route.knn.k3" and len(router._x) == len(train)
    wide = mo.rb3_builder(st, train, frozenset(), k=3, candidates=["cheap", "mid"])()
    assert wide.candidates == ("cheap", "mid")


def test_unknown_lever_id_fails_clearly(mo):
    with pytest.raises(SystemExit, match="no Pipeline B version"):
        mo.spec_for("cache.popular_question.first_turn")
    with pytest.raises(SystemExit, match="no Pipeline B version"):
        mo.spec_for("rb3.knn-router.k-x.tune.as_logged")
    spec = mo.spec_for("rb2.cross-turn.k-all.ptr-8.ledger.todays_models")
    assert (spec.family, spec.step, spec.version) == (
        "rb2",
        "context",
        "cross_turn_chunks.ptr8.ledger.all",
    )
    assert spec.params == {"window": None, "pointer": 8, "ledger": True}
    assert mo.spec_for("rb1.retrieval-cache.ttl-7d.user.tune.as_logged").version == (
        "retrieval_result_cache.ttl_7d"
    )
    # Report-split and secondary results map to the same version as their tune
    # counterparts (overhead is per version).
    assert mo.spec_for("rb1.retrieval-cache.ttl-1d.user.report.as_logged").version == (
        "retrieval_result_cache.ttl_1d"
    )
    rb2r = mo.spec_for("rb2.cross-turn.k-1.ptr-8.pointer.report.todays_models")
    assert rb2r.version == "cross_turn_chunks.ptr8.k1"
    wr = mo.spec_for("rb3.knn-router.with_reasoning_models.k-5.report.as_logged")
    assert (wr.version, wr.params) == (
        "route.knn.with_reasoning_models.k5",
        {"k": 5, "with_reasoning": True},
    )
    assert mo.spec_for("rb3.knn-router.k-5.report.as_logged").version == "route.knn.k5"
    with pytest.raises(SystemExit, match="no Pipeline B version"):
        mo.main(["route.small_classifier.rules.as_logged", "--dry-run"])


def test_summary_has_no_ids_or_text(mo, tmp_path):
    req = requests(40)
    rows = mo.sample_tune_rows(req, 10, seed=1, tenant_cap=0.35)
    measured = [
        {
            "family": "rb3",
            "step": "routing",
            "version": "route.knn.k5",
            "files": 4,
            "stats": {"n": len(rows), "p50_ms": 1.0, "p95_ms": 2.0, "max_ms": 3.0},
        },
        {
            "family": "rb1",
            "step": "cache",
            "version": "retrieval_result_cache.ttl_1d",
            "files": 4,
            "stats": None,
            "reason": "no data",
        },
    ]
    payload = mo.summary_payload(
        measured,
        sample=mo.sample_record(rows, n=10, seed=1, tenant_cap=0.35),
        machine="SYNTHETIC-OS x86_64",
        created_at=CREATED,
    )
    text = json.dumps(payload)
    for col in ("session_id", "user_id", "bot_id"):
        for value in req[col].unique():
            assert str(value) not in text
    assert "synthetic-" not in text
    by = {v["version"]: v for v in payload["versions"]}
    assert by["route.knn.k5"]["verdict"] == "pass"
    assert by["route.knn.k5"]["target_p95_ms"] == 100.0
    assert by["retrieval_result_cache.ttl_1d"]["p95_ms"] is None
    assert by["retrieval_result_cache.ttl_1d"]["verdict"] == "not measured"
    assert payload["target"]["source"] == "Q-14"
    assert "report-period" in payload["sample_note"]


def test_plan_groups_baselines_and_dry_run_writes_nothing(mo, tmp_path, capsys):
    for b in BASELINES:
        lever_file(tmp_path, f"rb3.knn-router.k-5.tune.{b}", "route.knn.k5", "routing")
        lever_file(
            tmp_path,
            f"rb2.cross-turn.k-0.ptr-8.pointer.{b}",
            "cross_turn_chunks.ptr8.k0",
            "context",
        )
    todo = mo.plan([], tmp_path)
    assert list(todo) == ["cross_turn_chunks.ptr8.k0", "route.knn.k5"]
    assert all(len(paths) == 4 for _, paths in todo.values())
    only = mo.plan(["rb3.knn-router.k-5.tune.as_logged"], tmp_path)
    assert list(only) == ["route.knn.k5"] and len(only["route.knn.k5"][1]) == 4

    before = {p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()}
    assert mo.main(["--folder", str(tmp_path), "--dry-run"]) == 0
    after = {p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()}
    assert after == before
    assert "dry run" in capsys.readouterr().out


def test_built_version_matches_its_label(mo):
    class R:  # [SYNTHETIC] router stand-in
        def __init__(self, k, candidates):
            self.k, self.candidates, self.name = k, tuple(candidates), f"route.knn.k{k}"

    st = {"candidates": ["a"], "candidates_with_reasoning": ["a", "b"]}
    wide = mo.spec_for("rb3.knn-router.with_reasoning_models.k-5.tune.as_logged")
    assert mo.built_as_planned(wide, R(5, ["a", "b"]), st)
    assert not mo.built_as_planned(wide, R(5, ["a"]), st)
    assert not mo.built_as_planned(wide, R(15, ["a", "b"]), st)
