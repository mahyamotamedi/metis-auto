"""R8 metrics (exp-route-013) on hand-made SYNTHETIC rows: the gate proposal
takes its threshold from the tune split only and reports its effect on the check
split; the per-question distributions; the probability strength of an answer."""

from __future__ import annotations

from metis_auto.contracts import DecisionAnswer, DecisionQuestionType
from metis_auto.domain.routing.decision import answer_strength
from metis_auto.evaluation.router_eval import (
    ShadowRow,
    answer_distributions,
    propose_gate,
)


def row(i, split, gate, rules=1, router=0):
    return ShadowRow(
        record_id=f"r{i}",
        split=split,
        language_group="persian",
        weight=1.0,
        rules_tier=rules,
        router_tier=router,
        router_path="slow_local",
        decision_status="answered",
        confidence=gate,
        below_gate=False,
        decide_ms=1.0,
        strengths=(("cheap_model_ok", gate, gate + 0.1),),
        gate_reported=gate,
        gate_probability=gate + 0.1,
    )


def test_the_threshold_comes_from_tune_and_its_effect_is_measured_on_check():
    tune = [row(i, "tune", g) for i, g in enumerate([0.1, 0.2, 0.3, 0.4, 0.5])]
    check = [row(10 + i, "check", g) for i, g in enumerate([0.05, 0.6, 0.7, 0.8])]
    out = propose_gate(tune + check, keep_share=0.8)
    reported = out["reported"]
    assert reported["threshold"] == 0.2  # the tune split's 20th percentile
    assert reported["tune_answered"] == 5 and reported["check_answered"] == 4
    assert reported["check_gated_share"] == 0.25  # only 0.05 < 0.2
    # the gated record falls back to the rules (tier 1); the rest keep tier 0
    assert reported["check_tier_mix_with_gate"] == {"0": 0.75, "1": 0.25}
    assert reported["check_agreement_with_rules_with_gate"] == 0.25
    assert out["probability"]["threshold"] == 0.3


def test_answer_distributions_per_question():
    dist = answer_distributions([row(i, "tune", 0.1 * i) for i in range(1, 11)])
    q = dist["cheap_model_ok"]
    assert q["reported_confidence"]["n"] == 10
    assert q["reported_confidence"]["min"] == 0.1
    assert q["probability"]["p50"] is not None


def test_the_probability_strength_of_an_answer():
    noul = DecisionAnswer(
        question_id="x", type=DecisionQuestionType.NOUL, p_yes=0.2, confidence=0.1
    )
    assert answer_strength(noul, "reported") == 0.1
    assert answer_strength(noul, "probability") == 0.8
    choice = DecisionAnswer(
        question_id="y",
        type=DecisionQuestionType.CHOICE,
        choice="a",
        probabilities={"a": 0.55, "b": 0.45},
    )
    assert answer_strength(choice, "probability") == 0.55
    assert answer_strength(choice, "reported") is None
