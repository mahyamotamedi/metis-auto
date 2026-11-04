"""Cut-first (d): input builders and the no-call estimate of the cache-hit
judging and the context ablation (SYNTHETIC IDs, catalogue and prices; traces
H-1, H-3, FR-EVAL-06, ADR-0053)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from metis_auto.evaluation.benchmark.config import parse_config
from metis_auto.evaluation.benchmark.quality_checks import (
    LOGGED,
    STORED,
    MappingContent,
    QualityCheckRefused,
    ablation_plan,
    build_ablation_items,
    build_hit_items,
    count_preview,
    hit_judging_plan,
    readiness_reasons,
    refuse_unless_ready,
)
from metis_auto.evaluation.judging.types import JudgeRequestView
from tests.unit.evaluation.test_benchmark_p1 import CATALOGUE, ENTRIES, PRICES

ROOT = Path(__file__).resolve().parents[3]


def committed():
    raw = tomllib.loads(
        (ROOT / "config/evaluation/benchmark.toml").read_text(encoding="utf-8")
    )
    return raw, parse_config(raw)


def ready_config(allowed=True):
    raw, _ = committed()
    raw["gates"] = {"metis_allows_samples": allowed, "metis_answer_ref": "syn-ref"}
    raw["run"] = {"hard_cap_usd": "5", "max_output_tokens": 1000, "order_seed": "s"}
    raw["judges"] = {
        "models": ["syn-a", "syn-b"],
        "max_output_tokens": 100,
        "instruction_language": "en",
    }
    raw["labels"] = {"acceptable_score": 0.5, "cheap_arms": ["syn-a"]}
    raw["spend_share"] = {
        **raw["spend_share"],
        "expected_machines": ["m1"],
        "max_age_hours": 24,
    }
    return parse_config(raw)


def test_a_config_missing_a_value_and_the_gate_refuses_with_every_reason(tmp_path):
    from tests.unit.evaluation.test_benchmark_estimate import config_without

    path = config_without(tmp_path, "judges.models", samples_gate=False)
    config = parse_config(tomllib.loads(path.read_text(encoding="utf-8")))
    reasons = readiness_reasons(config)
    assert "set by owner: judges.models" in reasons
    assert any(r.startswith("gate missing") and "O-1" in r for r in reasons)
    with pytest.raises(QualityCheckRefused) as err:
        refuse_unless_ready(config, preview=count_preview(kind="cache_hit", n=300))
    assert any("'judge_calls': 1200" in r for r in err.value.reasons)


def test_gate_still_refuses_when_only_the_owner_answer_is_missing():
    assert len(readiness_reasons(ready_config(allowed=False))) == 1
    assert readiness_reasons(ready_config()) == []


def test_hit_items_pair_stored_against_logged_and_ids_are_unique():
    items = build_hit_items([("h1", "s1", "fa"), ("h2", "s2", "en")])
    assert [(i.candidate, i.reference) for i in items] == [(STORED, LOGGED)] * 2
    with pytest.raises(ValueError):
        build_hit_items([("h1", "s1", "fa"), ("h1", "s2", "en")])


def test_ablation_items_and_calls():
    items, calls = build_ablation_items(
        [("r1", "s1", "fa"), ("r2", "s2", "en")], ["dedup", "k1"], "syn-a"
    )
    assert len(items) == 4 and len(calls) == 6
    assert {c.case_id for c in calls} == {
        "r1",
        "r1#dedup",
        "r1#k1",
        "r2",
        "r2#dedup",
        "r2#k1",
    }
    assert items[0].candidate == ("syn-a+dedup", None)
    assert items[0].reference == ("syn-a+original", None)
    for bad in ([], ["original"], ["a", "a"]):
        with pytest.raises(ValueError):
            build_ablation_items([("r1", "s1", "fa")], bad, "syn-a")
    with pytest.raises(ValueError):
        build_ablation_items([("r1", "s1", "fa")], ["a"], " ")


def test_mapping_content_serves_transient_text():
    view = JudgeRequestView(message="[SYNTHETIC] question")
    content = MappingContent({"h1": view}, {("h1", STORED): "[SYNTHETIC] stored"})
    assert content.request("h1") is view
    assert content.answer("h1", STORED) == "[SYNTHETIC] stored"
    assert content.answer("h1", LOGGED) is None


def test_hit_judging_plan_counts_and_bounds_with_counted_sizes():
    config = ready_config()
    items = build_hit_items([(f"h{i}", f"s{i}", "fa") for i in range(3)])
    sizes = {(i.case_id, j): 1000 for i in items for j in ("syn-a", "syn-b")}
    plan = hit_judging_plan(
        config,
        items,
        judge_input_tokens=sizes,
        catalogue=ENTRIES,
        prices=PRICES,
        candidate_max_tokens=500,
    )
    assert plan["judge_calls"] == 3 * 2 * 2 and plan["generation_calls"] == 0
    assert plan["makes_calls"] is False
    assert plan["judging"]["lower_bound_usd"] is not None
    # without sizes the bound is unknown, never a guess
    unknown = hit_judging_plan(
        config, items, judge_input_tokens=None, catalogue=ENTRIES, prices=PRICES
    )
    assert unknown["judging"]["lower_bound_usd"] is None


def test_ablation_plan_counts_generation_and_judging():
    config = ready_config()
    items, calls = build_ablation_items([("r1", "s1", "fa")], ["dedup"], "syn-a")
    sizes = {(c.case_id, "syn-a"): 2000 for c in calls}
    judge_sizes = {
        (i.case_id + "|" + i.candidate[0], j): 3000
        for i in items
        for j in ("syn-a", "syn-b")
    }
    plan = ablation_plan(
        config,
        items,
        calls,
        input_tokens=sizes,
        judge_input_tokens=judge_sizes,
        catalogue=ENTRIES,
        prices=PRICES,
    )
    assert plan["generation_calls"] == 2 and plan["judge_calls"] == 4
    assert plan["generation"]["calls"] == 2
    assert plan["generation"]["lower_bound_usd"] is not None
    assert plan["makes_calls"] is False and CATALOGUE is not None


def test_committed_config_passes_both_gates():
    _, config = committed()
    assert readiness_reasons(config) == []
