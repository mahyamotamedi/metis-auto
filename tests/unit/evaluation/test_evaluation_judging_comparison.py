"""E5: instruction-language comparison and the re-simulation stub. SYNTHETIC; the
judges are deterministic fakes, so nothing here says which instruction language
is better for Persian."""

from decimal import Decimal

import pytest

from metis_auto.evaluation.judging import (
    Bootstrap,
    FakePairwiseJudge,
    HumanLabel,
    JudgeRequestView,
    PairItem,
    ResimulationConfig,
    compare_instruction_languages,
    resimulate,
    teacher_forcing_gap,
)

M = "[SYNTHETIC] "
CAND, REF = ("cand-model", None), ("ref-model", None)


class Content:
    def __init__(self, items):
        self._answers = {}
        for it in items:
            self._answers[(it.case_id, CAND)] = M + "x" * 20
            self._answers[(it.case_id, REF)] = M + "y" * 10

    def request(self, case_id):
        return JudgeRequestView(message=M + case_id)

    def answer(self, case_id, variant):
        return self._answers.get((case_id, variant))


def items_for(n_fa=6, n_mixed=4):
    out = []
    for language, n in (("fa", n_fa), ("mixed", n_mixed)):
        out += [
            PairItem(f"{language}{i}", f"s-{language}{i}", language, CAND, REF)
            for i in range(n)
        ]
    return out


def labels_for(items, preference="candidate"):
    return {it.item_id: HumanLabel(it.case_id, 1, preference) for it in items}


def compare(items=None, **kw):
    items = items or items_for()
    judges = {
        "fa": FakePairwiseJudge(
            "longer",
            judge_id="fa-judge@0",
            instruction_language="fa",
            cost_per_call_usd=Decimal("0.002"),
        ),
        "en": FakePairwiseJudge(
            "tie",
            judge_id="en-judge@0",
            instruction_language="en",
            cost_per_call_usd=Decimal("0.001"),
        ),
    }
    args = {
        "answer_languages": ("fa", "mixed"),
        "statistic": "accuracy",
        "min_n": 5,
        "bootstrap": None,
        "vision_candidates": None,
    }
    return compare_instruction_languages(
        judges, items, Content(items), labels_for(items), **{**args, **kw}
    )


def test_every_instruction_by_answer_language_cell_is_reported_separately():
    result = compare()
    cells = {(c.instruction_language, c.answer_language): c for c in result.cells}
    assert [(c.answer_language, c.instruction_language) for c in result.cells] == [
        ("fa", "en"),
        ("fa", "fa"),
        ("mixed", "en"),
        ("mixed", "fa"),
    ]
    longer = cells[("fa", "fa")]
    assert (longer.n_items, longer.n_rated) == (6, 6)
    assert (
        longer.agreement.value == 1.0
    )  # the fake prefers the longer answer; humans agree
    assert cells[("en", "fa")].agreement.value == 0.0  # the tie judge never agrees
    assert longer.judge_id == "fa-judge@0"
    assert longer.swap_consistency.value == 1.0 and longer.position_bias.value == 0.5


def test_no_winner_is_selected_and_small_cells_are_only_descriptive():
    result = compare()
    assert "no winner is selected" in result.note
    assert not any(
        hasattr(result, name) for name in ("winner", "best", "ranking", "recommended")
    )
    assert not any(
        hasattr(c, name) for c in result.cells for name in ("winner", "best")
    )
    by = {(c.instruction_language, c.answer_language): c for c in result.cells}
    assert by[("fa", "fa")].label == "rankable"  # sufficiency only: n = 6 >= 5
    assert (by[("fa", "mixed")].label, by[("fa", "mixed")].label_reason) == (
        "descriptive",
        "n_below_minimum",
    )
    unset = compare(min_n=None)
    assert {c.label_reason for c in unset.cells} == {"min_n_unset"}


def test_judge_cost_is_reported_per_judge_as_evaluation_cost():
    result = compare()
    # 10 pairs, two orderings each
    assert result.judge_cost_usd == {"fa": Decimal("0.040"), "en": Decimal("0.020")}
    assert result.cost_kind == "evaluation"


def test_intervals_appear_only_with_a_bootstrap_and_the_statistic_is_not_defaulted():
    plain = compare()
    assert all(c.agreement.interval is None for c in plain.cells)
    boot = compare(bootstrap=Bootstrap(50, "b", 0.9))
    assert any(c.agreement.interval is not None for c in boot.cells)
    unset = compare(statistic=None)
    assert {c.agreement.reason for c in unset.cells} == {"agreement_statistic_unset"}


def test_a_judge_must_report_the_language_it_is_filed_under():
    items = items_for(2, 0)
    wrong = {"fa": FakePairwiseJudge("longer", instruction_language="en")}
    with pytest.raises(ValueError, match="reports"):
        compare_instruction_languages(
            wrong,
            items,
            Content(items),
            labels_for(items),
            answer_languages=("fa",),
            statistic="accuracy",
            min_n=None,
            bootstrap=None,
            vision_candidates=None,
        )


# --- the re-simulation stub ----------------------------------------------------


class Simulator:
    """A fake user simulator: two follow-ups, then it ends."""

    def __init__(self, follow_ups=2):
        self._left = follow_ups

    def next_message(self, transcript):
        if self._left == 0:
            return None
        self._left -= 1
        return M + "follow-up"


def run_stub(config, follow_ups=2, cases=("a", "b", "c")):
    return resimulate(
        cases,
        first_message=lambda c: M + "hello " + c,
        answer=lambda c, transcript: M + "answer " * len(transcript),
        simulator=Simulator(follow_ups),
        config=config,
    )


def test_the_stub_needs_both_limits_and_says_it_is_not_a_simulator():
    assert run_stub(ResimulationConfig()).reason == "max_turns_unset"
    assert run_stub(ResimulationConfig(max_turns=3)).reason == "max_sessions_unset"
    result = run_stub(ResimulationConfig(max_turns=5, max_sessions=2))
    assert "not a working Persian simulator" in result.note


def test_the_stub_loop_stops_at_the_simulator_or_the_turn_limit_and_keeps_only_counts():
    ended = run_stub(ResimulationConfig(max_turns=10, max_sessions=2), follow_ups=2)
    assert [t.case_id for t in ended.traces] == ["a", "b"]  # max_sessions
    # the simulator is shared: session 1 uses its two follow-ups, session 2 none
    assert (
        ended.traces[0].turns == 3 and ended.traces[0].stopped_by == "simulator_ended"
    )
    capped = resimulate(
        ["a"],
        first_message=lambda c: M + "hi",
        answer=lambda c, t: M + "a",
        simulator=Simulator(100),
        config=ResimulationConfig(max_turns=3, max_sessions=1),
    )
    assert (capped.traces[0].turns, capped.traces[0].stopped_by) == (3, "max_turns")
    assert "[SYNTHETIC]" not in repr(capped)  # lengths only


def test_teacher_forcing_gap_is_a_paired_mean_over_shared_cases():
    est = teacher_forcing_gap(
        {"a": 0.5, "b": 0.7, "x": 1.0}, {"a": 0.6, "b": 0.5, "y": 0.0}
    )
    assert est.n == 2 and est.value == pytest.approx(((0.6 - 0.5) + (0.5 - 0.7)) / 2)
    assert teacher_forcing_gap({}, {"a": 1.0}).reason == "no_shared_cases"


def test_image_turns_are_dropped_for_models_not_known_to_see_images_with_counts():
    from metis_auto.evaluation.sampling import (
        PlannedCall,
        SamplingUnit,
        partition_image_calls,
    )

    units = {
        "a": SamplingUnit("a", "s1", {"attachments": "yes"}),
        "b": SamplingUnit("b", "s2", {"attachments": "no"}),
    }
    calls = [PlannedCall(c, f"s-{c}", m, None, 0) for c in "ab" for m in ("v", "t")]
    kept, excluded = partition_image_calls(calls, units, vision_models=frozenset({"v"}))
    assert [(c.case_id, c.model_id) for c in kept] == [
        ("a", "v"),
        ("b", "v"),
        ("b", "t"),
    ]
    assert excluded == {"model_not_vision": 1}
    kept, excluded = partition_image_calls(calls, units, vision_models=None)
    assert len(kept) == 2 and excluded == {"vision_capability_unset": 2}
