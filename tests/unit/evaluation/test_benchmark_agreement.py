"""P-2 spot-check agreement and the Persian gate for the benchmark (review
finding 3, ADR-0053 amendment 1): the filled sheet and the local key become
E5's rating import; agreement per judge and per language uses E5's functions;
the gate is E5's ``evaluate_gate``. [SYNTHETIC] sheets only, no model, no
network. Results are content-free."""

from __future__ import annotations

import csv
import io
import json

import pytest

from metis_auto.evaluation.benchmark import agreement as ag
from metis_auto.evaluation.judging.calibration import GateConfig

J1, J2 = "judge-one", "judge-two"
REF = "syn-ref"
CAND = "syn-cheap"
ACC = GateConfig(agreement_statistic="accuracy", min_agreement=0.8, min_items=5)
KAPPA = GateConfig(agreement_statistic="cohen_kappa", min_agreement=0.8, min_items=5)


def item_id(case):
    return f"{case}~{CAND}@-~{REF}@-"


def build(cases):
    """``cases``: dicts with case, language, candidate_is ("a" or "b"), human
    ("candidate" | "reference" | "tie" | None), judges {judge: score | "inconsistent"}.
    Returns the sheet text, the key text and the judges' score rows."""
    sheet = [("spot_id", "language", "rater", "rating", "note")]
    key = [("spot_id", "item_id", "candidate_is")]
    judge_rows = {J1: [], J2: []}
    for i, c in enumerate(cases, start=1):
        spot = f"s{i:02d}"
        key.append((spot, item_id(c["case"]), c["candidate_is"]))
        human = c.get("human")
        other = "b" if c["candidate_is"] == "a" else "a"
        rating = {
            "candidate": c["candidate_is"],
            "reference": other,
            "tie": "tie",
            None: "",
        }[human]
        raters = c.get("raters", ["r1"] if human else [])
        if human is None:
            sheet.append((spot, c["language"], "", "", ""))
        for n, rater in enumerate(raters):
            r = c.get("ratings", [rating] * len(raters))[n]
            sheet.append((spot, c["language"], rater, r, ""))
        for judge, value in c["judges"].items():
            row = {
                "judge_id": judge,
                "case_id": c["case"],
                "language": c["language"],
                "candidate": CAND,
                "reference": REF,
                "reason": None,
                "first_position_picks": 1,
                "cost_usd": None,
            }
            if value == "inconsistent":
                row |= {
                    "state": "inconsistent",
                    "score": None,
                    "swap_consistent": False,
                }
            else:
                row |= {"state": "judged", "score": value, "swap_consistent": True}
            judge_rows[judge].append(row)
    return _csv(sheet), _csv(key), judge_rows


def _csv(rows):
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


def case(n, language="persian", human="candidate", judge=1.0, **kw):
    return {
        "case": f"c{n}",
        "language": language,
        "candidate_is": "a" if n % 2 else "b",
        "human": human,
        "judges": {J1: judge, J2: judge},
        **kw,
    }


def report(cases, gate, **kw):
    sheet, key, rows = build(cases)
    return ag.agreement_report(
        run_id="run-syn",
        sheet_text=sheet,
        key_text=key,
        judge_rows=rows,
        gate=gate,
        **kw,
    )


def cell(rep, judge, language):
    return rep["judges"][judge][language]


def test_perfect_agreement_validates_the_gate():
    rep = report([case(n) for n in range(1, 11)], ACC)
    c = cell(rep, J1, "persian")
    assert c["agreement"]["state"] == "measured" and c["agreement"]["value"] == 1.0
    assert (c["n_rated"], c["status"]) == (10, "sufficient")
    assert c["gate"] == {"state": "validated", "reason": None}
    assert rep["judge_gate"] == {"persian": "validated"}
    assert rep["gate_configured"] is True


def test_chance_agreement_fails_the_gate_with_the_reason():
    humans = ["candidate", "reference"] * 4
    judges = [1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0]  # 4 of 8 agree, by chance
    cases = [
        case(n + 1, human=h, judge=j)
        for n, (h, j) in enumerate(zip(humans, judges, strict=True))
    ]
    acc = report(cases, ACC)
    assert cell(acc, J1, "persian")["agreement"]["value"] == 0.5
    assert cell(acc, J1, "persian")["gate"] == {
        "state": "unvalidated",
        "reason": "agreement_below_threshold",
    }
    assert acc["judge_gate"] == {"persian": "unvalidated"}
    kappa = report(cases, KAPPA)
    assert cell(kappa, J1, "persian")["agreement"]["value"] == pytest.approx(0.0)
    assert kappa["judge_gate"] == {"persian": "unvalidated"}


def test_missing_ratings_are_insufficient_not_validated():
    cases = [case(n) for n in range(1, 4)] + [case(n, human=None) for n in range(4, 11)]
    rep = report(cases, ACC)
    assert rep["sheet"]["items"] == 10 and rep["sheet"]["unrated_items"] == 7
    c = cell(rep, J1, "persian")
    assert (c["n_rated"], c["status"]) == (3, "insufficient")
    assert c["gate"] == {"state": "unvalidated", "reason": "n_below_min_items"}
    assert rep["judge_gate"] == {"persian": "unvalidated"}
    none = report([case(n, human=None) for n in range(1, 4)], ACC)
    c = cell(none, J1, "persian")
    assert (c["n_rated"], c["status"]) == (0, "insufficient")
    assert c["agreement"]["reason"] == "no_rated_items"


def test_gate_unset_is_not_configured_and_counts_still_reported():
    rep = report([case(n) for n in range(1, 8)], GateConfig())
    assert rep["gate_configured"] is False
    assert rep["judge_gate"] == {"persian": "not_configured"}
    c = cell(rep, J1, "persian")
    assert c["gate"] == {"state": "not_configured", "reason": None}
    assert c["status"] == "not_configured"
    assert c["agreement"]["state"] == "not_evaluated"
    assert c["agreement"]["reason"] == "agreement_statistic_unset"
    assert (c["pairs_in_sheet"], c["n_rated"]) == (7, 7)


def test_a_partly_set_gate_is_evaluated_and_unvalidated_with_the_reason():
    rep = report(
        [case(n) for n in range(1, 8)],
        GateConfig(agreement_statistic="accuracy", min_items=5),
    )
    assert rep["gate_configured"] is True
    assert cell(rep, J1, "persian")["gate"] == {
        "state": "unvalidated",
        "reason": "min_agreement_unset",
    }
    assert rep["judge_gate"] == {"persian": "unvalidated"}


def test_the_language_validates_only_if_both_judges_do():
    cases = [case(n) for n in range(1, 11)]
    for c in cases[:5]:
        c["judges"][J2] = 0.0  # judge two disagrees with the humans on half
    rep = report(cases, ACC)
    assert cell(rep, J1, "persian")["gate"]["state"] == "validated"
    assert cell(rep, J2, "persian")["gate"]["state"] == "unvalidated"
    assert rep["judge_gate"] == {"persian": "unvalidated"}


def test_languages_are_gated_separately():
    cases = [case(n) for n in range(1, 8)] + [
        case(n, language="english") for n in range(8, 11)
    ]
    rep = report(cases, ACC)
    assert rep["judge_gate"] == {"persian": "validated", "english": "unvalidated"}
    assert cell(rep, J1, "english")["gate"]["reason"] == "n_below_min_items"


def test_inconsistent_pairs_are_excluded_from_agreement_and_counted():
    cases = [case(n) for n in range(1, 9)]
    cases[0]["judges"][J1] = "inconsistent"
    cases[1]["judges"][J1] = "inconsistent"
    rep = report(cases, ACC)
    c = cell(rep, J1, "persian")
    assert (c["pairs_in_sheet"], c["inconsistent"], c["judged_consistent"]) == (8, 2, 6)
    assert c["n_rated"] == 6 and c["agreement"]["value"] == 1.0
    assert cell(rep, J2, "persian")["inconsistent"] == 0


def test_blinding_is_undone_by_the_key_and_raters_without_consensus_are_left_out():
    # rating "a" means the candidate when the key says the candidate was shown as A
    a_first = case(1, human="candidate")  # candidate_is "a": rating "a"
    b_first = case(2, human="candidate")  # candidate_is "b": rating "b"
    split = case(3, raters=["r1", "r2"], ratings=["a", "b"], judge=1.0)
    rep = report([a_first, b_first, split], ACC)
    c = cell(rep, J1, "persian")
    assert c["n_rated"] == 2 and c["agreement"]["value"] == 1.0
    assert rep["sheet"]["items_without_consensus"] == 1
    assert rep["sheet"]["raters"] == 2


def test_bad_sheets_are_refused_with_the_row_not_the_content():
    sheet, key, rows = build([case(n) for n in range(1, 4)])
    bad_rating = sheet.replace("s01,persian,r1,a,", "s01,persian,r1,maybe,")
    with pytest.raises(ValueError, match="row 2"):
        ag.agreement_report(
            run_id="r", sheet_text=bad_rating, key_text=key, judge_rows=rows, gate=ACC
        )
    unknown = sheet.replace("s02,", "s99,")
    with pytest.raises(ValueError, match="unknown spot_id"):
        ag.agreement_report(
            run_id="r", sheet_text=unknown, key_text=key, judge_rows=rows, gate=ACC
        )
    no_rater = sheet.replace("s01,persian,r1,a,", "s01,persian,,a,")
    with pytest.raises(ValueError, match="rater"):
        ag.agreement_report(
            run_id="r", sheet_text=no_rater, key_text=key, judge_rows=rows, gate=ACC
        )
    with pytest.raises(ValueError, match="columns"):
        ag.agreement_report(
            run_id="r",
            sheet_text="a,b\n1,2\n",
            key_text=key,
            judge_rows=rows,
            gate=ACC,
        )


def test_the_report_is_content_free_and_json_safe():
    rep = report([case(n) for n in range(1, 8)], ACC)
    text = json.dumps(rep)
    assert "syn-cheap" not in text and "c1" not in text and "~" not in text
    assert rep["format"] == "benchmark-agreement-v1" and rep["run_id"] == "run-syn"
    assert rep["gate"] == {
        "agreement_statistic": "accuracy",
        "min_agreement": 0.8,
        "min_items": 5,
    }


def test_gate_by_language_reads_the_report_or_says_not_configured():
    rep = report([case(n) for n in range(1, 8)], ACC)
    langs = ["persian", "english"]
    got = ag.gate_by_language(rep, ACC, langs)
    assert got == {
        "persian": "validated",
        "english": "unvalidated",
    }  # english: no result
    # the gate is not configured: every language says so, report or not
    assert ag.gate_by_language(rep, GateConfig(), langs) == {
        "persian": "not_configured",
        "english": "not_configured",
    }
    assert ag.gate_by_language(None, GateConfig(), langs) == dict.fromkeys(
        langs, "not_configured"
    )
    # configured but the spot-check was never scored
    assert ag.gate_by_language(None, ACC, langs) == dict.fromkeys(langs, "unvalidated")
