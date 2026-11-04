"""The bridge from a benchmark pilot to the evaluation framework (E1/E4/E6):
the answering run is rebuilt from the recordings and fed to the framework's own
``comparison_table``; judge scores (E5) supply quality per judge. SYNTHETIC
recordings, catalogue and prices; no network, no database. The report is
content-free (model names, counts and statistics only)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.contracts import (
    AnswerSource,
    ErrorClass,
    FinishReason,
    ModelCatalogue,
    ModelError,
    ModelResponse,
    PriceTable,
    TokenUsage,
)
from metis_auto.contracts.accounting import Fidelity
from metis_auto.evaluation.benchmark import framework_report as fr
from metis_auto.evaluation.sampling.tables import BootstrapSettings


def _limit(v):
    return {"value": v, "evidence": {"source": "synthetic", "checked_on": "2026-11-03"}}


def _entry(model, price_ref):
    return {
        "model_id": model,
        "provider": "openai",
        "provider_model_name": model,
        "tier": 0,
        "equivalence_group": "g0",
        "context_window": _limit(100_000),
        "max_output_tokens": _limit(10_000),
        "tokenizer_ref": "syn",
        "price_ref": price_ref,
        "enabled": True,
    }


def _price(ref, kind, amount):
    return {
        "price_ref": ref,
        "token_type": kind,
        "amount": amount,
        "per_tokens": 1_000_000,
        "currency": "USD",
        "evidence": {"source": "synthetic", "checked_on": "2026-11-03"},
    }


CATALOGUE = ModelCatalogue.model_validate(
    {"version": "cat-syn", "entries": [_entry("syn-a", "p-a"), _entry("syn-b", "p-b")]}
)
PRICES = PriceTable.model_validate(
    {
        "version": "prices-syn",
        "entries": [
            _price("p-a", "input", "1"),
            _price("p-a", "output", "2"),
            _price("p-b", "input", "3"),
            _price("p-b", "output", "6"),
        ],
    }
)
ENTRIES = {e.model_id: e for e in CATALOGUE.entries}
ARMS = ("syn-a", "syn-b")
J1, J2 = "judge-one", "judge-two"


def _usage(model, tokens_in, tokens_out):
    return TokenUsage(
        model_id=model,
        input=ex.tokens(tokens_in, Fidelity.PROVIDER_REPORTED),
        output=ex.tokens(tokens_out, Fidelity.PROVIDER_REPORTED),
    )


def _record(case, model, *, error=None, source="live", latency=100.0, i=1000, o=500):
    inv = ex.model_invocation().model_copy(
        update={"model_id": model, "case_id": case, "request_id": f"run.{case}"}
    )
    if error:
        result = ModelError(error_class=error, retryable=True, source=AnswerSource.LIVE)
    else:
        result = ModelResponse(
            text="[SYNTHETIC] answer",
            finish_reason=FinishReason.COMPLETE,
            usage=_usage(model, i, o),
            provider_latency_ms=latency,
            source=AnswerSource.LIVE,
        )
    return {
        "invocation": inv.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "client_source": source,
    }


def _judge_record(case, model):
    rec = _record(case, "judge-model")
    rec["invocation"]["request_id"] = f"run.judge.{case}"
    return rec


def _run(records, cases=("c1", "c2", "c3")):
    return fr.recorded_run(
        records, case_ids=cases, arms=ARMS, catalogue=ENTRIES, prices=PRICES
    )


def test_cost_is_computed_from_the_recorded_usage():
    run = _run([_record("c1", "syn-a", i=1000, o=500)], cases=("c1",))
    (r,) = [r for r in run.records if r.model_id == "syn-a"]
    # 1000 * 1/1e6 + 500 * 2/1e6
    assert r.cost_usd == Decimal("0.002") and r.cost_state == "reported"
    assert (r.input_tokens, r.output_tokens, r.latency_ms) == (1000, 500, 100.0)
    assert r.provenance == "measured" and r.source == "live"


def test_a_success_beats_an_error_for_the_same_pair():
    records = [
        _record("c1", "syn-a", error=ErrorClass.CONNECTION),
        _record("c1", "syn-a", latency=7.0),
    ]
    run = _run(records, cases=("c1",))
    (r,) = [r for r in run.records if r.model_id == "syn-a"]
    assert r.outcome == "response" and r.latency_ms == 7.0


def test_an_error_alone_is_kept_as_an_error_not_dropped():
    run = _run([_record("c1", "syn-a", error=ErrorClass.CONNECTION)], cases=("c1",))
    (r,) = run.records
    assert r.outcome == "error" and r.error_class == "connection"
    assert r.cost_usd is None


def test_judge_calls_and_non_live_records_are_not_answers():
    records = [
        _judge_record("c1", "x"),
        _record("c1", "syn-a", source="fake"),
        _record("c1", "syn-b"),
    ]
    run = _run(records, cases=("c1",))
    assert [r.model_id for r in run.records] == ["syn-b"]


def test_the_run_says_it_was_rebuilt_and_counts_what_is_missing():
    run = _run([_record("c1", "syn-a"), _record("c2", "syn-a")])
    assert run.planned_calls == 6  # 3 cases x 2 arms
    assert run.executed_calls == 2 and run.skipped_calls == 4
    assert run.stop_rules == {"source": "reconstructed_from_recordings"}
    assert run.realized_usd == Decimal("0.004")
    assert run.sources == ("recorded",)


def _report(records, scores, *, languages=None, **kw):
    run = _run(records)
    langs = languages or {"c1": "persian", "c2": "persian", "c3": "english"}
    return fr.framework_report(
        run,
        scores,
        langs,
        min_n=kw.pop("min_n", None),
        bootstrap=kw.pop("bootstrap", None),
        gate=kw.pop("gate", None),
        run_id="pilot-syn",
        **kw,
    )


RECORDS = [
    _record("c1", "syn-a", latency=100.0),
    _record("c2", "syn-a", latency=300.0),
    _record("c3", "syn-a", latency=50.0),
    _record("c1", "syn-b", i=2000, o=1000, latency=10.0),
    _record("c2", "syn-b", error=ErrorClass.CONNECTION),
]
SCORES = {
    J1: {("c1", "syn-a"): 1.0, ("c2", "syn-a"): 0.0, ("c1", "syn-b"): 0.5},
    J2: {("c1", "syn-a"): 1.0},
}


def _rows(rep, judge=None):
    return {
        (r["language"], r["model_id"]): r for r in rep["tables"][judge or J1]["rows"]
    }


def test_the_table_is_persian_first_and_one_row_per_language_and_model():
    rep = _report(RECORDS, SCORES)
    keys = [(r["language"], r["model_id"]) for r in rep["tables"][J1]["rows"]]
    assert keys[0][0] == "fa"  # the primary language, mapped from "persian"
    assert ("fa", "syn-a") in keys and ("en", "syn-a") in keys
    assert ("fa", "syn-b") in keys


def test_cost_and_latency_come_from_the_framework_not_from_new_arithmetic():
    row = _rows(_report(RECORDS, SCORES))[("fa", "syn-a")]
    assert row["n_calls"] == 2 and row["n_answered"] == 2
    assert row["cost_mean_usd"]["value"] == pytest.approx(0.002)
    assert row["latency_total_ms"]["value"] == pytest.approx(200.0)  # mean of 100, 300


def test_an_error_is_counted_in_the_error_share():
    row = _rows(_report(RECORDS, SCORES))[("fa", "syn-b")]
    assert row["n_calls"] == 2 and row["n_answered"] == 1
    assert row["error_share"] == pytest.approx(0.5)


def test_quality_is_per_judge_never_combined_and_marked_unvalidated():
    rep = _report(RECORDS, SCORES)
    q1 = _rows(rep, J1)[("fa", "syn-a")]["quality"]
    q2 = _rows(rep, J2)[("fa", "syn-a")]["quality"]
    assert q1["value"] == pytest.approx(0.5) and q1["n"] == 2  # (1 + 0) / 2
    assert q2["value"] == pytest.approx(1.0) and q2["n"] == 1
    assert q1["extra"]["validated"] == "no"
    assert q1["provenance"] == "estimated"
    assert set(rep["tables"]) == {J1, J2}  # no merged "all judges" table


def test_a_judge_with_no_scores_for_a_group_says_not_evaluated():
    q = _rows(_report(RECORDS, SCORES), J2)[("en", "syn-a")]["quality"]
    assert q["state"] == "not_evaluated" and q["reason"] == "no_judge_scores"


def test_rows_are_descriptive_until_a_minimum_n_is_set():
    row = _rows(_report(RECORDS, SCORES))[("fa", "syn-a")]
    assert row["label"] == "descriptive"
    ranked = _rows(_report(RECORDS, SCORES, min_n=2))[("fa", "syn-a")]
    assert ranked["label"] == "rankable"


def test_a_bootstrap_adds_an_interval_only_when_asked_for():
    plain = _rows(_report(RECORDS, SCORES))[("fa", "syn-a")]["quality"]
    assert plain["interval"] is None
    boot = BootstrapSettings(n_boot=200, seed="syn", level=0.9)
    with_ci = _rows(_report(RECORDS, SCORES, bootstrap=boot, min_n=1))[("fa", "syn-a")]
    assert with_ci["quality"]["method"] is not None


def test_the_gate_is_passed_through_as_given_and_defaults_to_not_configured():
    assert _report(RECORDS, SCORES)["judge_gate"] == {
        "fa": "not_configured",
        "en": "not_configured",
    }
    given = _report(RECORDS, SCORES, gate={"fa": "validated", "en": "unvalidated"})
    assert given["judge_gate"] == {"fa": "validated", "en": "unvalidated"}


def test_the_report_states_how_it_was_made_and_is_content_free():
    rep = _report(RECORDS, SCORES)
    assert rep["format"] == "benchmark-framework-report-v1"
    assert rep["run_id"] == "pilot-syn"
    assert rep["reconstructed"] is True
    text = json.dumps(rep)
    for forbidden in ("[SYNTHETIC]", "c1", "c2", "c3", "run."):
        assert forbidden not in text
    assert "syn-a" in text  # model names are not content


def test_the_markdown_lists_every_judge_and_marks_quality_unvalidated():
    md = fr.to_markdown(_report(RECORDS, SCORES))
    assert J1 in md and J2 in md and "syn-a" in md
    assert "reconstructed" in md.lower() and "not validated" in md.lower()
    assert "c1" not in md
