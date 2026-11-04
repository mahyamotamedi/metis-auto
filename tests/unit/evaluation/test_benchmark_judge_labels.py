"""P-2 judge (strict JSON, cost and latency, both orders, refusals never crash)
and P-3 labels (the R-B3 / R-C3 hand-off), plus the 60-item spot-check sheet.
ADR-0053. SYNTHETIC text; scripted clients, no network."""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.adapters.system import FakeClock
from metis_auto.contracts import (
    AnswerSource,
    ComponentName,
    ErrorClass,
    Fidelity,
    FinishReason,
    InputPart,
    ModelError,
    ModelResponse,
    PartRole,
    TokenCount,
    TokenUsage,
)
from metis_auto.evaluation.benchmark import labels as lb
from metis_auto.evaluation.benchmark import spot_check as sc
from metis_auto.evaluation.benchmark.config import OwnerValueUnset
from metis_auto.evaluation.benchmark.judge import (
    JudgeCallFailed,
    JudgeOutputInvalid,
    LlmPairwiseJudge,
    judge_all,
    parse_choice,
    require_two_families,
    view_from_parts,
)
from metis_auto.evaluation.judging.types import JudgeRequestView, PairItem

ROOT = Path(__file__).resolve().parents[3]
NOW = __import__("datetime").datetime(2026, 11, 3, tzinfo=__import__("datetime").UTC)


# --- strict parsing -------------------------------------------------------------


@pytest.mark.parametrize(
    "text, choice",
    [
        ('{"choice": "first"}', "first"),
        ('  {"choice":"tie"}\n', "tie"),
        ('```json\n{"choice": "second"}\n```', "second"),
        ('```\n{"choice": "first"}\n```', "first"),
    ],
)
def test_strict_json_is_parsed(text, choice):
    assert parse_choice(text) == choice


@pytest.mark.parametrize(
    "text, reason",
    [
        (None, "empty_output"),
        ("  ", "empty_output"),
        ("The first answer is better.", "not_json"),
        ('I pick {"choice": "first"}', "not_json"),
        ('{"choice": "first"} {"choice": "second"}', "not_json"),
        ('["first"]', "not_an_object"),
        ('{"choice": "first", "reason": "x"}', "unexpected_keys"),
        ('{"winner": "first"}', "unexpected_keys"),
        ('{"choice": "First"}', "invalid_choice"),
        ('{"choice": "A"}', "invalid_choice"),
    ],
)
def test_anything_else_is_refused_never_guessed(text, reason):
    with pytest.raises(JudgeOutputInvalid) as err:
        parse_choice(text)
    assert err.value.reason == reason


# --- the judge over a scripted client ---------------------------------------------


def _usage(model, inp=900, out=8):
    return TokenUsage(
        model_id=model,
        input=TokenCount(tokens=inp, fidelity=Fidelity.PROVIDER_REPORTED, method="t"),
        output=TokenCount(tokens=out, fidelity=Fidelity.PROVIDER_REPORTED, method="t"),
    )


class Scripted:
    """Answers each invocation from a list of texts (or results)."""

    def __init__(self, replies, clock=None):
        self.replies = list(replies)
        self.seen = []
        self.clock = clock

    @property
    def source(self):
        return AnswerSource.LIVE

    def invoke(self, invocation):
        self.seen.append(invocation)
        if self.clock is not None:
            self.clock.advance(250)
        reply = self.replies.pop(0)
        if not isinstance(reply, str):
            return reply
        return ModelResponse(
            text=reply,
            finish_reason=FinishReason.COMPLETE,
            usage=_usage(invocation.model_id),
            source=AnswerSource.LIVE,
        )


VIEW = JudgeRequestView(
    message="[SYNTHETIC] سلام، ساعت کاری چیست؟", instructions="[SYNTHETIC] bot"
)


def _judge(client, clock, lang="en"):
    return LlmPairwiseJudge(
        client,
        model_id="syn-judge",
        instruction_language=lang,
        max_output_tokens=16,
        price=lambda u: Decimal("0.0001") if u else None,
        clock=clock,
        run_id="run-syn",
    )


def test_judge_sends_plain_chat_records_cost_and_latency():
    clock = FakeClock(NOW)
    client = Scripted(['{"choice": "second"}'], clock)
    judge = _judge(client, clock)
    verdict = judge.compare(VIEW, "[SYNTHETIC] A", "[SYNTHETIC] B")
    assert verdict.choice == "second" and verdict.cost_usd == Decimal("0.0001")
    inv = client.seen[0]
    assert inv.model_id == "syn-judge" and inv.max_output_tokens == 16
    assert [p.role for p in inv.parts] == [PartRole.INSTRUCTIONS, PartRole.USER]
    assert '{"choice": "first"}' in inv.parts[0].text
    body = inv.parts[1].text
    assert (
        body.index("[First answer]")
        < body.index("[SYNTHETIC] A")
        < body.index("[Second answer]")
        < body.index("[SYNTHETIC] B")
    )
    assert "json_schema" not in inv.model_dump_json()  # never a response_format
    (record,) = judge.records
    assert record.outcome == "verdict" and record.latency_ms == 250
    assert record.cost_kind == "evaluation" and record.input_tokens == 900
    assert "SYNTHETIC" not in repr(record)  # content-free


def test_judge_refuses_bad_output_and_reports_failed_calls():
    clock = FakeClock(NOW)
    judge = _judge(Scripted(["first, clearly"], clock), clock)
    with pytest.raises(JudgeOutputInvalid):
        judge.compare(VIEW, "a", "b")
    assert judge.records[0].outcome == "invalid_output:not_json"
    assert judge.records[0].cost_usd == Decimal("0.0001")  # paid even if refused
    err = ModelError(
        error_class=ErrorClass.RATE_LIMITED, retryable=True, source=AnswerSource.LIVE
    )
    judge = _judge(Scripted([err], clock), clock)
    with pytest.raises(JudgeCallFailed, match="error:rate_limited"):
        judge.compare(VIEW, "a", "b")


def test_persian_instructions_ask_for_the_same_json():
    clock = FakeClock(NOW)
    client = Scripted(['{"choice": "tie"}'], clock)
    judge = _judge(client, clock, lang="fa")
    assert judge.compare(VIEW, "a", "b").choice == "tie"
    assert '{"choice": "second"}' in client.seen[0].parts[0].text
    assert judge.judge_id.endswith("-fa")
    with pytest.raises(ValueError):
        _judge(client, clock, lang="de")


class Content:
    def __init__(self, answers):
        self.answers = answers

    def request(self, case_id):
        return VIEW

    def answer(self, case_id, variant):
        return self.answers.get((case_id, variant[0]))


def _item(case, cand="syn-cheap", lang="persian"):
    return PairItem(case, case, lang, (cand, None), ("syn-ref", None))


def test_judge_all_uses_both_orders_and_never_crashes():
    clock = FakeClock(NOW)
    answers = {
        (c, m): f"[SYNTHETIC] {c}/{m}"
        for c in ("c1", "c2", "c3", "c4")
        for m in ("syn-cheap", "syn-ref")
    }
    del answers[("c4", "syn-cheap")]
    replies = [
        '{"choice": "first"}',
        '{"choice": "second"}',  # c1: candidate wins both
        '{"choice": "first"}',
        "nonsense",  # c2: second order refused
        ModelError(
            error_class=ErrorClass.TIMEOUT, retryable=True, source=AnswerSource.LIVE
        ),  # c3: call failed
    ]
    judge = _judge(Scripted(replies, clock), clock)
    run = judge_all(
        judge,
        [_item("c1"), _item("c2"), _item("c3"), _item("c4")],
        Content(answers),
        vision_candidates=None,
    )
    by = {o.item.case_id: o for o in run.outcomes}
    assert by["c1"].state == "judged" and by["c1"].score == 1.0
    assert by["c1"].swap_consistent is True
    assert by["c2"].reason == "judge_output_invalid:not_json"
    assert by["c3"].reason == "judge_call_failed:error:timeout"
    assert by["c4"].reason == "answer_missing"
    assert run.cost_kind == "evaluation"
    assert run.excluded_by_reason["judge_output_invalid:not_json"] == 1
    assert [r.outcome for r in judge.records] == [
        "verdict",
        "verdict",
        "verdict",
        "invalid_output:not_json",
        "failed:error:timeout",
    ]


def test_judge_all_keeps_finished_pairs_when_interrupted():
    clock = FakeClock(NOW)
    answers = {
        (c, m): f"[SYNTHETIC] {c}/{m}"
        for c in ("c1", "c2", "c3")
        for m in ("syn-cheap", "syn-ref")
    }
    replies = [
        '{"choice": "first"}',
        '{"choice": "second"}',  # c1 judged in both orders
        KeyboardInterrupt(),  # c2 interrupted: abandoned, not scored
    ]

    class Interrupting(Scripted):
        def invoke(self, invocation):
            if isinstance(self.replies[0], KeyboardInterrupt):
                raise self.replies[0]
            return super().invoke(invocation)

    judge = _judge(Interrupting(replies, clock), clock)
    run = judge_all(
        judge,
        [_item("c1"), _item("c2"), _item("c3")],
        Content(answers),
        vision_candidates=None,
    )
    assert [o.item.case_id for o in run.outcomes] == ["c1"]
    assert run.outcomes[0].state == "judged"


def test_two_judges_from_different_families():
    class E:
        def __init__(self, provider):
            self.provider = provider

    cat = {"a": E("openai"), "b": E("deepseek"), "c": E("openai")}
    require_two_families(("a", "b"), cat)
    for bad in (("a", "c"), ("a",), ("a", "a"), ("a", "zz")):
        with pytest.raises(ValueError):
            require_two_families(bad, cat)


def test_view_from_parts_keeps_every_component():
    parts = (
        InputPart(
            role=PartRole.INSTRUCTIONS,
            text="[SYNTHETIC] ins",
            component=ComponentName.INSTRUCTIONS,
        ),
        InputPart(
            role=PartRole.USER,
            text="[SYNTHETIC] earlier",
            component=ComponentName.HISTORY,
            item_index=0,
        ),
        InputPart(
            role=PartRole.ASSISTANT,
            text="[SYNTHETIC] reply",
            component=ComponentName.HISTORY,
            item_index=1,
        ),
        InputPart(
            role=PartRole.RETRIEVED,
            text="[SYNTHETIC] chunk",
            component=ComponentName.RETRIEVED,
            item_index=0,
        ),
        InputPart(
            role=PartRole.USER, text="[SYNTHETIC] now", component=ComponentName.MESSAGE
        ),
    )
    view = view_from_parts(parts)
    assert view.message == "[SYNTHETIC] now" and view.instructions == "[SYNTHETIC] ins"
    assert view.history == ("user: [SYNTHETIC] earlier", "assistant: [SYNTHETIC] reply")
    assert view.retrieved == "[SYNTHETIC] chunk"
    with pytest.raises(ValueError):
        view_from_parts(parts[:-1])


# --- P-3 labels -------------------------------------------------------------------

ARMS = ("syn-cheap", "syn-mid")
TIERS = {"syn-cheap": 0, "syn-mid": 1}
RECORDS = {f"r{i}": f"syn-m-{i}" for i in range(1, 7)}
J1 = {
    ("r1", "syn-cheap"): 0.5,
    ("r1", "syn-mid"): 1.0,  # both ok
    ("r2", "syn-cheap"): 0.0,
    ("r2", "syn-mid"): 0.75,  # cheap no, mid ok
    ("r3", "syn-cheap"): 1.0,
    ("r3", "syn-mid"): 0.0,  # judges disagree on cheap
    ("r4", "syn-cheap"): 0.0,
    ("r4", "syn-mid"): 0.0,  # none ok
    ("r5", "syn-cheap"): 1.0,
}  # mid not judged
J2 = {
    ("r1", "syn-cheap"): 0.75,
    ("r1", "syn-mid"): 0.5,
    ("r2", "syn-cheap"): 0.25,
    ("r2", "syn-mid"): 0.5,
    ("r3", "syn-cheap"): 0.0,
    ("r3", "syn-mid"): 0.0,
    ("r4", "syn-cheap"): 0.25,
    ("r4", "syn-mid"): 0.0,
    ("r5", "syn-cheap"): 1.0,
}


def _labels(**kw):
    args = dict(
        records=RECORDS,
        arms=ARMS,
        tiers=TIERS,
        acceptable_score=0.5,
        cheap_arms=("syn-cheap",),
        name="p1-pilot",
    )
    args.update(kw)
    return {r.record_id: r for r in lb.make_labels([J1, J2], **args)}


def test_labels_follow_both_judges_and_never_guess():
    rows = _labels()
    assert rows["r1"].cheap_ok is True and rows["r1"].min_adequate_tier == 0
    assert rows["r2"].cheap_ok is False and rows["r2"].min_adequate_tier == 1
    assert (
        rows["r3"].cheap_ok is None and rows["r3"].arm_acceptable["syn-cheap"] is None
    )
    assert rows["r3"].state == "not_labelled:judges_disagree_or_incomplete"
    assert rows["r4"].cheap_ok is False and rows["r4"].min_adequate_tier is None
    assert rows["r5"].cheap_ok is True and rows["r5"].arm_acceptable["syn-mid"] is None
    assert rows["r6"].state == "not_labelled:not_judged"
    assert {r.labels_source for r in rows.values()} == {"benchmark:p1-pilot"}


def test_labels_refuse_unset_owner_values_and_bad_inputs():
    with pytest.raises(OwnerValueUnset, match="labels.acceptable_score"):
        _labels(acceptable_score=None)
    with pytest.raises(OwnerValueUnset, match="labels.cheap_arms"):
        _labels(cheap_arms=None)
    with pytest.raises(ValueError, match="benchmark:<name>"):
        _labels(name="Bad Name")
    with pytest.raises(ValueError, match="cheap arms"):
        _labels(cheap_arms=("syn-x",))
    with pytest.raises(ValueError, match="two judges"):
        lb.make_labels(
            [J1],
            records=RECORDS,
            arms=ARMS,
            tiers=TIERS,
            acceptable_score=0.5,
            cheap_arms=("syn-cheap",),
            name="x",
        )


def test_label_file_and_summary_are_typed_and_content_free():
    rows = list(_labels().values())
    frame = lb.to_frame(rows, ARMS)
    assert list(frame.columns[: len(lb.COLUMNS)]) == list(lb.COLUMNS)
    assert str(frame["cheap_ok"].dtype) == "boolean"
    assert str(frame["min_adequate_tier"].dtype) == "Int64"
    summary = lb.summary(rows)
    assert summary["records"] == 6 and summary["cheap_ok"]["unknown"] == 2
    assert "syn-m" not in json.dumps(summary)  # no join keys in the summary


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_handoff_feeds_r_c3_fit_logistic_unchanged():
    """The label file goes into R-C3's own ``fit_logistic`` (exp-route-012,
    loaded by path, not edited): source accepted, NA rows dropped."""
    from metis_auto.analysis.levers import with_blocks

    v = _load(
        "exp_route_012_for_handoff",
        ROOT / "experiments/routing/exp-route-012-small-classifier/version.py",
    )
    try:
        rng = np.random.default_rng(7)
        n = 40
        req = with_blocks(
            pd.DataFrame(
                {
                    "session_id": [f"syn-s{i}" for i in range(n)],
                    "turn": 0,
                    "a_order": 0,
                    "bot_id": "bot-syn",
                    "user_id": "tenant-syn",
                    "u_h_norm": np.nan,
                    "u_n_chars": rng.integers(10, 400, n).astype(float),
                    "u_lang": "fa",
                    "n_prior_msgs": 0,
                    "prior_chars": 0.0,
                    "a_rag_n_queries": 0.0,
                    "u_att_n": 0.0,
                    "bot_n_functions": 0.0,
                    "bot_ins_n_chars": 300.0,
                    "bot_provider_name": "syn-provider",
                    "bot_provider_model": "syn-incumbent",
                    "a_billing_state": "items",
                    "a_bill_inputTokens": 100.0,
                    "a_bill_cachedInputTokens": 0.0,
                    "a_bill_outputTokens": 10.0,
                    "a_bill_totalCost": 0.01,
                    "a_n_per_call_only_items": 0,
                    "a_n_chars": 200,
                    "a_is_json": False,
                    "a_finish_reason": "STOP",
                    "a_tool_n_calls": 0,
                    "llm_request": True,
                    "user_message_id": [f"syn-m-{i}" for i in range(n)],
                }
            )
        )
        labelled = {f"r{i}": f"syn-m-{i}" for i in range(n - 5)}  # 5 unlabelled
        j = {
            (r, "syn-cheap"): float(req.loc[i, "u_n_chars"] < 200)
            for i, r in enumerate(labelled)
        }
        rows = lb.make_labels(
            [j, j],
            records=labelled,
            arms=("syn-cheap",),
            tiers={"syn-cheap": 0},
            acceptable_score=0.5,
            cheap_arms=("syn-cheap",),
            name="p1-pilot",
        )
        labels = lb.labels_for_requests(lb.to_frame(rows, ("syn-cheap",)), req)
        assert labels.isna().sum() == 5 and labels.index.equals(req.index)
        model = v.fit_logistic(
            req,
            labels,
            labels_source="benchmark:p1-pilot",
            l2=1.0,
            cached_separately=frozenset(),
        )
        assert model.labels_source == "benchmark:p1-pilot"
    finally:
        sys.modules.pop("exp_route_012_for_handoff", None)


def test_labels_for_requests_refuses_mixed_or_foreign_files():
    rows = list(_labels().values())
    frame = lb.to_frame(rows, ARMS)
    req = pd.DataFrame({"user_message_id": ["syn-m-1", "syn-m-2", "syn-x"]})
    out = lb.labels_for_requests(frame, req)
    assert out.tolist()[:2] == [True, False] and out.isna().tolist()[2]
    with pytest.raises(ValueError, match="benchmark-labels-v1"):
        lb.labels_for_requests(frame.assign(format="other"), req)
    with pytest.raises(ValueError, match="one labels_source"):
        lb.labels_for_requests(
            frame.assign(labels_source=["benchmark:a"] + ["benchmark:b"] * 5), req
        )
    with pytest.raises(ValueError, match="duplicate"):
        lb.labels_for_requests(pd.concat([frame, frame.iloc[:1]]), req)


# --- spot check -------------------------------------------------------------------


def test_spot_check_sheet_is_id_only_blinded_and_deterministic():
    from metis_auto.evaluation.judging.pairwise import PairOutcome

    outcomes = [
        PairOutcome(
            _item(f"c{i}", lang=["persian", "english", "mixed"][i % 3]),
            "judged",
            None,
            0.5,
            "tie",
            "tie",
            "tie",
            1,
            True,
            10,
            10,
            None,
        )
        for i in range(90)
    ] + [
        PairOutcome(
            _item("cx"),
            "not_evaluated",
            "answer_missing",
            None,
            None,
            None,
            None,
            0,
            None,
            None,
            None,
            None,
        )
    ]
    items = sc.select_items(outcomes, size=60, seed="s")
    assert items == sc.select_items(outcomes, size=60, seed="s")
    assert len(items) == 60 and "cx" not in {i.case_id for i in items}
    assert {i.language for i in items} == {"persian", "english", "mixed"}
    assert 0 < sum(i.candidate_first for i in items) < 60
    sheet = sc.sheet_rows(items)
    assert list(sheet[0]) == list(sc.SHEET_COLUMNS)
    assert sheet[0]["spot_id"] == "s01"
    flat = json.dumps(sheet)
    assert "syn-cheap" not in flat and "syn-ref" not in flat and "c1" not in flat


# --- review findings 1 and 2: swap-inconsistency and the gate on labels ---------------
# E5 already defines it: ``PairOutcome.swap_consistent`` is True when both
# orderings map to the same verdict (judging/pairwise.py, ``swap_consistent=
# mapped_a == mapped_b``); these tests use that definition, no new rule.


def _one_pair(replies):
    clock = FakeClock(NOW)
    answers = {
        ("c1", "syn-cheap"): "[SYNTHETIC] candidate",
        ("c1", "syn-ref"): "[SYNTHETIC] reference",
    }
    judge = _judge(Scripted(replies, clock), clock)
    return judge_all(judge, [_item("c1")], Content(answers), vision_candidates=None)


def test_swap_inconsistent_pair_is_not_a_tie():
    # order 1 (candidate shown first): "first" = the arm wins;
    # order 2 (reference shown first): "first" = the reference wins
    run = _one_pair(['{"choice": "first"}', '{"choice": "first"}'])
    (o,) = run.outcomes
    assert o.state == "inconsistent" and o.reason == "swap_inconsistent"
    assert o.score is None and o.preference is None  # never 0.5
    assert o.swap_consistent is False
    assert o.cost_usd == Decimal("0.0002")  # the two calls were paid
    assert run.cost_usd_total == Decimal("0.0002")
    assert run.judged == () and run.excluded_by_reason == {"swap_inconsistent": 1}


def test_genuine_tie_stays_tie():
    run = _one_pair(['{"choice": "tie"}', '{"choice": "tie"}'])
    (o,) = run.outcomes
    assert o.state == "judged" and o.score == 0.5 and o.preference == "tie"
    assert o.swap_consistent is True


def test_a_win_in_one_order_and_a_tie_in_the_other_is_inconsistent_by_the_e5_rule():
    run = _one_pair(['{"choice": "first"}', '{"choice": "tie"}'])
    (o,) = run.outcomes
    assert o.state == "inconsistent" and o.score is None


def test_consistent_win_is_unchanged():
    run = _one_pair(['{"choice": "first"}', '{"choice": "second"}'])
    (o,) = run.outcomes
    assert (o.state, o.score, o.preference) == ("judged", 1.0, "candidate")


def _one_row(j1, j2, inconsistent):
    return lb.make_labels(
        [j1, j2],
        records={"r1": "m1"},
        arms=("syn-cheap",),
        tiers={"syn-cheap": 0},
        acceptable_score=0.5,
        cheap_arms=("syn-cheap",),
        name="x",
        inconsistent=inconsistent,
    )


def test_inconsistent_gives_na_label():
    rows = _one_row({("r1", "syn-cheap"): 1.0}, {}, [set(), {("r1", "syn-cheap")}])
    (row,) = rows
    assert row.arm_acceptable == {"syn-cheap": None} and row.cheap_ok is None
    assert row.state == "not_labelled:inconsistent" and row.inconsistent_arms == 1
    assert lb.summary(rows)["states"] == {"not_labelled:inconsistent": 1}
    frame = lb.to_frame(rows, ("syn-cheap",))
    assert frame["acceptable:syn-cheap"].isna().all()


def test_one_judge_scoring_and_the_other_inconsistent_is_never_guessed():
    # judge 1 says "not acceptable"; judge 2's pair was inconsistent: unknown, not False
    (row,) = _one_row({("r1", "syn-cheap"): 0.0}, {}, [set(), {("r1", "syn-cheap")}])
    assert row.arm_acceptable["syn-cheap"] is None and row.cheap_ok is None


def test_an_inconsistent_arm_does_not_block_the_records_other_labels():
    rows = lb.make_labels(
        [
            {("r1", "syn-cheap"): 1.0, ("r1", "syn-mid"): 1.0},
            {("r1", "syn-cheap"): 1.0},
        ],
        records={"r1": "m1"},
        arms=ARMS,
        tiers=TIERS,
        acceptable_score=0.5,
        cheap_arms=("syn-cheap",),
        name="x",
        inconsistent=[set(), {("r1", "syn-mid")}],
    )
    (row,) = rows
    assert row.state == "labelled" and row.cheap_ok is True
    assert row.arm_acceptable == {"syn-cheap": True, "syn-mid": None}
    assert row.inconsistent_arms == 1


def test_without_inconsistency_input_labels_are_exactly_as_before():
    assert lb.make_labels(
        [J1, J2],
        records=RECORDS,
        arms=ARMS,
        tiers=TIERS,
        acceptable_score=0.5,
        cheap_arms=("syn-cheap",),
        name="x",
        inconsistent=None,
    ) == lb.make_labels(
        [J1, J2],
        records=RECORDS,
        arms=ARMS,
        tiers=TIERS,
        acceptable_score=0.5,
        cheap_arms=("syn-cheap",),
        name="x",
    )


def test_inconsistency_rate_per_judge_and_per_arm():
    rows = [
        ("j1", "syn-cheap", "judged"),
        ("j1", "syn-cheap", "inconsistent"),
        ("j1", "syn-mid", "judged"),
        ("j2", "syn-cheap", "judged"),
        ("j2", "syn-mid", "inconsistent"),
        ("j2", "syn-mid", "not_evaluated"),  # not a judged pair: not counted
    ]
    out = lb.inconsistency_summary(rows)
    assert out["per_judge"]["j1"] == {
        "pairs": 3,
        "inconsistent": 1,
        "rate": pytest.approx(1 / 3),
    }
    assert out["per_judge"]["j2"] == {"pairs": 2, "inconsistent": 1, "rate": 0.5}
    assert out["per_arm"]["syn-cheap"]["pairs"] == 3
    assert out["per_arm"]["syn-cheap"]["inconsistent"] == 1
    assert out["per_arm"]["syn-mid"] == {"pairs": 2, "inconsistent": 1, "rate": 0.5}
    assert lb.inconsistency_summary([]) == {"per_judge": {}, "per_arm": {}}
    summary = lb.summary(list(_labels().values()), inconsistency=out)
    assert summary["inconsistency"] == out


LANGS = {
    "r1": "persian",
    "r2": "persian",
    "r3": "english",
    "r4": "english",
    "r5": "mixed",
    "r6": "mixed",
}


def test_judge_gate_is_not_configured_by_default():
    rows = list(_labels().values())
    assert {r.judge_gate for r in rows} == {"not_configured"}
    frame = lb.to_frame(rows, ARMS)
    assert set(frame["judge_gate"]) == {"not_configured"}
    assert lb.summary(rows)["judge_gate"] == {"not_configured": 6}


def test_a_failed_gate_marks_the_rows_unvalidated_and_changes_no_value():
    gate = {"persian": "validated", "english": "unvalidated"}  # mixed: no result
    plain = _labels()
    gated = _labels(languages=LANGS, gate=gate)
    assert set(plain) == set(gated)  # nothing dropped
    for rid, row in plain.items():
        other = gated[rid]
        assert (
            row.state,
            row.cheap_ok,
            row.min_adequate_tier,
            row.arm_acceptable,
            row.arms_judged,
        ) == (
            other.state,
            other.cheap_ok,
            other.min_adequate_tier,
            other.arm_acceptable,
            other.arms_judged,
        )
    assert {r: gated[r].judge_gate for r in LANGS} == {
        "r1": "validated",
        "r2": "validated",
        "r3": "unvalidated",
        "r4": "unvalidated",
        "r5": "not_configured",
        "r6": "not_configured",
    }
    frame = lb.to_frame(list(gated.values()), ARMS)
    assert frame.set_index("record_id")["judge_gate"]["r3"] == "unvalidated"
    assert lb.summary(list(gated.values()))["judge_gate"] == {
        "not_configured": 2,
        "unvalidated": 2,
        "validated": 2,
    }
    req = pd.DataFrame({"user_message_id": ["syn-m-1", "syn-m-2"]})
    assert lb.labels_for_requests(frame, req).tolist() == [True, False]  # unchanged


def test_judge_gate_values_are_checked():
    with pytest.raises(ValueError, match="judge_gate"):
        _labels(languages=LANGS, gate={"persian": "maybe"})
