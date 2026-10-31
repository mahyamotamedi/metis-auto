"""E5: pairwise judging, calibration, agreement, bias diagnostics, the Persian
gate. SYNTHETIC answers and a deterministic fake judge that decides by length:
these tests check mechanics and hand-computed statistics, not the quality of any
judge, and say nothing about Persian ability."""

from decimal import Decimal

import pytest

from metis_auto.evaluation.comparison import (
    EvalRequest,
    Outcome,
    OutcomeTable,
    non_inferiority,
)
from metis_auto.evaluation.judging import (
    Bootstrap,
    CalibrationConfig,
    FakePairwiseJudge,
    GateConfig,
    HumanLabel,
    JudgeRequestView,
    PairItem,
    agreement,
    evaluate_gate,
    export_calibration,
    gated_tables,
    judge_items,
    pairwise_quality,
    position_bias,
    read_ratings,
    swap_consistency,
    to_csv,
    verbosity_bias,
)

M = "[SYNTHETIC] "
CAND, REF = ("cand-model", None), ("ref-model", None)


class Content:
    def __init__(self, answers=None, views=None):
        self.answers = answers or {}
        self.views = views or {}

    def request(self, case_id):
        return self.views.get(case_id, JudgeRequestView(message=M + case_id))

    def answer(self, case_id, variant):
        return self.answers.get((case_id, variant))


def item(case, language="fa", attachments=False, session=None):
    return PairItem(case, session or f"s-{case}", language, CAND, REF, attachments)


def content_for(items, cand_len=20, ref_len=10):
    answers = {}
    for it in items:
        answers[(it.case_id, CAND)] = M + "x" * cand_len
        answers[(it.case_id, REF)] = M + "y" * ref_len
    return Content(answers)


VISION = frozenset({"cand-model"})


def run(judge, items, content=None, vision=VISION):
    return judge_items(
        judge, items, content or content_for(items), vision_candidates=vision
    )


# --- pairwise with position swapping -----------------------------------------


def test_a_position_biased_judge_is_neutralised_by_the_swap():
    (out,) = run(FakePairwiseJudge("first"), [item("c1")]).outcomes
    assert (out.candidate_first, out.reference_first) == ("candidate", "reference")
    assert (out.score, out.preference, out.swap_consistent) == (0.5, "tie", False)
    assert out.first_position_picks == 2


@pytest.mark.parametrize(
    "mode, cand_len, ref_len, score, preference, picks",
    [
        ("longer", 20, 10, 1.0, "candidate", 1),
        ("longer", 5, 10, 0.0, "reference", 1),
        ("shorter", 20, 10, 0.0, "reference", 1),
        ("tie", 20, 10, 0.5, "tie", 0),
        ("longer", 10, 10, 0.5, "tie", 0),
    ],
)
def test_pair_scores_by_hand(mode, cand_len, ref_len, score, preference, picks):
    items = [item("c1")]
    (out,) = run(
        FakePairwiseJudge(mode), items, content_for(items, cand_len, ref_len)
    ).outcomes
    assert (out.score, out.preference, out.first_position_picks) == (
        score,
        preference,
        picks,
    )
    assert out.swap_consistent is True
    assert (out.candidate_chars, out.reference_chars) == (
        len(M) + cand_len,
        len(M) + ref_len,
    )


def test_judge_cost_is_evaluation_cost_and_adds_two_calls_per_pair():
    items = [item("c1"), item("c2")]
    judge = FakePairwiseJudge("longer", cost_per_call_usd=Decimal("0.001"))
    result = run(judge, items)
    assert judge.calls == 4  # both orderings of both pairs
    assert (
        result.cost_usd_total == Decimal("0.004") and result.cost_kind == "evaluation"
    )
    free = run(FakePairwiseJudge("longer"), items)
    assert free.cost_usd_total == 0 and free.judge_id == "fake-pairwise@0"


def test_a_missing_answer_is_not_judged_and_costs_no_call():
    judge = FakePairwiseJudge("longer")
    result = run(judge, [item("c1")], Content({}))
    assert (result.outcomes[0].state, result.outcomes[0].reason) == (
        "not_evaluated",
        "answer_missing",
    )
    assert judge.calls == 0 and result.judged == ()


def test_image_turns_are_excluded_unless_everyone_can_see_them():
    items = [item("c1", attachments=True)]
    unset = run(FakePairwiseJudge("longer", supports_images=True), items, vision=None)
    assert unset.outcomes[0].reason == "vision_capability_unset"
    other = run(
        FakePairwiseJudge("longer", supports_images=True),
        items,
        vision=frozenset({"x"}),
    )
    assert other.outcomes[0].reason == "candidate_not_vision"
    blind = FakePairwiseJudge("longer", supports_images=False)
    assert run(blind, items).outcomes[0].reason == "judge_cannot_see_images"
    assert blind.calls == 0  # nothing was sent to a judge that cannot see them
    ok = run(FakePairwiseJudge("longer", supports_images=True), items)
    assert ok.outcomes[0].state == "judged" and ok.excluded_by_reason == {}
    assert unset.excluded_by_reason == {"vision_capability_unset": 1}


def test_the_judge_is_shown_the_logged_retrieved_context():
    judge = FakePairwiseJudge("tie")
    items = [item("c1")]
    content = content_for(items)
    content.views["c1"] = JudgeRequestView(
        message=M + "q", retrieved=M + "logged context"
    )
    run(judge, items, content)
    assert all(v.retrieved == M + "logged context" for v in judge.views)


def test_pairwise_quality_keys_for_the_run_tables():
    items = [item("c1"), item("c2")]
    scores = pairwise_quality(run(FakePairwiseJudge("longer"), items), REF)
    assert scores == {
        ("c1", "cand-model", None): 1.0,
        ("c2", "cand-model", None): 1.0,
        ("c1", "ref-model", None): 0.5,
        ("c2", "ref-model", None): 0.5,
    }


# --- calibration export and import -------------------------------------------


def outcomes_for(n_fa, n_en):
    items = [item(f"fa{i}", "fa") for i in range(n_fa)] + [
        item(f"en{i}", "en") for i in range(n_en)
    ]
    return run(FakePairwiseJudge("longer"), items).outcomes


def test_export_needs_its_config_and_never_fills_a_persian_shortfall():
    outcomes = outcomes_for(20, 5)
    assert export_calibration(outcomes, CalibrationConfig()).reason == "size_unset"
    assert (
        export_calibration(outcomes, CalibrationConfig(size=10)).reason
        == "persian_share_unset"
    )
    assert (
        export_calibration(
            outcomes, CalibrationConfig(size=10, persian_share=0.8)
        ).reason
        == "seed_unset"
    )
    ok = export_calibration(
        outcomes, CalibrationConfig(size=10, persian_share=0.8, seed="s")
    )
    assert (ok.persian_target, ok.persian_achieved, ok.other_achieved) == (8, 8, 2)
    assert not ok.persian_unmet and ok.notes == ()
    again = export_calibration(
        outcomes, CalibrationConfig(size=10, persian_share=0.8, seed="s")
    )
    assert [i.item_id for i in ok.items] == [i.item_id for i in again.items]
    short = export_calibration(
        outcomes_for(3, 5), CalibrationConfig(size=10, persian_share=0.8, seed="s")
    )
    assert (short.persian_achieved, short.persian_unmet) == (3, True)
    assert "persian_items_fewer_than_target" in short.notes
    assert short.other_achieved == 2  # never topped up past the planned share


def test_the_rating_sheet_holds_ids_language_and_lengths_only():
    export = export_calibration(
        outcomes_for(3, 1), CalibrationConfig(size=4, persian_share=0.75, seed="s")
    )
    sheet = to_csv(export)
    header, *rows = sheet.splitlines()
    assert (
        header == "item_id,language,candidate,reference,"
        "candidate_chars,reference_chars,rater_id,preference"
    )
    assert len(rows) == 4 and all(r.endswith(",,") for r in rows)
    assert "x" * 5 not in sheet and "SYNTHETIC" not in sheet


def test_ratings_are_read_with_a_strict_majority_consensus():
    text = (
        "item_id,rater_id,preference\n"
        "a,r1,candidate\na,r2,candidate\na,r3,reference\n"
        "b,r1,candidate\nb,r2,reference\n"
        "c,r1,\n"
        "d,r1,TIE\n"
    )
    labels = read_ratings(text)
    assert labels["a"] == HumanLabel("a", 3, "candidate")
    assert labels["b"].consensus is None and labels["b"].n_raters == 2
    assert "c" not in labels  # an unrated row is skipped
    assert labels["d"].consensus == "tie"


@pytest.mark.parametrize(
    "text, message",
    [
        ("item_id,rater_id,preference\na,r1,maybe\n", "row 2"),
        ("item_id,rater_id,preference\na,,candidate\n", "row 2"),
        ("item_id,preference\na,candidate\n", "missing columns"),
    ],
)
def test_bad_rating_files_are_refused_without_echoing_content(text, message):
    with pytest.raises(ValueError, match=message):
        read_ratings(text)


# --- agreement and diagnostics ------------------------------------------------


def judged(preferences, cand_len=20, ref_len=10):
    """Outcomes whose pair preference is forced by a scripted judge."""
    items = [item(f"c{i}") for i in range(len(preferences))]
    want = dict(zip((i.case_id for i in items), preferences, strict=True))

    def script(view, first, second):
        case = view.message.removeprefix(M)
        side = want[case]
        if side == "tie":
            return "tie"
        candidate_first = first.startswith(M + "x")
        wants_candidate = side == "candidate"
        return "first" if candidate_first == wants_candidate else "second"

    judge = FakePairwiseJudge("scripted", scripted=script)
    return run(judge, items, content_for(items, cand_len, ref_len)).outcomes


def labels_for(preferences):
    return {
        f"c{i}~cand-model@-~ref-model@-": HumanLabel(f"c{i}", 1, p)
        for i, p in enumerate(preferences)
    }


JUDGE = ["candidate", "candidate", "tie", "reference"]
HUMAN = ["candidate", "reference", "tie", "reference"]


def test_agreement_statistics_by_hand():
    outcomes, labels = judged(JUDGE), labels_for(HUMAN)
    acc = agreement(outcomes, labels, statistic="accuracy", bootstrap=None)
    assert (acc.value, acc.n, acc.provenance) == (0.75, 4, "estimated")
    kappa = agreement(outcomes, labels, statistic="cohen_kappa", bootstrap=None)
    # observed 0.75; chance 2/4*1/4 + 1/4*1/4 + 1/4*2/4 = 0.3125
    assert kappa.value == pytest.approx((0.75 - 0.3125) / (1 - 0.3125))


def test_agreement_says_why_it_is_missing_and_needs_a_bootstrap_for_an_interval():
    outcomes, labels = judged(JUDGE), labels_for(HUMAN)
    unset = agreement(outcomes, labels, statistic=None, bootstrap=None)
    assert (unset.state, unset.reason) == ("not_evaluated", "agreement_statistic_unset")
    none = agreement(outcomes, {}, statistic="accuracy", bootstrap=None)
    assert none.reason == "no_rated_items"
    with_interval = agreement(
        outcomes, labels, statistic="accuracy", bootstrap=Bootstrap(100, "b", 0.9)
    )
    assert with_interval.interval is not None and with_interval.claims_allowed
    same = judged(["candidate"] * 3)
    undefined = agreement(
        same, labels_for(["candidate"] * 3), statistic="cohen_kappa", bootstrap=None
    )
    assert (undefined.state, undefined.reason) == ("undefined", "statistic_undefined")


def test_position_bias_and_swap_consistency_are_read_off_the_two_orderings():
    items = [item(f"c{i}") for i in range(4)]
    biased = run(FakePairwiseJudge("first"), items).outcomes
    assert position_bias(biased).value == 1.0 and swap_consistency(biased).value == 0.0
    fair = run(FakePairwiseJudge("longer"), items).outcomes
    assert position_bias(fair).value == 0.5 and swap_consistency(fair).value == 1.0
    ties = run(FakePairwiseJudge("tie"), items).outcomes
    assert position_bias(ties).reason == "no_non_tie_verdicts"
    assert swap_consistency(()).reason == "no_judged_items"


def test_verbosity_bias_is_the_judge_minus_the_humans():
    items = [item(f"c{i}") for i in range(4)]
    outcomes = run(FakePairwiseJudge("longer"), items).outcomes  # always the longer one
    humans_prefer_shorter = labels_for(["reference"] * 4)  # candidate is the longer
    bias = verbosity_bias(outcomes, humans_prefer_shorter)
    assert bias.value == 1.0 and bias.extra["judge_longer_share"] == 1.0
    assert bias.extra["human_longer_share"] == 0.0
    agree = verbosity_bias(outcomes, labels_for(["candidate"] * 4))
    assert agree.value == 0.0
    assert verbosity_bias(outcomes, {}).reason == "no_comparable_items"


# --- the gate ------------------------------------------------------------------


def est(value, n=50, interval=None, state="measured"):
    from metis_auto.evaluation.comparison import Estimate

    if state != "measured":
        return Estimate(state, n, "estimated", reason="x")
    return Estimate("measured", n, "estimated", value=value, interval=interval)


@pytest.mark.parametrize(
    "gate, agreement_est, validated, reason",
    [
        (
            GateConfig(min_agreement=0.8, min_items=10),
            est(0.9),
            False,
            "agreement_statistic_unset",
        ),
        (
            GateConfig(agreement_statistic="accuracy", min_items=10),
            est(0.9),
            False,
            "min_agreement_unset",
        ),
        (
            GateConfig(agreement_statistic="accuracy", min_agreement=0.8),
            est(0.9),
            False,
            "min_items_unset",
        ),
        (
            GateConfig(
                agreement_statistic="accuracy", min_agreement=0.8, min_items=100
            ),
            est(0.9),
            False,
            "n_below_min_items",
        ),
        (
            GateConfig(agreement_statistic="accuracy", min_agreement=0.8, min_items=10),
            est(0.7),
            False,
            "agreement_below_threshold",
        ),
        (
            GateConfig(agreement_statistic="accuracy", min_agreement=0.8, min_items=10),
            est(0.8),
            True,
            None,
        ),
        # with an interval the conservative lower bound decides
        (
            GateConfig(agreement_statistic="accuracy", min_agreement=0.8, min_items=10),
            est(0.9, interval=(0.7, 0.95)),
            False,
            "agreement_below_threshold",
        ),
        (
            GateConfig(agreement_statistic="accuracy", min_agreement=0.8, min_items=10),
            est(0.9, interval=(0.85, 0.95)),
            True,
            None,
        ),
        (
            GateConfig(agreement_statistic="accuracy", min_agreement=0.8, min_items=10),
            est(0, state="not_evaluated"),
            False,
            "agreement_not_evaluated",
        ),
    ],
)
def test_the_gate_passes_fails_or_is_unset(gate, agreement_est, validated, reason):
    result = evaluate_gate({"fa": agreement_est}, gate)["fa"]
    assert (result.validated, result.reason) == (validated, reason)


def test_gate_config_validation():
    with pytest.raises(ValueError):
        GateConfig(min_agreement=2)
    with pytest.raises(ValueError):
        GateConfig(min_items=0)
    assert GateConfig().min_agreement is None  # nothing is set by default


# --- unvalidated scores cannot reach a claim ----------------------------------


def quality_table(validated=False):
    requests = []
    for language, n in (("fa", 30), ("en", 30)):
        for i in range(n):
            requests.append(
                EvalRequest(
                    f"{language}{i}",
                    f"s-{language}{i}",
                    language,
                    {
                        "cand": Outcome(1.0, 0.71 + 0.01 * (i % 3)),
                        "ref": Outcome(2.0, 0.72 + 0.01 * (i % 3)),
                    },
                )
            )
    return OutcomeTable(tuple(requests), "simulated", "estimated", validated)


def claim(table):
    cand = {r.request_id: "cand" for r in table.requests}
    ref = {r.request_id: "ref" for r in table.requests}
    return non_inferiority(
        table, cand, ref, delta=0.05, min_n=10, n_boot=100, seed="s", level=0.9
    )


def test_only_a_slice_whose_gate_passed_can_reach_a_non_inferiority_claim():
    gate = GateConfig(agreement_statistic="accuracy", min_agreement=0.8, min_items=10)
    results = evaluate_gate(
        {"fa": est(0.9, interval=(0.85, 0.95)), "en": est(0.6, n=5)}, gate
    )
    tables = gated_tables(quality_table(), results)
    assert tables["fa"].quality_validated is True
    assert tables["en"].quality_validated is False
    assert tables["all"].quality_validated is False  # not every language passed
    passed = claim(tables["fa"])
    assert passed.estimate.measured and passed.non_inferior is True
    for blocked in (tables["en"], tables["all"]):
        out = claim(blocked)
        assert (out.estimate.state, out.estimate.reason) == (
            "not_evaluated",
            "unvalidated_quality",
        )
        assert out.non_inferior is None


def test_with_the_gate_unset_every_slice_stays_unvalidated():
    results = evaluate_gate(
        {"fa": est(0.99, interval=(0.98, 1.0)), "en": est(0.99)}, GateConfig()
    )
    tables = gated_tables(quality_table(), results)
    assert not any(t.quality_validated for t in tables.values())
    assert claim(tables["fa"]).estimate.reason == "unvalidated_quality"
    # a language with no gate result at all is unvalidated too
    only_fa = gated_tables(quality_table(), {"fa": results["fa"]})
    assert only_fa["en"].quality_validated is False
