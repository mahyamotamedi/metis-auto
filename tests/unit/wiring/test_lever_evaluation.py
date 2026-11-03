"""The framework's lever evaluation command: it reads lever result files, skips
what is not a result (and its own output), and writes a content-free JSON and
Markdown report. SYNTHETIC result files in a temporary folder; no network."""

from __future__ import annotations

import json

from metis_auto.wiring import lever_evaluation as le


def _result(step, version, baseline="as_logged"):
    return {
        "lever_id": f"{version}.{baseline}",
        "step": step,
        "version": version,
        "n_requests": 1000,
        "n_eligible": 500,
        "baseline": baseline,
        "baseline_cost": {"total": "100"},
        "saving": {"total": "2"},
        "ci_low": 0.01,
        "ci_high": 0.03,
        "slices": {"all": {"saving_share": 0.02}, "llm_only": {"saving_share": 0.02}},
        "evidence_class": "simulation",
        "correctness_state": "unmeasured",
        "assumptions": [],
        "overhead_ms_p50": 1.0,
        "overhead_ms_p95": 2.0,
        "manifest": {"price_version": "prices-syn", "data_revision": "rev-syn"},
    }


def _write(folder, name, data):
    path = folder / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_results_are_read_and_everything_else_is_skipped(tmp_path):
    a = _write(tmp_path, "a.json", _result("context", "context.syn"))
    b = _write(tmp_path, "b.json", _result("routing", "route.syn"))
    summary = _write(tmp_path, "final.json", {"not": "a lever result"})
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    text = tmp_path / "notes.md"
    text.write_text("x", encoding="utf-8")
    own = _write(tmp_path, "lever_evaluation.json", {"format": "lever-evaluation-v1"})
    out = tmp_path / "out"
    summary_counts = le.write_evaluation(
        [a, b, summary, broken, text, own], out_dir=out
    )
    assert summary_counts["results"] == 2 and summary_counts["skipped"] == 4
    assert summary_counts["pickable"] == {"cache": [], "context": [], "routing": []}
    report = json.loads((out / "lever_evaluation.json").read_text("utf-8"))
    assert report["format"] == "lever-evaluation-v1" and report["n_results"] == 2
    md = (out / "lever_evaluation.md").read_text("utf-8")
    assert "context.syn" in md and "route.syn" in md and "cannot_pass" in md


def test_the_minimum_reviews_option_reaches_the_cache_rule(tmp_path):
    res = _result("cache", "cache.popular_question.syn")
    res["correctness_state"] = "sampled:30"
    path = _write(tmp_path, "c.json", res)
    default = le.write_evaluation([path], out_dir=tmp_path / "o1")
    assert default["results"] == 1
    low = le.write_evaluation([path], out_dir=tmp_path / "o2", min_reviewed=20)
    report = json.loads((tmp_path / "o2" / "lever_evaluation.json").read_text("utf-8"))
    (row,) = report["steps"]["cache"]["results"]
    assert (
        row["rule"]["reason"] == "answer_error_rate_not_in_result"
        and low["results"] == 1
    )
