"""R-B3 wiring in ``scripts/run_pipeline_b_day3.py``: the switch-over to the
shared routing base (ADR-0045). SYNTHETIC only; no data file is read.

Traces: plan R-0 / R-B3, FR-ROUTE-05, ADR-0045, ADR-0048.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest
from test_knn_router import CATALOGUE, ctx, frame

from metis_auto.analysis import routing_base

ROOT = Path(__file__).resolve().parents[3]

# [SYNTHETIC] routing rules in the sprint.toml [routing] shape.
ROUTING = {
    "candidates": ["cheap", "mid"],
    "candidates_jev": [],
    "avoid_long_context_tier": True,
    "retiring": [{"model_id": "dear", "replacement": "mid"}],
}


@pytest.fixture(scope="module")
def d3():
    name = "run_pipeline_b_day3_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "run_pipeline_b_day3.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _st(d3):
    return {
        "ctx": ctx(),
        "routing": ROUTING,
        "candidates": list(routing_base.candidate_list(ROUTING)),
    }


def test_rb3_factory_uses_the_shared_routing_base(d3):
    router = d3._factory(_st(d3), frozenset())(frame(4), 3)
    assert router.eligible_models is routing_base.eligible_models
    assert router.rules is ROUTING
    assert router.candidates == routing_base.candidate_list(ROUTING)


def test_rb3_settings_carry_the_routing_table(d3):
    st = d3.settings(ROOT / "config" / "evaluation" / "sprint.toml")
    assert "avoid_long_context_tier" in st["routing"]
    assert tuple(st["candidates"]) == routing_base.candidate_list(st["routing"])


def test_no_assumption_carries_the_interim_label(d3, load_experiment):
    version = load_experiment("routing/exp-route-011-knn-router/version.py")
    texts = [*d3.rb3_assumptions(5, "declared default"), *version.ASSUMPTIONS]
    assert texts
    assert not [t for t in texts if "interim" in t.lower()]
    assert any("Q-B21" in t for t in texts)


def test_rb3_routes_on_shared_eligibility(d3):
    """A request with attachments keeps its incumbent (routing base rule)."""
    st = _st(d3)
    cat = {
        "models": [
            {
                **m,
                "context_window": {"value": 10**6},
                "max_output_tokens": {"value": 10**5},
            }
            for m in CATALOGUE["models"]
        ]
    }
    c = dataclasses.replace(ctx(), catalogue=cat)
    train = frame(6, bot_provider_model=["cheap"] * 6)
    query = frame(
        2,
        session_id=["x0", "x1"],
        u_h_norm=["y0", "y1"],
        u_att_n=[0.0, 1.0],
    )
    out = d3._factory({**st, "ctx": c}, frozenset())(train, 3).apply(query, c)
    assert out["route_reason"].tolist() == ["moved", "no_eligible_candidate"]
