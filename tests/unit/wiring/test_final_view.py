"""The Results page reads ``final.json`` (sprint plan I-2; ADR-0050 amendment
draft). Every document and result here is SYNTHETIC. Rules: only the agreed
format (``final-v1``) is read, a document in another shape keeps the old note,
the provisional label and the units caveat are always shown, "not computed" is
text and never 0, and F-2's unexplained "other" block is shown for the recorded
baseline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.analysis.lever_result import LeverResult, Manifest
from metis_auto.wiring.lever_view import dashboard, load_final, load_view
from metis_auto.wiring.ui_config import LANGUAGES, load_strings

CAP = Decimal("0.35")


def _manifest() -> Manifest:
    return Manifest(
        data_revision="0" * 40,
        code_commit="unknown",
        config_hash="a" * 64,
        seed=7,
        price_version="prices-synthetic-1",
        python_version="3.13.5",
        created_at=datetime(2026, 11, 3, 9, 0, tzinfo=UTC),
    )


def _result() -> LeverResult:
    s = {
        "n_requests": Decimal(100),
        "baseline:total": Decimal(8),
        "saving:total": Decimal(2),
    }
    return LeverResult(
        lever_id="cache.synth_a.as_logged",
        step="cache",
        version="synth_a",
        n_requests=100,
        n_eligible=60,
        baseline="as_logged",
        baseline_cost={
            "fees": Decimal(2),
            "token_cost": Decimal(6),
            "total": Decimal(8),
        },
        saving={
            "fees": Decimal("0.5"),
            "token_cost": Decimal("1.5"),
            "total": Decimal(2),
        },
        slices={"all": s, "llm_only": s},
        evidence_class="simulation",
        correctness_state="unmeasured",
        assumptions=("synthetic fixture",),
        manifest=_manifest(),
    )


def final_doc() -> dict:
    def step(alone, combined, **extra):
        return {"alone": alone, "combined": combined, **extra}

    return {
        "format": "final-v1",
        "status": "provisional: cost only, pending quality",
        "units_caveat": "Recorded and price-file cost are never added.",
        "population": {"scored_requests": 100},
        "baselines": {
            "as_logged": {
                "unit": "recorded",
                "total": "100",
                "other_block": {"amount": "1", "share": 0.02, "note": "other"},
                "pipelines": {
                    "winners": {
                        "versions": {"cache": "c", "context": "x", "routing": "r"},
                        "steps": {
                            "cache": step("2", "2"),
                            "context": step("6", "6"),
                            "routing": step("10", "8"),
                        },
                        "combined_total": "16",
                        "standalone_sum": "18",
                        "sum_rule": {"holds": True, "equal": False},
                        "share_of_total": 0.16,
                        "waterfall": [
                            {
                                "kind": "baseline",
                                "label": "baseline cost",
                                "amount": "100",
                            },
                            {
                                "kind": "step",
                                "step": "cache",
                                "blocks": "fees",
                                "amount": "2",
                            },
                            {"kind": "after", "label": "cost after", "amount": "84"},
                        ],
                    },
                    "parham": {
                        "versions": {"routing": "r"},
                        "steps": {"routing": step("10", "10")},
                        "combined_total": "10",
                        "standalone_sum": "10",
                        "sum_rule": {"holds": True, "equal": True},
                        "share_of_total": 0.1,
                        "waterfall": None,
                    },
                },
            },
            "todays_models": {
                "unit": "price-file",
                "total": "60",
                "other_block": {"amount": None, "share": None, "note": "not computed"},
                "pipelines": {
                    "winners": {
                        "versions": {"cache": "c", "context": "x", "routing": "r"},
                        "steps": {
                            "cache": step(None, None, not_computed="no fee block"),
                            "context": step("7", "7"),
                            "routing": step("9", "8"),
                        },
                        "combined_total": "15",
                        "standalone_sum": "16",
                        "sum_rule": {"holds": True, "equal": False},
                        "share_of_total": 0.25,
                        "waterfall": None,
                    }
                },
            },
        },
    }


@pytest.fixture()
def folder(tmp_path: Path) -> Path:
    r = _result()
    (tmp_path / f"{r.lever_id}.json").write_text(r.to_json(), encoding="utf-8")
    return tmp_path


def board(folder: Path, final, **kw):
    kw.setdefault("lang", "en")
    kw.setdefault("baseline", "as_logged")
    return dashboard(
        load_view(folder), strings=load_strings(), tenant_cap=CAP, final=final, **kw
    )


def test_load_final_reads_only_the_agreed_format(folder):
    assert load_final(folder) is None  # absent
    (folder / "final.json").write_text('{"synthetic": true}', encoding="utf-8")
    assert load_final(folder) is None  # another shape
    (folder / "final.json").write_text("{not json", encoding="utf-8")
    assert load_final(folder) is None
    (folder / "final.json").write_text(json.dumps(final_doc()), encoding="utf-8")
    assert load_final(folder)["format"] == "final-v1"


def test_final_view_rows_follow_the_baseline(folder):
    d = board(folder, final_doc())
    assert d.final is not None
    names = [r.pipeline for r in d.final.rows]
    assert names == ["winners", "parham"]
    row = d.final.rows[0]
    assert row.combined.startswith("16") or "16" in row.combined
    assert row.rule_holds is True
    todays = board(folder, final_doc(), baseline="todays_models")
    assert [r.pipeline for r in todays.final.rows] == ["winners"]


def test_a_step_not_computed_in_the_units_is_text_not_zero(folder):
    d = board(folder, final_doc(), baseline="todays_models")
    cache = d.final.rows[0].steps["cache"]
    assert cache == load_strings().text("final_not_computed", "en")
    assert "0" not in cache.replace("computed", "")


def test_status_and_units_caveat_are_shown(folder):
    d = board(folder, final_doc())
    assert d.final.status == load_strings().text("final_status", "en")
    assert "provisional" in d.final.status.lower()
    assert d.final.units_caveat == load_strings().text("final_units", "en")
    assert d.combined_note == load_strings().text("combined_shown", "en")


def test_the_other_block_is_shown_for_recorded_units_only(folder):
    rec = board(folder, final_doc())
    assert rec.final.other_text and "2" in rec.final.other_text
    repriced = board(folder, final_doc(), baseline="todays_models")
    assert repriced.final.other_text == load_strings().text(
        "final_other_repriced", "en"
    )


def test_waterfall_rows_are_listed_for_a_pipeline_that_has_them(folder):
    d = board(folder, final_doc())
    assert [w.kind for w in d.final.waterfall] == ["baseline", "step", "after"]
    assert d.final.waterfall[1].label.lower().startswith("cache")


def test_a_document_in_another_shape_keeps_the_old_note(folder):
    d = board(folder, None, final_present=True)
    assert d.final is None
    assert d.combined_note == load_strings().text("combined_unformatted", "en")
    absent = board(folder, None)
    assert absent.combined_note == load_strings().text("combined_absent", "en")


def test_every_new_string_has_both_languages():
    strings = load_strings()
    keys = [
        k for k in strings.keys() if k.startswith("final_") or k == "combined_shown"
    ]
    assert len(keys) >= 8
    for key in keys:
        for lang in LANGUAGES:
            assert strings.text(key, lang), (key, lang)
