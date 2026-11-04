"""Offline logic of ``scripts/measure_lever_overhead.py`` (final plan L-1).

Every frame and file here is [SYNTHETIC]. Versions are small in-test classes and
the clock is injected, so the timings are exact and no real data is read. The
script is loaded with ``importlib`` (scripts are not a package), as in
``test_run_popular_question.py``.
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

from metis_auto.analysis.lever_result import LeverResult, build_manifest
from metis_auto.analysis.levers import ReplayContext

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def mo():
    name = "measure_lever_overhead_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "measure_lever_overhead.py"
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
        price_table={"version": "prices-synthetic"},
        catalogue={},
        seed=7,
    )


def frame(n_report: int = 30, n_tune: int = 10, n_workflow: int = 5) -> pd.DataFrame:
    """[SYNTHETIC] requests: report LLM rows, tune LLM rows, report workflow rows."""
    rows = (
        [("report", True)] * n_report
        + [("tune", True)] * n_tune
        + [("report", False)] * n_workflow
    )
    return pd.DataFrame(
        {
            "period": [p for p, _ in rows],
            "llm_request": [llm for _, llm in rows],
            "block_fees": 0.002,
            "block_token_cost": 0.01,
        },
        index=pd.RangeIndex(100, 100 + len(rows)),
    )


class NoOp:
    """[SYNTHETIC] a version that changes nothing."""

    name = "cache.synthetic_noop"
    step = "cache"

    def __init__(self) -> None:
        self.calls: list[int] = []

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        self.calls.append(len(req))
        out = req.copy()
        out["served_from_cache"] = False
        return out


class Raises(NoOp):
    def apply(self, req, ctx):
        raise RuntimeError("synthetic failure")


class DropsIndex(NoOp):
    def apply(self, req, ctx):
        return req.reset_index(drop=True)


class Clock:
    """[SYNTHETIC] each call moves time by ``step_ns`` nanoseconds."""

    def __init__(self, step_ns: int) -> None:
        self.now, self.step = 0, step_ns

    def __call__(self) -> int:
        self.now += self.step
        return self.now


def result(lever_id: str = "cache.synthetic_noop", baseline="as_logged", **over):
    manifest = build_manifest(
        {"synthetic": True},
        ctx(),
        code_commit="abc1234",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    data = {
        "lever_id": lever_id,
        "step": "cache",
        "version": "syn-v1",
        "n_requests": 100,
        "n_eligible": 40,
        "baseline": baseline,
        "baseline_cost": {"total": Decimal("1.500000000")},
        "saving": {"total": Decimal("0.250000000")},
        "ci_low": 0.1,
        "ci_high": 0.2,
        "slices": {
            "all": {"n_requests": Decimal(100)},
            "llm_only": {"n_requests": Decimal(70)},
        },
        "evidence_class": "simulation",
        "correctness_state": "sampled:30",
        "assumptions": ("[SYNTHETIC] an earlier assumption.",),
        "manifest": manifest,
    } | over
    return LeverResult(**data)


# --- sampling


def test_sample_is_seeded_reproducible_and_report_period_llm_only(mo):
    req = frame()
    a = mo.sample_rows(req, 12, seed=3)
    b = mo.sample_rows(req, 12, seed=3)
    c = mo.sample_rows(req, 12, seed=4)
    assert list(a.index) == list(b.index)
    assert list(a.index) != list(c.index)
    assert len(a) == 12
    assert a["period"].eq("report").all() and a["llm_request"].all()


def test_sample_takes_every_row_when_fewer_than_asked(mo):
    assert len(mo.sample_rows(frame(n_report=5), 1000, seed=3)) == 5


# --- timing


def test_times_are_per_request_one_row_per_apply(mo):
    version = NoOp()
    rows = frame(n_report=6).iloc[:6]
    times = mo.time_apply(version, rows, ctx(), clock=Clock(2_000_000))
    assert times == [2.0] * 6  # 2 ms per call, one row per call
    assert version.calls == [1] * 7  # one warm-up call, then one per row


def test_times_are_total_divided_by_rows_for_larger_batches(mo):
    version = NoOp()
    rows = frame(n_report=6).iloc[:6]
    times = mo.time_apply(version, rows, ctx(), batch_size=3, clock=Clock(6_000_000))
    assert times == [2.0, 2.0]  # 6 ms per 3-row batch = 2 ms per request
    assert version.calls == [3, 3, 3]


def test_a_version_that_raises_fails_the_run(mo):
    with pytest.raises(RuntimeError, match="synthetic failure"):
        mo.time_apply(Raises(), frame().iloc[:3], ctx())


def test_a_version_that_changes_the_index_fails_the_run(mo):
    with pytest.raises(ValueError, match="index"):
        mo.time_apply(DropsIndex(), frame().iloc[:3], ctx())


def test_no_rows_is_an_error_not_a_zero(mo):
    with pytest.raises(ValueError, match="no rows"):
        mo.time_apply(NoOp(), frame().iloc[:0], ctx())


def test_summary_has_p50_p95_max_and_n(mo):
    s = mo.summarise([float(v) for v in range(1, 101)])
    assert s == {"n": 100, "p50_ms": 50.5, "p95_ms": 95.0, "max_ms": 100.0}


# --- writing into LeverResult


def test_overhead_fields_filled_and_labelled_offline_estimate(mo):
    before = result()
    after = mo.with_overhead(before, p50=0.5, p95=1.25, note="[SYNTHETIC] note")
    assert after.overhead_ms_p50 == 0.5
    assert after.overhead_ms_p95 == 1.25
    labels = [a for a in after.assumptions if a.startswith(mo.OVERHEAD_LABEL)]
    assert len(labels) == 1
    assert "offline per-request estimate on a local machine" in labels[0]
    assert "not a load test (Q-14)" in labels[0]


def test_every_other_field_stays_unchanged(mo):
    before = result()
    after = mo.with_overhead(before, p50=0.5, p95=1.25, note="[SYNTHETIC] note")
    a, b = json.loads(before.to_json()), json.loads(after.to_json())
    for key in ("overhead_ms_p50", "overhead_ms_p95", "assumptions"):
        a.pop(key), b.pop(key)
    assert a == b  # savings, slices, CI, manifest and the rest are untouched
    assert after.assumptions[: len(before.assumptions)] == before.assumptions


def test_rerun_replaces_the_overhead_label_instead_of_adding_one(mo):
    once = mo.with_overhead(result(), p50=0.5, p95=1.0, note="[SYNTHETIC] first")
    twice = mo.with_overhead(once, p50=0.7, p95=2.0, note="[SYNTHETIC] second")
    labels = [a for a in twice.assumptions if a.startswith(mo.OVERHEAD_LABEL)]
    assert len(labels) == 1 and "second" in labels[0]
    assert twice.overhead_ms_p95 == 2.0


def test_result_files_are_matched_by_lever_id_not_file_name(mo, tmp_path):
    for lever_id, base, name in (
        ("cache.synthetic_noop", "as_logged", "cache.synthetic_noop.json"),
        ("cache.synthetic_noop", "premium", "cache.synthetic_noop__premium.json"),
        (
            "cache.synthetic_noop.ttl24h",
            "as_logged",
            "cache.synthetic_noop.ttl24h.json",
        ),
    ):
        (tmp_path / name).write_text(result(lever_id, base).to_json(), "utf-8")
    found = mo.result_files("cache.synthetic_noop", tmp_path)
    assert [p.name for p in found] == [
        "cache.synthetic_noop.json",
        "cache.synthetic_noop__premium.json",
    ]


def test_measure_writes_every_baseline_file_and_keeps_savings(mo, tmp_path):
    for base in ("as_logged", "premium"):
        suffix = "" if base == "as_logged" else f"__{base}"
        path = tmp_path / f"cache.synthetic_noop{suffix}.json"
        path.write_text(result(baseline=base).to_json(), "utf-8")
    summary = mo.measure(
        "cache.synthetic_noop",
        NoOp(),
        frame(),
        ctx(),
        folder=tmp_path,
        n=10,
        seed=1,
        note=lambda s: f"[SYNTHETIC] n={s['n']}",
        clock=Clock(1_000_000),
    )
    assert summary["n"] == 10 and summary["p95_ms"] == 1.0
    for path in sorted(tmp_path.glob("*.json")):
        r = LeverResult.from_json(path.read_text("utf-8"))
        assert r.overhead_ms_p50 == 1.0 and r.overhead_ms_p95 == 1.0
        assert r.saving == {"total": Decimal("0.250000000")}


def test_measure_writes_nothing_when_the_version_raises(mo, tmp_path):
    path = tmp_path / "cache.synthetic_noop.json"
    text = result().to_json()
    path.write_text(text, "utf-8")
    with pytest.raises(RuntimeError):
        mo.measure(
            "cache.synthetic_noop",
            Raises(),
            frame(),
            ctx(),
            folder=tmp_path,
            n=5,
            seed=1,
            note=lambda s: "[SYNTHETIC]",
        )
    assert path.read_text("utf-8") == text


def test_measure_refuses_a_lever_without_result_files(mo, tmp_path):
    with pytest.raises(FileNotFoundError):
        mo.measure(
            "cache.synthetic_missing",
            NoOp(),
            frame(),
            ctx(),
            folder=tmp_path,
            n=5,
            seed=1,
            note=lambda s: "[SYNTHETIC]",
        )


def test_target_check_against_100_ms(mo):
    assert mo.TARGET_P95_MS == 100.0
    assert mo.verdict(99.9) == "pass" and mo.verdict(100.0) == "pass"
    assert mo.verdict(100.1) == "fail"


# --- version families


@pytest.mark.parametrize(
    ("lever_id", "group", "value"),
    [
        ("cache.popular_question.first_turn", "variant", "first_turn"),
        ("cache.popular_question.all_turns.ttl24h", "ttl", "24"),
        ("context.reranker_cut.observed_relevancy", "scorer", "observed_relevancy"),
        ("context.reranker_cut.lexical_overlap", "scorer", "lexical_overlap"),
        ("route.per_bot", "set", None),
        ("route.per_bot.with_reasoning_models", "set", ".with_reasoning_models"),
        ("ctx.within_message_dedup", None, None),
        ("ctx.history_budget.b2000", "variant", "b2000"),
        ("ctx.history_budget.half_over_8k", "variant", "half_over_8k"),
        ("cache.session_memo_gate", None, None),
        ("route.decision_router.rules_only", None, None),
        ("route.small_classifier.rules", "mode", "rules"),
        (
            "route.small_classifier.rules.with_reasoning_models",
            "set",
            ".with_reasoning_models",
        ),
        (
            "route.small_classifier.strict_unknown_blocked",
            "mode",
            "strict_unknown_blocked",
        ),
    ],
)
def test_known_lever_ids_find_their_version(mo, lever_id, group, value):
    _, m = mo.target_for(lever_id)
    if group is not None:
        assert m[group] == value


def test_per_baseline_lever_ids_are_found_by_their_version_id(mo, tmp_path):
    """Pipeline C writes the baseline into ``lever_id`` (``<id>.<baseline>``);
    those files are one version's results, found by the version id."""
    for base in ("as_logged", "todays_models"):
        rid = f"ctx.synthetic_c.{base}"
        (tmp_path / f"{rid}.json").write_text(result(rid, base).to_json(), "utf-8")
    other = "ctx.synthetic_c.longer.as_logged"
    (tmp_path / f"{other}.json").write_text(result(other).to_json(), "utf-8")
    assert mo.result_files("ctx.synthetic_c", tmp_path) == []
    found = mo.result_files("ctx.synthetic_c", tmp_path, per_baseline=True)
    assert [p.name for p in found] == [
        "ctx.synthetic_c.as_logged.json",
        "ctx.synthetic_c.todays_models.json",
    ]


def test_c_targets_match_results_per_baseline(mo):
    for lever_id in (
        "ctx.within_message_dedup",
        "ctx.history_budget.b4000",
        "cache.session_memo_gate",
        "route.small_classifier.strict",
        "route.decision_router.rules_only",
    ):
        target, _ = mo.target_for(lever_id)
        assert target.per_baseline, lever_id
    target, _ = mo.target_for("route.per_bot")
    assert not target.per_baseline


def test_unknown_lever_id_stops_the_run(mo):
    with pytest.raises(SystemExit):
        mo.target_for("context.synthetic_unknown")


def test_headline_point_is_read_from_the_report_rows_of_the_curve(mo):
    curve = pd.DataFrame(
        {
            "scorer": ["observed_relevancy"] * 3 + ["lexical_overlap"] * 2,
            "period": ["tune", "report", "report", "report", "report"],
            "top_k": [12, 12, 3, None, 5],
            "threshold_rule": ["q25", "q25", "none", "q50", "none"],
            "threshold": [0.23, 0.23, None, 0.2, None],
            "floor": 3,
            "headline": [True, True, False, True, False],
        }
    )
    assert mo.headline_point(curve, "observed_relevancy") == (3, 0.23, 12)
    assert mo.headline_point(curve, "lexical_overlap") == (3, 0.2, None)
    with pytest.raises(SystemExit):
        mo.headline_point(curve, "synthetic_missing")
