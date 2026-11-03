"""R8 shadow evaluation (exp-route-013) on the SYNTHETIC miniature slice, with
the fake backend: rules only vs the router per record, the R8 blocks (splits,
balanced and traffic-weighted, Persian first), content-free output, and the L4
check: SYNTHETIC tier labels scored by the harness (a scripted "cheap" or
"complex" backend must reproduce its own labels wherever it answered)."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pyarrow")

from integration.test_router_slice_build import make_repo, make_slice  # noqa: E402

from metis_auto.evaluation.router_eval import LANGUAGE_ORDER  # noqa: E402
from metis_auto.settings import load_settings  # noqa: E402
from metis_auto.wiring.router_eval import evaluate, shadow_rows  # noqa: E402


def hermetic(overrides):
    return load_settings(environ={}, dotenv=None, runtime=None, overrides=overrides)


@pytest.fixture(scope="module")
def records(tmp_path_factory):
    repo, data, _ = make_repo(tmp_path_factory.mktemp("shadow"))
    sl = make_slice(repo, data)
    sl.build()
    return sl.frozen_records()


def test_every_record_gets_a_row_and_the_blocks_are_complete(records):
    out = evaluate(hermetic, records, backend="fake", profile="cheap")
    assert out["records"] == len(records) == 100
    for split in ("all", "tune", "check"):
        for view in ("balanced", "traffic_weighted"):
            block = out["splits"][split][view]
            assert set(block) >= {
                "tier_mix_rules",
                "tier_mix_router",
                "agreement",
                "gate_skip_share",
                "path_mix",
                "confidence",
                "decision_step_ms",
            }
    langs = list(out["languages"])
    known = [g for g in LANGUAGE_ORDER if g in langs]
    assert langs[: len(known)] == known
    text = json.dumps(out, ensure_ascii=False)
    for r in records[:20]:
        assert r["message"] not in text and r["slice_record_id"] not in text


@pytest.mark.parametrize(("profile", "tier"), [("cheap", 0), ("complex", 1)])
def test_l4_synthetic_labels_are_reproduced_where_the_router_answered(
    records, profile, tier
):
    rows = shadow_rows(hermetic, records, backend="fake", profile=profile)
    answered = [r for r in rows if r.decision_status == "answered"]
    assert answered, "the fake backend answers every asked record"
    labels = {r.record_id: tier for r in answered}
    scored = evaluate(
        hermetic, records, backend="fake", profile=profile, labels=labels
    )["labels"]
    assert scored["labelled"] == len(answered)
    assert scored["unlabelled"] == len(rows) - len(answered)
    # A scripted backend maps to its own tier unless no model of that tier is
    # eligible for the request (then the policy's fallback picks one).
    assert scored["router_accuracy"] >= 0.9


def test_offline_mode_records_real_answers_and_proposes_a_gate(records):
    """Offline (owner, 2026-11-03): no inline deadline, no cache, gate off, so
    every asked record is answered; per-question distributions and the gate
    proposal (threshold from tune, effect on check) are reported."""
    out = evaluate(hermetic, records, backend="fake", profile="neutral", offline=True)
    assert out["mode"] == "offline"
    status = out["splits"]["all"]["balanced"]["decision_status"]
    assert "failed" not in status and status.get("answered", 0) > 0
    dist = out["answer_strengths"]["all"]
    assert set(dist) >= {"complexity", "needs_reasoning", "cheap_model_ok", "intent"}
    assert dist["cheap_model_ok"]["probability"]["n"] > 0
    gate = out["gate_proposal"]
    for statistic in ("reported", "probability"):
        assert gate[statistic]["threshold"] is not None
        assert 0 <= gate[statistic]["check_gated_share"] <= 1
