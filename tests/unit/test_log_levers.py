"""scripts/log_levers.py: only lever results are logged; the rest are skipped.

Imports no MLflow (a fake tracker). Fixtures are SYNTHETIC."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "log_levers.py"
spec = importlib.util.spec_from_file_location("log_levers", SCRIPT)
log_levers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(log_levers)


def lever(lever_id):
    return {
        "lever_id": lever_id,
        "manifest": {"config_hash": "a" * 64},
        "saving": {"total": "1"},
        "baseline_cost": {"total": "2"},
    }


def test_lever_results_are_found_and_other_json_is_skipped(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(lever("l.a")))
    (tmp_path / "pipeline_b_overhead.json").write_text(json.dumps({"method": "x"}))
    (tmp_path / "final.json").write_text(json.dumps({"cost_blocks": []}))
    (tmp_path / "list.json").write_text("[]")
    found, skipped = log_levers.lever_results(tmp_path)
    assert [r["lever_id"] for r in found] == ["l.a"]
    assert skipped == ["final.json", "list.json", "pipeline_b_overhead.json"]


def test_every_found_result_is_logged_once():
    class Fake:
        def __init__(self):
            self.seen = []

        def log_result(self, result):
            self.seen.append(result["lever_id"])
            return f"run-{len(self.seen)}"

    tracker = Fake()
    out = log_levers.log_all(tracker, [lever("l.a"), lever("l.b")])
    assert out == [("l.a", "run-1"), ("l.b", "run-2")]
