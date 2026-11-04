"""``scripts/run_sprint_final.py`` and ``experiments/pipelines/sprint-final.toml``
(plan I-1). Frames are [SYNTHETIC]; no data is read."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "experiments/pipelines/sprint-final.toml"
NAN = np.nan


@pytest.fixture(scope="module")
def rs():
    name = "run_sprint_final_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts/run_sprint_final.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def config():
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def test_every_configured_version_has_a_builder(rs, config):
    named = {
        v
        for name in rs.ALL_PIPELINES
        for step, v in config[name].items()
        if step in ("cache", "context", "routing")
    }
    assert named <= set(rs.BUILDERS)


def test_the_five_pipelines_are_named_with_one_version_per_step(rs, config):
    assert set(rs.ALL_PIPELINES) == {
        "winners",
        "parham",
        "pipeline_a",
        "pipeline_b",
        "pipeline_c",
    }
    for name in ("pipeline_a", "pipeline_b", "pipeline_c", "winners"):
        assert {"cache", "context", "routing"} <= set(config[name]), name
    assert set(config["parham"]) - {"routing"} == set()  # routing only


def test_winners_are_labelled_provisional_and_the_population_is_the_report_split(
    config,
):
    assert config["status"] == "provisional: cost only, pending quality"
    assert "quality is not measured" in config["note"].lower()
    assert config["population"]["split"] == "report"
    assert config["population"]["expected_requests"] == 73063


def test_runners_up_and_skips_are_named(config):
    assert set(config["runners_up"]) == {"cache", "context", "routing"}
    assert "context.reranker_cut.lexical_overlap" in config["not_run"]


def frames():
    before = pd.DataFrame(
        {
            "llm_request": [True, True, True, False],
            "block_fees": [0.1, 0.2, 0.3, NAN],
            "block_token_cost": [1.0, 2.0, 3.0, NAN],
        }
    )
    after = before.copy()
    after["block_token_cost"] = [0.5, NAN, 2.0, NAN]  # row 1: unknown after
    return before, after


def test_unknown_rows_leave_both_sides_of_a_saving(rs):
    before, after = frames()
    rows = pd.Series(True, index=before.index)
    # row 1 is unknown on one side: out of the sum; row 3 is a workflow row
    assert rs.frames_saving(before, after, rows) == Decimal("1.500000000")


def test_only_scored_rows_count(rs):
    before, after = frames()
    rows = pd.Series([True, False, False, False], index=before.index)
    assert rs.frames_saving(before, after, rows) == Decimal("0.500000000")


def test_the_run_refuses_unless_the_router_is_off(rs):
    from metis_auto.settings import load_settings

    off = load_settings(environ={}, dotenv=None, runtime=None).settings
    rs.script("decision_router_levers").rules_only.require_offline(off)
    bad = off.model_copy(update={"live": off.live.model_copy(update={"enabled": True})})
    with pytest.raises(SystemExit):
        rs.script("decision_router_levers").rules_only.require_offline(bad)
