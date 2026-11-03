"""Gap 1 (sprint close): the benchmark's computed estimate is refused while any
owner value is unset, the committed config keeps them unset, and the gate text
names ADR-0018 Amendment 3 (traces: QA-COST, FR-EVAL-04, ADR-0053).
SYNTHETIC numbers only; no network, no key."""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.evaluation.benchmark.config import parse_config
from metis_auto.evaluation.benchmark.plan import (
    estimate_gaps,
    gates,
    total_estimate,
)

ROOT = Path(__file__).resolve().parents[3]
EXPECTED_GAPS = [
    "run.hard_cap_usd",
    "run.max_output_tokens",
    "run.order_seed",
    "judges.models",
    "judges.max_output_tokens",
    "judges.instruction_language",
    "labels.acceptable_score",
    "labels.cheap_arms",
    "spend_share.expected_machines",
    "spend_share.max_age_hours",
]


def committed():
    raw = tomllib.loads(
        (ROOT / "config/evaluation/benchmark.toml").read_text(encoding="utf-8")
    )
    return parse_config(raw), raw


def test_committed_config_leaves_every_owner_value_unset():
    config, _ = committed()
    assert estimate_gaps(config) == EXPECTED_GAPS


def test_gaps_empty_once_every_value_is_set():
    _, raw = committed()
    raw["run"] = {"hard_cap_usd": "5", "max_output_tokens": 1000, "order_seed": "s"}
    raw["judges"] = {
        "models": ["j-a", "j-b"],
        "max_output_tokens": 300,
        "instruction_language": "en",
    }
    raw["labels"] = {"acceptable_score": 0.5, "cheap_arms": ["a"]}
    raw["spend_share"] = {
        **raw["spend_share"],
        "expected_machines": ["m1"],
        "max_age_hours": 24,
    }
    assert estimate_gaps(parse_config(raw)) == []


def test_total_estimate_sums_both_steps_and_checks_the_cap():
    out = total_estimate(
        {"lower_bound_usd": "1.5", "ceiling_usd": "4"},
        {"lower_bound_usd": "0.5", "ceiling_usd": "2"},
        hard_cap=Decimal("5"),
    )
    assert out["lower_bound_usd"] == "2" and out["ceiling_usd"] == "6"
    assert out["ceiling_fits_hard_cap"] is False
    assert out["lower_bound_fits_hard_cap"] is True


def test_total_estimate_keeps_unknown_unknown():
    out = total_estimate(
        {"lower_bound_usd": "1", "ceiling_usd": None},
        {"lower_bound_usd": "1", "ceiling_usd": "1"},
        hard_cap=Decimal("5"),
    )
    assert out["ceiling_usd"] is None and out["ceiling_fits_hard_cap"] is None


def test_gate_names_amendment_three_not_two():
    first = gates(amendment_committed=True, samples_allowed=False)[0]
    assert "amendment 3" in first.name and "amendment 2" not in first.name
    assert "92" in first.note


def _script(name: str):
    mod_name = f"{name}_under_test"
    spec = importlib.util.spec_from_file_location(mod_name, ROOT / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def test_benchmark_plan_estimate_refuses_while_values_unset(monkeypatch, capsys):
    bench = _script("benchmark.py")
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "plan", "--estimate"])
    assert bench.main() == 1
    refused = json.loads(capsys.readouterr().out)["refused"]
    assert "set by owner: run.max_output_tokens" in refused
    assert "set by owner: judges.models" in refused
    assert any("--with-db" in r for r in refused)


def test_sampling_plan_strict_refuses_while_allocation_unset(monkeypatch, capsys):
    sp = _script("sampling_plan.py")
    monkeypatch.setattr(sys, "argv", ["sampling_plan.py", "--strict"])
    assert sp.main() == 1
    refused = json.loads(capsys.readouterr().out)["refused"]
    assert "set by owner: allocation.total" in refused
    assert "set by owner: allocation.seed" in refused
    assert "set by owner: run.max_output_tokens" in refused


def test_sampling_readiness_lists_nothing_when_set():
    from metis_auto.evaluation.sampling.config import (
        parse_allocation_config,
        parse_run_config,
    )
    from metis_auto.evaluation.sampling.readiness import call_estimate, unset_values

    alloc = parse_allocation_config(
        {"dimensions": ["language"], "total": 10, "seed": "s"}
    )
    run = parse_run_config(
        {
            "models": ["m1", "m2"],
            "hard_cap_usd": "3",
            "max_output_tokens": 500,
            "order_seed": "o",
        }
    )
    assert unset_values(alloc, run) == []
    est = call_estimate(achieved_total=10, run=run)
    assert est == {"calls": 20, "max_output_tokens_total": 10_000}
    with pytest.raises(ValueError):
        call_estimate(achieved_total=10, run=parse_run_config({}))


def test_scope_selects_pilot_or_main_records(monkeypatch):
    import pandas as pd

    from metis_auto.wiring.benchmark import Benchmark, BenchmarkRefused

    frame = pd.DataFrame(
        {
            "record_id": [f"r{i:03d}" for i in range(40)][::-1],
            "tenant": [f"t{i % 8}" for i in range(40)],
            "language_group": ["fa", "en"] * 20,
            "user_message_id": [f"m{i}" for i in range(40)],
        }
    )
    bench = Benchmark()
    monkeypatch.setattr(Benchmark, "shareable", lambda self: frame)
    main = bench.record_ids("main")
    assert len(main) == 40 and list(main) == sorted(main)
    pilot = bench.record_ids("pilot")
    assert len(pilot) == bench.config.pilot.size and set(pilot) <= set(main)
    with pytest.raises(BenchmarkRefused):
        bench.record_ids("everything")
