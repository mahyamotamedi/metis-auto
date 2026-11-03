"""Report-split helpers of ``scripts/run_pipeline_b_day2.py`` (R-B1, R-B2; owner
decision 2026-11-03: one report-split run each, settings frozen on tune first).
Every frame and file here is SYNTHETIC; no data file is read.

Traces: plan R-B1, R-B2, ADR-0036, ADR-0037.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def d2():
    name = "run_pipeline_b_day2_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "run_pipeline_b_day2.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_report_scope_scores_the_report_split_with_tune_history(d2):
    req = pd.DataFrame(  # [SYNTHETIC]
        {
            "period": ["tune", "tune", "report", "report", "unknown", "unknown"],
            "split": ["tune", "excluded", "report", "excluded", "report", "tune"],
        }
    )
    history, scored = d2.report_scope(req)
    assert scored.tolist() == [False, False, True, False, True, False]
    # Every tune/report-period row is cache history; a scored row always is.
    assert history.tolist() == [True, True, True, True, True, False]


def test_frozen_settings_are_written_on_tune_and_required_for_report(d2, tmp_path):
    rb1 = d2.frozen_rb1(chosen_ttl_days=7)
    assert rb1["ttl_days"] == 1 and rb1["grid_ttl_days"] == list(d2.TTL_DAYS)
    assert rb1["ttl_rule_choice_days"] == 7  # reported, never the frozen value
    rb2 = d2.frozen_rb2()
    assert rb2["default"] == {"visible_window": 0, "pointer_tokens": 8, "ledger": False}
    assert rb2["stated_scenario"]["visible_window"] == 1
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"lever": "synthetic"}), encoding="utf-8")
    with pytest.raises(SystemExit, match="no frozen settings"):
        d2.read_frozen(summary)
    summary.write_text(json.dumps({"frozen": rb1}), encoding="utf-8")
    assert d2.read_frozen(summary) == rb1


def test_report_scenarios_are_the_frozen_ones(d2):
    frozen = d2.frozen_rb2()
    assert d2.report_scenarios(frozen) == [(0, 8, False), (1, 8, False)]
