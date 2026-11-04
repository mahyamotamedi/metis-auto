"""MLflow run tracker (sprint T-2): one run per lever result, idempotent by
``lever_id`` + ``config_hash``, and nothing but the manifest's pins reaches MLflow.

Uses a temporary local file store; skipped when the ``services`` extra is not
installed. Fixtures are SYNTHETIC."""

import copy
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("mlflow")

from metis_auto.adapters.tracking.mlflow_tracker import MlflowRunTracker  # noqa: E402
from metis_auto.ports.tracking import RunTracker  # noqa: E402

CONFIG_HASH = "ab" * 32
DATA_REVISION = "cd" * 20
HEX = re.compile(r"\b[0-9a-f]{16,}\b")


def synthetic(lever_id="cache.synthetic.as_logged", config_hash=CONFIG_HASH):
    return {
        "lever_id": lever_id,
        "step": "caching",
        "version": "cache.synthetic",
        "baseline": "as_logged",
        "evidence_class": "simulation",
        "correctness_state": "unmeasured",
        "baseline_cost": {"fees": "1.5", "token_cost": "8.5", "total": "10.0"},
        "saving": {"fees": "0.0", "token_cost": "2.5", "total": "2.5"},
        "ci_low": 0.2,
        "ci_high": 0.3,
        "n_eligible": 90,
        "n_requests": 100,
        "overhead_ms_p50": None,
        "overhead_ms_p95": 4.0,
        "assumptions": ["SYNTHETIC test fixture"],
        "slices": {
            "all": {"saving:total": "2.5", "saving_share": 0.25},
            "lang:fa": {"saving:total": "1.0"},
            "bot_rank:1": {"saving:total": "0.5"},
        },
        "manifest": {
            "code_commit": "unknown",
            "config_hash": config_hash,
            "created_at": "2026-11-03T14:54:17Z",
            "data_revision": DATA_REVISION,
            "price_version": "synthetic-prices",
            "python_version": "3.13.5",
            "seed": 7,
        },
    }


@pytest.fixture
def tracker(tmp_path):
    return MlflowRunTracker(f"file://{tmp_path / 'mlruns'}", "test-levers")


def runs(tracker):
    from mlflow.tracking import MlflowClient

    client = MlflowClient(tracker.tracking_uri)
    exp = client.get_experiment_by_name(tracker.experiment)
    return client, client.search_runs([exp.experiment_id]) if exp else []


def test_it_satisfies_the_port(tracker):
    assert isinstance(tracker, RunTracker)


def test_a_result_becomes_one_run_with_manifest_params_and_saving_metrics(tracker):
    run_id = tracker.log_result(synthetic())
    _, found = runs(tracker)
    assert [r.info.run_id for r in found] == [run_id]
    run = found[0]
    assert run.data.params["config_hash"] == CONFIG_HASH
    assert run.data.params["data_revision"] == DATA_REVISION
    assert run.data.params["code_commit"] == "unknown"
    assert run.data.params["seed"] == "7"
    assert run.data.params["price_version"] == "synthetic-prices"
    assert run.data.metrics["saving_total"] == 2.5
    assert run.data.metrics["baseline_total"] == 10.0
    assert run.data.metrics["ci_low"] == 0.2
    assert run.data.metrics["overhead_ms_p95"] == 4.0
    assert "overhead_ms_p50" not in run.data.metrics  # None is not logged as 0
    assert run.data.tags["lever_id"] == "cache.synthetic.as_logged"
    assert run.data.tags["correctness_state"] == "unmeasured"
    assert run.data.tags["slice_kinds"] == "all,bot_rank,lang"


def test_logging_the_same_result_twice_makes_one_run(tracker):
    first = tracker.log_result(synthetic())
    second = tracker.log_result(copy.deepcopy(synthetic()))
    assert first == second
    assert len(runs(tracker)[1]) == 1


def test_another_lever_or_config_hash_is_another_run(tracker):
    a = tracker.log_result(synthetic())
    b = tracker.log_result(synthetic(lever_id="cache.synthetic.todays_models"))
    c = tracker.log_result(synthetic(config_hash="ef" * 32))
    assert len({a, b, c}) == 3
    assert len(runs(tracker)[1]) == 3


def test_no_text_id_or_hash_reaches_mlflow_except_the_manifest_pins(tracker):
    planted = synthetic()
    planted["text_sample"] = "PLANTED-MESSAGE-TEXT"
    planted["user_id"] = "u-4711"
    planted["note_hash"] = "ee" * 32
    tracker.log_result(planted)
    client, found = runs(tracker)
    run = found[0]
    logged = json.dumps(
        [run.data.params, run.data.metrics, run.data.tags], sort_keys=True
    )
    root = Path(tracker.tracking_uri.removeprefix("file://"))
    for path in root.rglob("*"):  # the artifact and every file the store wrote
        if path.is_file():
            logged += path.read_text(encoding="utf-8", errors="ignore")
    for planted_value in ("PLANTED-MESSAGE-TEXT", "u-4711", "ee" * 32):
        assert planted_value not in logged
    allowed = {CONFIG_HASH, DATA_REVISION, run.info.run_id, run.info.experiment_id}
    stray = [h for h in HEX.findall(logged) if h not in allowed]
    assert stray == []
